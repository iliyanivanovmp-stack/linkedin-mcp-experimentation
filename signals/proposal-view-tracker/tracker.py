from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_MIN_REOPEN_SECONDS = 300
DEFAULT_NOTIFICATION_COOLDOWN_SECONDS = 3600


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "proposal"


def slides_url(presentation_id: str) -> str:
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit?usp=sharing"


def build_tracking_url(
    *,
    base_url: str,
    presentation_id: str,
    company: str,
    prospect: str = "",
    email: str = "",
) -> str:
    params = {
        "proposal_id": presentation_id,
        "company": company,
        "prospect": prospect,
        "email": email,
        "utm_source": "proposal",
        "utm_medium": "google_slides",
        "utm_campaign": "proposal_reopen",
        "utm_content": slugify(company),
    }
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    return f"{base_url.rstrip('/')}?{query}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def update_view_state(
    state: dict[str, Any] | None,
    *,
    viewed_at: str,
    min_reopen_seconds: int = DEFAULT_MIN_REOPEN_SECONDS,
    notification_cooldown_seconds: int = DEFAULT_NOTIFICATION_COOLDOWN_SECONDS,
) -> tuple[dict[str, Any], bool]:
    current = dict(state or {})
    first_viewed_at = str(current.get("first_viewed_at") or viewed_at)
    last_viewed_at = str(current.get("last_viewed_at") or viewed_at)
    last_notified_at = str(current.get("last_notified_at") or "")
    view_count = int(current.get("view_count") or 0) + 1

    should_notify = False
    if view_count > 1:
        viewed_ts = datetime.fromisoformat(viewed_at).timestamp()
        first_ts = datetime.fromisoformat(first_viewed_at).timestamp()
        last_notified_ts = datetime.fromisoformat(last_notified_at).timestamp() if last_notified_at else 0
        past_reopen_floor = viewed_ts - first_ts >= min_reopen_seconds
        past_notification_cooldown = not last_notified_at or viewed_ts - last_notified_ts >= notification_cooldown_seconds
        should_notify = past_reopen_floor and past_notification_cooldown

    updated = {
        **current,
        "first_viewed_at": first_viewed_at,
        "last_viewed_at": viewed_at,
        "previous_viewed_at": last_viewed_at,
        "view_count": view_count,
    }
    if should_notify:
        updated["last_notified_at"] = viewed_at
    return updated, should_notify


def slack_message(
    *,
    company: str,
    prospect: str,
    email: str,
    presentation_id: str,
    state: dict[str, Any],
) -> str:
    title = ":eyes: *Proposal reopened*"
    prospect_label = prospect or "Unknown prospect"
    company_label = company or "Unknown company"
    lines = [
        title,
        f"Prospect: {prospect_label}",
        f"Company: {company_label}",
    ]
    if email:
        lines.append(f"Email: {email}")
    lines.extend(
        [
            f"Views: {state.get('view_count', 0)}",
            f"First viewed: {format_time(str(state.get('first_viewed_at', 'unknown')))}",
            f"Previous view: {format_time(str(state.get('previous_viewed_at', 'unknown')))}",
            f"<{slides_url(presentation_id)}|Open proposal>",
            "Suggested follow-up: Wanted to check in while the proposal is fresh. Was there anything in there you wanted me to clarify?",
        ]
    )
    return "\n".join(lines)


def post_slack_message(token: str, channel: str, text: str) -> str:
    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "text": text}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "proposal-view-tracker/1.0",
        },
    )
    response = urllib.request.urlopen(request, timeout=15)
    try:
        body = json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
    if not body.get("ok"):
        raise RuntimeError(f"Slack API error: {body.get('error', 'unknown_error')}")
    return str(body.get("ts", "ok"))


def slack_configured() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN", "").strip() and os.environ.get("SLACK_CHANNEL_ID", "").strip())
