from __future__ import annotations

import os
from typing import Any

import modal

from tracker import (
    DEFAULT_MIN_REOPEN_SECONDS,
    DEFAULT_NOTIFICATION_COOLDOWN_SECONDS,
    now_iso,
    post_slack_message,
    slack_configured,
    slack_message,
    slides_url,
    update_view_state,
)


app = modal.App("proposal-view-tracker")
TRACKER_DIR = "/root/proposal-view-tracker"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi==0.115.14")
    .env({"PYTHONPATH": TRACKER_DIR})
    .add_local_dir(
        os.path.dirname(__file__),
        remote_path=TRACKER_DIR,
    )
)

state_store = modal.Dict.from_name("proposal-view-tracker-state", create_if_missing=True)
secrets = [modal.Secret.from_name("proposal-view-tracker-slack")]


def _state_key(proposal_id: str) -> str:
    return f"proposal:{proposal_id}"


def _record_view(
    *,
    proposal_id: str,
    company: str,
    prospect: str,
    email: str,
    viewed_at: str | None = None,
    min_reopen_seconds: int = DEFAULT_MIN_REOPEN_SECONDS,
    notification_cooldown_seconds: int = DEFAULT_NOTIFICATION_COOLDOWN_SECONDS,
) -> dict[str, Any]:
    key = _state_key(proposal_id)
    current = state_store.get(key) or {}
    next_state, should_notify = update_view_state(
        current,
        viewed_at=viewed_at or now_iso(),
        min_reopen_seconds=min_reopen_seconds,
        notification_cooldown_seconds=notification_cooldown_seconds,
    )
    next_state.update(
        {
            "proposal_id": proposal_id,
            "company": company,
            "prospect": prospect,
            "email": email,
        }
    )
    state_store.put(key, next_state)

    notification: dict[str, Any] = {"sent": False, "reason": "first_view_or_cooldown"}
    if should_notify and slack_configured():
        ts = post_slack_message(
            os.environ["SLACK_BOT_TOKEN"].strip(),
            os.environ["SLACK_CHANNEL_ID"].strip(),
            slack_message(
                company=company,
                prospect=prospect,
                email=email,
                presentation_id=proposal_id,
                state=next_state,
            ),
        )
        notification = {"sent": True, "ts": ts}
        next_state["last_slack_ts"] = ts
        state_store.put(key, next_state)
    elif should_notify:
        notification = {"sent": False, "reason": "slack_not_configured"}

    return {"state": next_state, "notification": notification}


@app.function(
    image=image,
    secrets=secrets,
    timeout=60,
    max_containers=1,
)
@modal.fastapi_endpoint(method="GET")
def track(
    proposal_id: str,
    company: str = "",
    prospect: str = "",
    email: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
):
    from fastapi.responses import RedirectResponse

    if len(proposal_id.strip()) < 10:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="proposal_id is required")
    _record_view(
        proposal_id=proposal_id.strip(),
        company=company.strip(),
        prospect=prospect.strip(),
        email=email.strip(),
    )
    return RedirectResponse(slides_url(proposal_id.strip()), status_code=302)


@app.function(image=image, secrets=secrets, timeout=60, max_containers=1)
def send_smoke_test_notification() -> dict[str, Any]:
    if not slack_configured():
        return {"ok": False, "error": "slack_not_configured"}
    ts = post_slack_message(
        os.environ["SLACK_BOT_TOKEN"].strip(),
        os.environ["SLACK_CHANNEL_ID"].strip(),
        ":test_tube: *Proposal view tracker smoke test*\nSlack delivery is configured. No client email automation is enabled.",
    )
    return {"ok": True, "ts": ts}


@app.local_entrypoint()
def main(smoke_test: bool = False) -> None:
    if smoke_test:
        print(send_smoke_test_notification.remote())
