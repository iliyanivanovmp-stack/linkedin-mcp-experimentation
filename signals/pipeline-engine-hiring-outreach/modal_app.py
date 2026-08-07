from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

import modal
from fastapi import Header


app = modal.App("pipeline-engine-hiring-outreach")
WORKFLOW_DIR = Path(__file__).resolve().parent
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi==0.115.14",
        "google-auth==2.49.1",
        "gspread==6.2.1",
    )
    .add_local_dir(
        str(WORKFLOW_DIR),
        remote_path="/root/workflow",
    )
)

secrets = [
    modal.Secret.from_name("pipeline-engine-hiring-outreach-secrets"),
    modal.Secret.from_name("pipeline-engine-hiring-trigger-secret"),
    modal.Secret.from_name("pipeline-engine-hiring-result-callback"),
    modal.Secret.from_name("pipeline-engine-hiring-slack"),
    modal.Secret.from_name("linkedin-mcp-auth"),
]


def _run(*extra_args: str) -> dict:
    env = os.environ.copy()
    process = subprocess.run(
        [sys.executable, "/root/workflow/run_system.py", *extra_args],
        cwd="/root/workflow",
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
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


@app.function(
    image=image,
    secrets=secrets,
    timeout=3600,
    max_containers=1,
)
def run_pipeline(
    dry_run: bool = True,
    company_limit: int | None = None,
    skip_sourcing: bool = True,
    sourcing_limit: int | None = None,
) -> dict:
    args: list[str] = []
    if dry_run:
        args.append("--dry-run")
    if company_limit is not None:
        args.extend(["--company-limit", str(company_limit)])
    if skip_sourcing:
        args.append("--skip-sourcing")
    if sourcing_limit is not None:
        args.extend(["--sourcing-limit", str(sourcing_limit)])
    return _run(*args)


@app.function(
    image=image,
    secrets=secrets,
    timeout=3600,
    max_containers=1,
)
def run_production_pipeline() -> dict:
    """Run production asynchronously so the scheduler is not tied to HTTP timeouts."""
    return _run()


@app.function(
    image=image,
    secrets=secrets,
    timeout=300,
    max_containers=1,
)
@modal.fastapi_endpoint(method="POST")
def pipeline_engine_hiring_daily_trigger(authorization: str = Header(default="")):
    from fastapi import HTTPException

    expected = os.environ.get("PIPELINE_ENGINE_HIRING_TRIGGER_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="Missing trigger credential")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
    call = run_production_pipeline.spawn()
    return {"ok": True, "accepted": True, "call_id": call.object_id}


@app.local_entrypoint()
def main(
    dry_run: bool = True,
    company_limit: int = 3,
    skip_sourcing: bool = True,
    sourcing_limit: int | None = None,
) -> None:
    print(run_pipeline.remote(
        dry_run=dry_run,
        company_limit=company_limit,
        skip_sourcing=skip_sourcing,
        sourcing_limit=sourcing_limit,
    ))
