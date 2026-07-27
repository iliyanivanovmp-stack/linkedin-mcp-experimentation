from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SYSTEM_DIR = ROOT
CONFIG = SYSTEM_DIR / "config.json"
FEEDER_CONFIG = SYSTEM_DIR / "feeder_config.json"


def load_env() -> dict[str, str]:
    env = os.environ.copy()
    path = SYSTEM_DIR / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def run(name: str, command: list[str], env: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    try:
        result: object = json.loads(completed.stdout) if completed.stdout.strip() else None
    except json.JSONDecodeError:
        result = completed.stdout.strip()
    return {
        "step": name,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "result": result,
        "stderr": completed.stderr.strip(),
    }


def result_metrics(results: list[dict[str, object]]) -> dict[str, object]:
    metrics: dict[str, object] = {"companies_inserted": 0, "contacts_inserted": 0, "contacts_plugged": 0, "failures": 0}
    for step in results:
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        if step.get("step") == "collect_hiring_signals":
            google = result.get("google_sheet_result") or {}
            if isinstance(google, dict):
                metrics["companies_inserted"] = int(google.get("inserted", 0) or 0)
        elif step.get("step") == "extract_contacts":
            metrics["contacts_inserted"] = int(result.get("contacts_inserted", 0) or 0)
        elif str(step.get("step", "")).startswith("feed_"):
            metrics["contacts_plugged"] = int(metrics["contacts_plugged"]) + int(result.get("plugged", 0) or 0)
            metrics["failures"] = int(metrics["failures"]) + int(result.get("failed", 0) or 0)
            source_errors = result.get("source_errors") or []
            if isinstance(source_errors, list):
                metrics["failures"] = int(metrics["failures"]) + len(source_errors)
    return metrics


def notify_result(env: dict[str, str], payload: dict[str, object]) -> None:
    url = env.get("PIPELINE_ENGINE_HIRING_RESULT_WEBHOOK_URL", "").strip()
    if not url:
        return
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=15).close()
    except Exception:
        # Monitoring must never change the pipeline outcome.
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--company-limit", type=int)
    parser.add_argument("--sourcing-limit", type=int)
    parser.add_argument("--skip-sourcing", action="store_true")
    parser.add_argument("--skip-email-enrichment", action="store_true")
    args = parser.parse_args()
    dry = ["--dry-run"] if args.dry_run else []
    company_limit = ["--limit", str(args.company_limit)] if args.company_limit is not None else []
    contact_limit = ["--limit", "30"]
    env = load_env()
    feeder_command = [
        sys.executable,
        str(SYSTEM_DIR / "feed_lemlist.py"),
        "--config", str(FEEDER_CONFIG),
        "--source", "hiring",
        "--source", "hiring_linkedin_only",
        *dry,
        *contact_limit,
    ]
    # Flush contacts left by an interrupted previous run before starting the
    # slower LinkedIn and enrichment stages. This makes retries self-healing.
    commands: list[tuple[str, list[str]]] = [
        ("feed_existing_contacts", feeder_command),
    ]
    if not args.skip_sourcing:
        sourcing_python = env.get("LINKEDIN_PYTHON", sys.executable)
        sourcing_limit = ["--limit", str(args.sourcing_limit)] if args.sourcing_limit is not None else []
        commands.append(("collect_hiring_signals", [
            sourcing_python,
            str(SYSTEM_DIR / "collect_hiring_signals.py"),
            "--config", str(SYSTEM_DIR / "sourcing_config.json"),
            "--system-config", str(CONFIG),
            *dry,
            *sourcing_limit,
        ]))
    commands.extend([
        ("recover_company_domains", [sys.executable, str(SYSTEM_DIR / "recover_company_domains.py"), "--config", str(CONFIG), *dry, *company_limit]),
        ("prepare_context", [sys.executable, str(SYSTEM_DIR / "prepare_context.py"), "--config", str(CONFIG), *dry, *company_limit]),
        ("extract_contacts", [sys.executable, str(SYSTEM_DIR / "extract_contacts.py"), "--config", str(CONFIG), "--retry-failed", *dry, *company_limit]),
    ])
    if not args.skip_email_enrichment:
        commands.extend([
            ("email_enrichment_start", [sys.executable, str(SYSTEM_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "start", *dry, *contact_limit]),
            ("email_enrichment_poll", [sys.executable, str(SYSTEM_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "poll", *dry, *contact_limit]),
            ("apollo_email_fallback", [sys.executable, str(SYSTEM_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "apollo", *dry, *contact_limit]),
            ("finalize_linkedin_only", [sys.executable, str(SYSTEM_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "finalize-linkedin-only", *dry, *contact_limit]),
        ])
    commands.append(("feed_new_contacts", feeder_command))

    results = []
    started_at = datetime.now(timezone.utc)
    for name, command in commands:
        result = run(name, command, env)
        results.append(result)
        if not result["ok"]:
            payload = {"status": "error", "started_at": started_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "metrics": result_metrics(results), "steps": results}
            notify_result(env, payload)
            print(json.dumps(payload, indent=2))
            raise SystemExit(1)
    payload = {"status": "success", "dry_run": args.dry_run, "started_at": started_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "metrics": result_metrics(results), "steps": results}
    notify_result(env, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
