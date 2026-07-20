from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FUNNEL_DIR = ROOT
FEEDER = ROOT / "feeder.py"
FEEDER_CONFIG = ROOT / "feeder_config.json"


def load_env_file(path: Path = ROOT / ".env") -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def run_step(name: str, command: list[str], env: dict[str, str], continue_on_error: bool) -> dict[str, object]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    parsed = None
    if process.stdout.strip():
        try:
            parsed = json.loads(process.stdout)
        except json.JSONDecodeError:
            parsed = process.stdout.strip()
    result = {
        "step": name,
        "returncode": process.returncode,
        "ok": process.returncode == 0,
        "result": parsed,
        "stderr": process.stderr.strip(),
    }
    if process.returncode != 0 and not continue_on_error:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def should_alert(results: list[dict[str, object]]) -> tuple[bool, str]:
    failed_steps = [str(step["step"]) for step in results if not step.get("ok")]
    monitor = next((step for step in results if step.get("step") == "monitor"), None)
    attention_counts = {}
    if monitor and isinstance(monitor.get("result"), dict):
        attention_counts = dict(monitor["result"].get("attention_counts", {}))  # type: ignore[index, union-attr]
    attention_total = sum(int(value or 0) for value in attention_counts.values())
    if failed_steps or attention_total:
        lines = ["Pipeline gap downstream alert"]
        if failed_steps:
            lines.append(f"Failed steps: {', '.join(failed_steps)}")
        if attention_counts:
            lines.append(
                "Attention counts: "
                + ", ".join(f"{key}={value}" for key, value in attention_counts.items())
            )
        return True, "\n".join(lines)
    return False, ""


def send_slack_alert(env: dict[str, str], text: str) -> None:
    webhook = env.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"text": text}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "linkedin-mcp-experimentation/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=15):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-apollo", action="store_true")
    parser.add_argument("--skip-email-enrichment", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--no-slack-alerts", action="store_true")
    args = parser.parse_args()

    env = load_env_file()
    dry = ["--dry-run"] if args.dry_run else []
    limit = ["--limit", str(args.limit)] if args.limit is not None else []
    steps: list[tuple[str, list[str]]] = [
        ("prepare_outreach_context", [sys.executable, str(FUNNEL_DIR / "prepare_outreach_context.py"), *dry, *limit]),
        ("extract_contacts", [sys.executable, str(FUNNEL_DIR / "extract_contacts.py"), *dry, *limit]),
        ("sync_contact_context", [sys.executable, str(FUNNEL_DIR / "sync_contact_context.py"), *dry, *limit]),
    ]
    if not args.skip_email_enrichment:
        steps.extend([
            ("lemlist_email_enrichment_start", [sys.executable, str(FUNNEL_DIR / "enrich_missing_emails.py"), "--mode", "start", *dry, *limit]),
            ("lemlist_email_enrichment_poll", [sys.executable, str(FUNNEL_DIR / "enrich_missing_emails.py"), "--mode", "poll", *dry, *limit]),
        ])
        if not args.skip_apollo:
            steps.append(("apollo_email_fallback", [sys.executable, str(FUNNEL_DIR / "enrich_missing_emails.py"), "--mode", "apollo", *dry, *limit]))
        steps.append(("finalize_linkedin_only", [sys.executable, str(FUNNEL_DIR / "enrich_missing_emails.py"), "--mode", "finalize-linkedin-only", *dry, *limit]))
    steps.extend([
        ("feed_pipeline_gap", [sys.executable, str(FEEDER), "--config", str(FEEDER_CONFIG), "--source", "pipeline_gap", *dry, *limit]),
        ("feed_pipeline_gap_linkedin_only", [sys.executable, str(FEEDER), "--config", str(FEEDER_CONFIG), "--source", "pipeline_gap_linkedin_only", *dry, *limit]),
        ("monitor", [sys.executable, str(FUNNEL_DIR / "monitor_pipeline_gap_system.py")]),
    ])

    results = []
    status = "success"
    try:
        for name, command in steps:
            results.append(run_step(name, command, env, args.continue_on_error))
    except Exception as exc:
        status = "error"
        if not args.no_slack_alerts:
            try:
                send_slack_alert(env, f"Pipeline gap downstream failed\n{exc}")
            except Exception:
                pass
        print(json.dumps({"status": status, "error": str(exc), "steps": results}, indent=2))
        sys.exit(1)
    if any(not step["ok"] for step in results):
        status = "partial_failure"
    alert, text = should_alert(results)
    if status == "success" and alert:
        status = "attention_required"
    if not args.no_slack_alerts:
        if alert:
            send_slack_alert(env, text)
    print(json.dumps({"status": status, "dry_run": args.dry_run, "steps": results}, indent=2))


if __name__ == "__main__":
    main()
