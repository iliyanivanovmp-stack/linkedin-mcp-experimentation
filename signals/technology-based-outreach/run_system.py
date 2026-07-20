from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TECH_DIR = ROOT
CONFIG = TECH_DIR / "config.json"
FEEDER_CONFIG = TECH_DIR / "feeder_config.json"


def load_env() -> dict[str, str]:
    env = os.environ.copy()
    path = TECH_DIR / ".env"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--company-limit", type=int)
    parser.add_argument("--skip-email-enrichment", action="store_true")
    args = parser.parse_args()
    dry = ["--dry-run"] if args.dry_run else []
    company_limit = ["--limit", str(args.company_limit)] if args.company_limit is not None else []
    contact_limit = ["--limit", "30"]
    commands = [
        ("prepare_context", [sys.executable, str(TECH_DIR / "prepare_context.py"), "--config", str(CONFIG), *dry, *company_limit]),
        ("extract_contacts", [sys.executable, str(TECH_DIR / "extract_contacts.py"), "--config", str(CONFIG), *dry, *company_limit]),
    ]
    if not args.skip_email_enrichment:
        commands.extend([
            ("email_enrichment_start", [sys.executable, str(TECH_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "start", *dry, *contact_limit]),
            ("email_enrichment_poll", [sys.executable, str(TECH_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "poll", *dry, *contact_limit]),
            ("apollo_email_fallback", [sys.executable, str(TECH_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "apollo", *dry, *contact_limit]),
            ("finalize_linkedin_only", [sys.executable, str(TECH_DIR / "enrich_missing_emails.py"), "--config", str(CONFIG), "--mode", "finalize-linkedin-only", *dry, *contact_limit]),
        ])
    commands.append(("feed_lemlist", [
        sys.executable,
        str(TECH_DIR / "feed_lemlist.py"),
        "--config", str(FEEDER_CONFIG),
        "--source", "technology",
        "--source", "technology_linkedin_only",
        *dry,
        *contact_limit,
    ]))

    env = load_env()
    results = []
    for name, command in commands:
        result = run(name, command, env)
        results.append(result)
        if not result["ok"]:
            print(json.dumps({"status": "error", "steps": results}, indent=2))
            sys.exit(1)
    print(json.dumps({"status": "success", "dry_run": args.dry_run, "steps": results}, indent=2))


if __name__ == "__main__":
    main()
