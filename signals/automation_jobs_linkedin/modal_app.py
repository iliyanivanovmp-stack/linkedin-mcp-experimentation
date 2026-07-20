"""
Automation Jobs LinkedIn Signal — Modal deployment
Scrapes LinkedIn daily for AI/automation contract jobs and writes to Google Sheet + Slack.

──────────────────────────────────────────────────────────────────────────────
BOOTSTRAP (one-time setup):

  1. Create the state volume (no LinkedIn cookies or browser are required):
       modal volume create automation-jobs-linkedin-session

  2. Create the Modal secret (credentials stored as base64 to avoid shell-escaping issues):
       GOOGLE_CREDENTIALS_B64=$(base64 -i /path/to/credentials.json)
       modal secret create automation-jobs-linkedin-secrets \
         GOOGLE_CREDENTIALS_B64="$GOOGLE_CREDENTIALS_B64" \
         AUTOMATION_JOBS_SHEET_ID="1GmV-FEfYKEIODbpJanLqxlMDbjMa7DHijNJtnZZpsnk" \
         SLACK_WEBHOOK_URL="https://hooks.slack.com/..." \
         --force
       modal secret create automation-jobs-linkedin-trigger \
         TRIGGER_TOKEN="<long-random-token>" --force

  3. Deploy:
       modal deploy signals/automation_jobs_linkedin/modal_app.py

SCHEDULE:
  n8n runs daily at 5 PM Europe/Sofia and sends:
    Authorization: Bearer <TRIGGER_TOKEN>
  Configure n8n with the Europe/Sofia timezone so daylight saving is automatic.

MANUAL RUN:
  modal run signals/automation_jobs_linkedin/modal_app.py
  modal run signals/automation_jobs_linkedin/modal_app.py --reset-state
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import hmac
import os
import subprocess
import tempfile
from pathlib import Path

import modal

app = modal.App("automation-jobs-linkedin")

SIGNAL_DIR = Path(__file__).resolve().parent
LINKEDIN_PYTHON = "/usr/local/bin/python"
# Stored in the volume so deduplication persists across daily runs
STATE_PATH = "/root/.linkedin-mcp/automation_jobs_seen.json"

linkedin_session = modal.Volume.from_name(
    "automation-jobs-linkedin-session",
    create_if_missing=False,
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]==0.116.1",
        "gspread==6.2.1",
        "google-auth==2.55.1",
    )
    .add_local_dir(str(SIGNAL_DIR), remote_path="/root/signal")
)

secrets = [
    modal.Secret.from_name("automation-jobs-linkedin-secrets"),
    modal.Secret.from_name("automation-jobs-linkedin-trigger"),
]


def _run(reset_state: bool = False) -> dict:
    import base64
    creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_B64", "")
    if not creds_b64:
        return {"ok": False, "returncode": 78, "result": None,
                "stderr": "GOOGLE_CREDENTIALS_B64 is not configured"}
    try:
        creds_json = base64.b64decode(creds_b64, validate=True).decode("utf-8")
        json.loads(creds_json)
    except Exception as exc:
        return {"ok": False, "returncode": 78, "result": None,
                "stderr": f"GOOGLE_CREDENTIALS_B64 is invalid: {type(exc).__name__}"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(creds_json)
        creds_path = f.name

    cmd = [
        LINKEDIN_PYTHON,
        "/root/signal/track_jobs.py",
        "--credentials", creds_path,
        "--state", STATE_PATH,
    ]
    if reset_state:
        cmd.append("--reset-state")

    try:
        process = subprocess.run(
            cmd, cwd="/root/signal", env=os.environ.copy(),
            text=True, capture_output=True, check=False,
        )
    finally:
        Path(creds_path).unlink(missing_ok=True)
    try:
        parsed: object = json.loads(process.stdout) if process.stdout.strip() else None
    except json.JSONDecodeError:
        parsed = process.stdout.strip()
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "result": parsed,
        "stderr": process.stderr.strip(),
    }


def _is_authorized(authorization: str | None, expected_token: str) -> bool:
    if not expected_token or not authorization:
        return False
    scheme, separator, supplied = authorization.partition(" ")
    return bool(
        separator
        and scheme.casefold() == "bearer"
        and hmac.compare_digest(supplied.strip(), expected_token)
    )


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/root/.linkedin-mcp": linkedin_session},
    timeout=1200,
    max_containers=1,
)
@modal.asgi_app()
def run_daily():
    """Authenticated HTTP endpoint for the n8n daily trigger."""
    from fastapi import FastAPI, Header, HTTPException

    web = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @web.post("/")
    def execute(authorization: str | None = Header(default=None)) -> dict:
        expected = os.environ.get("TRIGGER_TOKEN", "").strip()
        if not _is_authorized(authorization, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")
        result = _run(reset_state=False)
        if not result["ok"]:
            raise HTTPException(status_code=500, detail=result)
        linkedin_session.commit()
        return result

    return web


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/root/.linkedin-mcp": linkedin_session},
    timeout=1200,
    max_containers=1,
)
def run_once(reset_state: bool = False) -> dict:
    result = _run(reset_state=reset_state)
    if result["ok"]:
        linkedin_session.commit()
    return result


@app.local_entrypoint()
def main(reset_state: bool = False) -> None:
    print(json.dumps(run_once.remote(reset_state=reset_state), indent=2))
