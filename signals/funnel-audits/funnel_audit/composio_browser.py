from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from composio import Composio

from .config import SETTINGS
from .models import FunnelCandidate, SubmissionDecision


CREATE_TASK = "BROWSER_TOOL_CREATE_TASK"
WATCH_TASK = "BROWSER_TOOL_WATCH_TASK"
GET_SESSION = "BROWSER_TOOL_GET_SESSION"
BROWSER_TOOL_VERSION = "20260618_00"


def configured() -> bool:
    value = os.getenv("COMPOSIO_API_KEY", "")
    return bool(value and value != "CONFIGURE_ME")


def _client() -> Composio:
    if not configured():
        raise RuntimeError("COMPOSIO_API_KEY is not configured")
    return Composio(
        api_key=os.environ["COMPOSIO_API_KEY"],
        toolkit_versions={"browser_tool": BROWSER_TOOL_VERSION},
    )


def _plain(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return json.loads(json.dumps(value, default=lambda item: item.__dict__))


def _data(value: Any) -> dict[str, Any]:
    payload = _plain(value)
    for key in ("data", "response"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            payload = nested
    nested = payload.get("data")
    return nested if isinstance(nested, dict) else payload


def _execute(slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = _client().tools.execute(
        slug,
        user_id=SETTINGS.composio_user_id,
        arguments=arguments,
    )
    return _data(result)


def wait_for_task(task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + SETTINGS.browser_task_timeout_seconds
    last_step = 0
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _execute(
            WATCH_TASK,
            {"taskId": task_id, "lastStepSeen": last_step},
        )
        last_step = int(latest.get("current_step") or last_step)
        status = str(latest.get("status", "")).casefold()
        if status in {"finished", "failed", "stopped"}:
            return latest
        time.sleep(5)
    return {
        **latest,
        "status": "timed_out",
        "isSuccess": False,
        "output": "Browser task exceeded the configured timeout.",
    }


def create_and_wait(
    task: str,
    start_url: str,
    session_id: str = "",
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"task": task, "startUrl": start_url}
    if session_id:
        arguments["sessionId"] = session_id
    created = _execute(CREATE_TASK, arguments)
    task_id = str(created.get("watch_task_id") or created.get("taskId") or "")
    browser_session_id = str(
        created.get("browser_session_id") or created.get("sessionId") or ""
    )
    if not task_id:
        return {
            "submitted": False,
            "reason": "Composio did not return a browser task ID.",
            "raw": created,
        }
    watched = wait_for_task(task_id)
    live_url = ""
    if browser_session_id:
        session = _execute(GET_SESSION, {"sessionId": browser_session_id})
        live_url = str(session.get("liveUrl") or "")
    return {
        "task_id": task_id,
        "browser_session_id": browser_session_id,
        "live_url": live_url,
        "status": watched.get("status", ""),
        "is_success": bool(
            watched.get("isSuccess")
            if "isSuccess" in watched
            else watched.get("is_success")
        ),
        "output": str(watched.get("output") or ""),
        "current_url": str(watched.get("current_url") or ""),
        "raw": watched,
    }


def _decision_values(decision: SubmissionDecision) -> dict[str, str]:
    return {item.field.casefold(): item.value for item in decision.field_values}


def submit_booking(
    candidate: FunnelCandidate,
    decision: SubmissionDecision,
) -> dict[str, Any]:
    values = _decision_values(decision)
    earliest = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
    task = f"""
Open this public booking flow and create exactly one booking.

Rules:
- Select the earliest available date on or after {earliest}.
- Select the first available time on that date.
- Name: {values.get("name", "")}
- Email: {values.get("email", "")}
- Title: {values.get("title", "")}
- Company: {values.get("company", "")}
- Phone: {values.get("phone", "")}
- Leave optional questions blank.
- Do not add guests.
- Click the final Schedule/Book/Confirm action exactly once.
- Never retry the final submission after an error.
- Success is valid only if the final page explicitly says the invitee is
  scheduled/confirmed and provides a unique confirmation or invitee URL.

At the end, report:
BOOKING_CONFIRMED: yes or no
CONFIRMATION_URL: the final unique invitee/confirmation URL, or blank
SCHEDULED_TIME_ISO: the scheduled instant as ISO 8601 with UTC offset, or blank
FINAL_MESSAGE: the exact confirmation or error message
"""
    result = create_and_wait(task, candidate.page_url)
    output = result.get("output", "")
    confirmed = bool(
        re.search(r"BOOKING_CONFIRMED:\s*yes", output, re.I)
        and re.search(r"you are scheduled|confirmed", output, re.I)
    )
    url_match = re.search(r"CONFIRMATION_URL:\s*(https?://\S+)", output, re.I)
    time_match = re.search(r"SCHEDULED_TIME_ISO:\s*(.+)", output, re.I)
    return {
        "submitted": confirmed,
        "booking_created": confirmed,
        "provider": "composio_browser",
        "confirmation_url": (
            url_match.group(1).rstrip(".,)") if url_match else result.get("current_url", "")
        ),
        "scheduled_time": time_match.group(1).strip() if time_match else "",
        "confirmation_text": output,
        "browser_session_id": result.get("browser_session_id", ""),
        "browser_task_id": result.get("task_id", ""),
        "live_url": result.get("live_url", ""),
        "reason": (
            "" if confirmed
            else output or "Composio did not return authoritative booking confirmation."
        ),
    }


def cancel_booking(cancellation_url: str) -> dict[str, Any]:
    task = """
Open this cancellation page and cancel the existing meeting exactly once.
Do not reschedule it. Confirm cancellation only when required. Success is valid
only if the final page explicitly states that the event was cancelled.

At the end, report:
CANCELLATION_CONFIRMED: yes or no
FINAL_MESSAGE: the exact confirmation or error message
"""
    result = create_and_wait(task, cancellation_url)
    output = result.get("output", "")
    cancelled = bool(
        re.search(r"CANCELLATION_CONFIRMED:\s*yes", output, re.I)
        and re.search(r"cancelled|canceled", output, re.I)
    )
    return {
        "cancelled": cancelled,
        "provider": "composio_browser",
        "confirmation_text": output,
        "browser_session_id": result.get("browser_session_id", ""),
        "browser_task_id": result.get("task_id", ""),
        "live_url": result.get("live_url", ""),
        "reason": "" if cancelled else output or "Cancellation was not confirmed.",
    }
