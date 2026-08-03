from __future__ import annotations

import json
import hmac
import os
import subprocess
import sys
from pathlib import Path

import modal


app = modal.App("technology-based-outreach")
WORKFLOW_DIR = Path(__file__).resolve().parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi>=0.115",
        "google-auth>=2.40",
        "gspread>=6.2",
    )
    .add_local_dir(
        str(WORKFLOW_DIR),
        remote_path="/root/workflow",
    )
)

secrets = [
    modal.Secret.from_name("technology-outreach-secrets"),
    modal.Secret.from_name("technology-outreach-reacher"),
]


def _run(*extra_args: str) -> dict:
    process = subprocess.run(
        [
            sys.executable,
            "/root/workflow/run_system.py",
            *extra_args,
        ],
        cwd="/root/workflow",
        text=True,
        capture_output=True,
        check=False,
    )
    parsed: object = None
    if process.stdout.strip():
        try:
            parsed = json.loads(process.stdout)
        except json.JSONDecodeError:
            parsed = process.stdout.strip()
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "result": parsed,
        "stderr": process.stderr.strip(),
    }


@app.function(image=image, secrets=secrets, timeout=1800)
def run_pipeline(dry_run: bool = True) -> dict:
    return _run("--dry-run") if dry_run else _run()


@app.function(image=image, secrets=secrets, timeout=1800)
def daily_cycle() -> dict:
    return _run()


@app.function(image=image, secrets=secrets, timeout=1800)
@modal.fastapi_endpoint(method="POST")
def technology_daily_trigger(token: str = ""):
    from fastapi import HTTPException

    trigger_token = os.environ.get("TECHNOLOGY_TRIGGER_TOKEN", "").strip()
    if not trigger_token:
        raise HTTPException(status_code=500, detail="Missing trigger credential")
    if not hmac.compare_digest(str(token).strip(), trigger_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = _run()
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result)
    return result


@app.local_entrypoint()
def main(dry_run: bool = True) -> None:
    print(run_pipeline.remote(dry_run=dry_run))
