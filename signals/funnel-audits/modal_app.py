from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import modal


app = modal.App("funnel-audit-system")
WORKFLOW_DIR = Path(__file__).resolve().parent
volume = modal.Volume.from_name("funnel-audit-data", create_if_missing=True)
DISPATCH_STATUS_PATH = Path("/data/scheduled-dispatcher-status.json")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "libnss3",
        "libatk1.0-0",
        "libatk-bridge2.0-0",
        "libcups2",
        "libdrm2",
        "libxkbcommon0",
        "libxcomposite1",
        "libxdamage1",
        "libxfixes3",
        "libxrandr2",
        "libgbm1",
        "libasound2",
        "libpango-1.0-0",
        "libcairo2",
    )
    .pip_install(
        "beautifulsoup4>=4.13",
        "composio>=0.9",
        "google-api-python-client>=2.170",
        "google-auth>=2.40",
        "gspread>=6.2",
        "openai>=1.90",
        "playwright>=1.52",
        "pydantic>=2.11",
    )
    .run_commands("playwright install chromium")
    .add_local_python_source("funnel_audit")
    .add_local_dir(
        str(WORKFLOW_DIR),
        remote_path="/root/workflow",
    )
)

secrets = [
    modal.Secret.from_name("funnel-audit-openai"),
    modal.Secret.from_name("funnel-audit-google"),
    modal.Secret.from_name("funnel-audit-config"),
    modal.Secret.from_name("funnel-audit-composio"),
    modal.Secret.from_name("pipeline-gap-downstream-secrets"),
]


def _run_downstream_pipeline(*extra_args: str) -> dict:
    process = subprocess.run(
        [
            sys.executable,
            "/root/workflow/run_pipeline_gap_system.py",
            "--continue-on-error",
            *extra_args,
        ],
        cwd="/root/workflow",
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
    successful_statuses = {"success", "attention_required"}
    parsed_status = parsed.get("status") if isinstance(parsed, dict) else None
    return {
        "returncode": process.returncode,
        "ok": process.returncode == 0 and parsed_status in successful_statuses,
        "healthy": parsed_status == "success",
        "stdout": parsed,
        "stderr": process.stderr.strip(),
    }


def _run_pipeline_monitor() -> dict:
    process = subprocess.run(
        [sys.executable, "/root/workflow/monitor_pipeline_gap_system.py"],
        cwd="/root/workflow",
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        result = json.loads(process.stdout) if process.stdout.strip() else None
    except json.JSONDecodeError:
        result = process.stdout.strip()
    return {
        "ok": process.returncode == 0,
        "returncode": process.returncode,
        "result": result,
        "stderr": process.stderr.strip(),
    }


def _write_dispatch_status(payload: dict) -> None:
    temporary = DISPATCH_STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, DISPATCH_STATUS_PATH)


def _read_dispatch_status() -> dict:
    if not DISPATCH_STATUS_PATH.exists():
        return {}
    try:
        return json.loads(DISPATCH_STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _send_scheduler_alert(text: str) -> dict:
    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        return {"status": "not_configured"}
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"text": text}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "funnel-audit-system/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
        return {"status": "sent"}
    except Exception as error:
        return {
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }


def _alert_fingerprint(
    status: str,
    upstream_failures: dict,
    upstream_warnings: dict,
    downstream: dict,
) -> str:
    if status == "success":
        return ""
    payload = {
        "status": status,
        "upstream_failures": sorted(upstream_failures),
        "upstream_warnings": {
            key: value for key, value in upstream_warnings.items() if value
        },
        "downstream_ok": bool(downstream.get("ok")),
        "downstream_healthy": bool(downstream.get("healthy")),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _scheduler_alert_text(
    status: str,
    started_at: str,
    upstream_failures: dict,
    upstream_warnings: dict,
    downstream: dict,
) -> str:
    lines = [
        f"Funnel audit scheduler: {status}",
        f"Started: {started_at}",
    ]
    if upstream_failures:
        lines.append("Failed stages: " + ", ".join(sorted(upstream_failures)))
    warnings = [
        f"{key}={value}" for key, value in upstream_warnings.items() if value
    ]
    if warnings:
        lines.append("Warnings: " + ", ".join(warnings))
    if not downstream.get("ok"):
        lines.append("Downstream pipeline failed.")
    elif not downstream.get("healthy"):
        lines.append("Downstream pipeline requires attention.")
    lines.append("Inspect Modal function scheduler_status for full details.")
    return "\n".join(lines)


@app.function(image=image, secrets=secrets, timeout=120)
def health_check() -> dict:
    from openai import OpenAI
    from openai import APIError

    from funnel_audit.config import SETTINGS
    from funnel_audit.composio_browser import configured as composio_configured
    from funnel_audit.google import gmail_service, sheet_service

    profile = gmail_service().users().getProfile(userId="me").execute()
    spreadsheet = (
        sheet_service()
        .spreadsheets()
        .get(
            spreadsheetId=SETTINGS.spreadsheet_id,
            fields="properties.title",
        )
        .execute()
    )
    try:
        response = OpenAI().responses.create(
            model=SETTINGS.openai_model,
            input="Reply with exactly OK.",
            max_output_tokens=16,
        )
        openai_status = response.output_text.strip() == "OK"
        openai_error = ""
    except APIError as error:
        openai_status = False
        openai_error = getattr(error, "code", None) or type(error).__name__
    return {
        "openai": openai_status,
        "openai_error": openai_error,
        "gmail": bool(profile.get("emailAddress")),
        "gmail_account": profile.get("emailAddress"),
        "sheets": spreadsheet.get("properties", {}).get("title")
        == "Pipeline Testing Signal",
        "composio": composio_configured(),
        "scheduler_alerts": bool(os.getenv("SLACK_WEBHOOK_URL", "").strip()),
        "live_submissions": SETTINGS.live_submissions,
    }


@app.function(image=image, secrets=secrets, timeout=420)
def composio_smoke_check() -> dict:
    from funnel_audit.composio_browser import create_and_wait

    return create_and_wait(
        task=(
            "Open the AI Essentials website. Click the Get the free report button. "
            "Verify that a Calendly booking widget or booking page opens and that "
            "available dates or times are visible. Do not select a time, enter any "
            "personal information, or submit/book anything. End with exactly "
            "'BOOKING_FLOW_REACHED: yes' if verified, otherwise "
            "'BOOKING_FLOW_REACHED: no' followed by the reason."
        ),
        start_url="https://aiessentials.us",
    )


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=120,
)
def active_audit_status() -> list[dict]:
    from funnel_audit.config import SETTINGS
    from funnel_audit.db import Database

    volume.reload()
    database = Database(SETTINGS.database_path)
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT audit_id, company_name, website_url, status, submitted_at,
                   monitor_until, last_checked_at, next_check_at,
                   cancellation_url, cancellation_due_at
            FROM audits
            WHERE status IN ('submitted', 'monitoring', 'opportunity_detected')
               OR cancellation_url<>''
               OR cancellation_due_at<>''
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=120,
)
def scheduler_status() -> dict:
    volume.reload()
    status = _read_dispatch_status()
    if not status:
        return {
            "status": "never_recorded",
            "volume_files": sorted(path.name for path in DISPATCH_STATUS_PATH.parent.iterdir()),
        }
    return status


@app.function(image=image, secrets=secrets, timeout=180)
def pipeline_status() -> dict:
    """Read-only downstream status without running enrichment or feeders."""
    return _run_pipeline_monitor()


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=120,
)
def set_booking_cancellation_url(audit_id: str, cancellation_url: str) -> dict:
    from funnel_audit.config import SETTINGS
    from funnel_audit.db import Database

    volume.reload()
    database = Database(SETTINGS.database_path)
    database.update_audit(audit_id, cancellation_url=cancellation_url)
    volume.commit()
    return database.get_audit(audit_id) or {}


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=120,
)
def reconcile_terminal_audit(audit_id: str) -> dict:
    from funnel_audit.config import SETTINGS
    from funnel_audit.db import Database
    from funnel_audit.orchestrator import reconcile_terminal_audit_sheet

    volume.reload()
    return reconcile_terminal_audit_sheet(Database(SETTINGS.database_path), audit_id)


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=120,
)
def resolve_historical_booking_attention(audit_id: str, resolution_note: str) -> dict:
    from funnel_audit.config import SETTINGS
    from funnel_audit.db import Database
    from funnel_audit.orchestrator import resolve_booking_attention

    volume.reload()
    database = Database(SETTINGS.database_path)
    result = resolve_booking_attention(database, audit_id, resolution_note)
    volume.commit()
    return result


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=900,
)
def discovery_cycle() -> dict:
    from funnel_audit.orchestrator import run_discovery_cycle

    volume.reload()
    result = run_discovery_cycle()
    volume.commit()
    return result


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=600,
)
def inbox_cycle() -> list[dict]:
    from funnel_audit.orchestrator import run_inbox_cycle

    volume.reload()
    result = run_inbox_cycle()
    volume.commit()
    return result


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=600,
)
def finalization_cycle() -> list[dict]:
    from funnel_audit.orchestrator import run_finalization_cycle

    volume.reload()
    result = run_finalization_cycle()
    volume.commit()
    return result


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    timeout=1800,
)
def downstream_cycle(dry_run: bool = False) -> dict:
    args = ["--dry-run", "--no-slack-alerts"] if dry_run else []
    return _run_downstream_pipeline(*args)


@app.function(
    image=image,
    secrets=secrets,
    volumes={"/data": volume},
    schedule=modal.Cron("0 */2 * * *"),
    timeout=1200,
)
def scheduled_dispatcher() -> dict:
    from funnel_audit.orchestrator import (
        run_discovery_cycle,
        run_finalization_cycle,
        run_inbox_cycle,
    )

    volume.reload()
    previous_status = _read_dispatch_status()
    started_at = datetime.now(timezone.utc).isoformat()
    from funnel_audit.config import SETTINGS
    from funnel_audit.db import Database

    database = Database(SETTINGS.database_path)
    owner = str(uuid.uuid4())
    lease_expires = datetime.now(timezone.utc).timestamp() + 1500
    lease_expires_at = datetime.fromtimestamp(lease_expires, timezone.utc).isoformat()
    if not database.acquire_lease("scheduled_dispatcher", owner, lease_expires_at):
        return {"status": "skipped_concurrent_run", "started_at": started_at}
    stale_run_notification = {}
    if previous_status.get("status") == "running":
        stale_run_notification = _send_scheduler_alert(
            "Funnel audit scheduler: previous run never recorded completion.\n"
            f"Previous start: {previous_status.get('started_at', 'unknown')}\n"
            "A new scheduled run is starting now."
        )
    _write_dispatch_status(
        {
            "status": "running",
            "started_at": started_at,
            "previous_alert_fingerprint": previous_status.get(
                "alert_fingerprint", ""
            ),
            "stale_run_notification": stale_run_notification,
        }
    )
    volume.commit()
    try:
        result = {
            "inbox": run_inbox_cycle(),
            "discovery": run_discovery_cycle(),
            "finalization": run_finalization_cycle(),
        }
        result["downstream"] = _run_downstream_pipeline()
        upstream_failures = {
            name: value
            for name, value in result.items()
            if name != "downstream"
            and isinstance(value, dict)
            and value.get("status") in {"configuration_required", "error", "failed"}
        }
        inbox_counts = (
            result.get("inbox", {}).get("attribution_counts", {})
            if isinstance(result.get("inbox"), dict)
            else {}
        )
        discovery_items = (
            result.get("discovery", {}).get("processed", [])
            if isinstance(result.get("discovery"), dict)
            else []
        )
        failed_cancellations = [
            item.get("audit_id", "unknown")
            for item in (
                result.get("finalization", {}).get("cancellations", [])
                if isinstance(result.get("finalization"), dict)
                else []
            )
            if not item.get("cancelled")
        ]
        with database.connect() as connection:
            missing_cancellation_rows = connection.execute(
                """
                SELECT audit_id FROM audits
                WHERE status IN ('submitted', 'monitoring')
                  AND cancellation_due_at<>''
                  AND cancellation_url=''
                ORDER BY audit_id
                """
            ).fetchall()
        upstream_warnings = {
            "unassigned_inbound_messages": int(inbox_counts.get("unassigned", 0) or 0),
            "failed_booking_cancellations": failed_cancellations,
            "bookings_missing_cancellation_url": [
                row["audit_id"] for row in missing_cancellation_rows
            ],
            "failed_audits": [
                item.get("audit_id", "unknown")
                for item in discovery_items
                if item.get("status") == "audit_failed"
            ],
            "manual_review_audits": [
                item.get("audit_id", "unknown")
                for item in discovery_items
                if item.get("status") == "manual_review"
            ],
            "downstream_attention": int(
                bool(result["downstream"].get("ok"))
                and not bool(result["downstream"].get("healthy"))
            ),
        }
        if not result["downstream"]["ok"] or upstream_failures:
            status = "partial_failure"
        elif any(upstream_warnings.values()):
            status = "attention_required"
        else:
            status = "success"
        alert_fingerprint = _alert_fingerprint(
            status, upstream_failures, upstream_warnings, result["downstream"]
        )
        previous_fingerprint = previous_status.get("alert_fingerprint", "")
        notification = {"status": "not_needed"}
        if alert_fingerprint and alert_fingerprint != previous_fingerprint:
            notification = _send_scheduler_alert(
                _scheduler_alert_text(
                    status,
                    started_at,
                    upstream_failures,
                    upstream_warnings,
                    result["downstream"],
                )
            )
        elif not alert_fingerprint and previous_fingerprint:
            notification = _send_scheduler_alert(
                "Funnel audit scheduler recovered.\n"
                f"Successful run started: {started_at}"
            )
        _write_dispatch_status(
            {
                "status": status,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
                "upstream_failures": upstream_failures,
                "upstream_warnings": upstream_warnings,
                "alert_fingerprint": alert_fingerprint,
                "notification": notification,
                "stale_run_notification": stale_run_notification,
            }
        )
        volume.commit()
        return result
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        error_fingerprint = json.dumps(
            {"status": "error", "error": error_text}, sort_keys=True
        )
        notification = {"status": "not_needed"}
        if error_fingerprint != previous_status.get("alert_fingerprint", ""):
            notification = _send_scheduler_alert(
                "Funnel audit scheduler crashed.\n"
                f"Started: {started_at}\n"
                f"Error: {error_text}"
            )
        _write_dispatch_status(
            {
                "status": "error",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": error_text,
                "alert_fingerprint": error_fingerprint,
                "notification": notification,
                "stale_run_notification": stale_run_notification,
            }
        )
        volume.commit()
        raise
    finally:
        database.release_lease("scheduled_dispatcher", owner)
        volume.commit()


@app.local_entrypoint()
def main() -> None:
    print({"health": health_check.remote(), "discovery": discovery_cycle.remote()})
