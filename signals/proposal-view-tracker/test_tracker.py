from __future__ import annotations

from tracker import build_tracking_url, slack_message, update_view_state


def test_first_view_is_silent() -> None:
    state, should_notify = update_view_state(
        None,
        viewed_at="2026-08-06T10:00:00+00:00",
    )

    assert should_notify is False
    assert state["view_count"] == 1
    assert state["first_viewed_at"] == "2026-08-06T10:00:00+00:00"


def test_reopen_after_floor_notifies() -> None:
    state, _ = update_view_state(
        None,
        viewed_at="2026-08-06T10:00:00+00:00",
        min_reopen_seconds=300,
    )
    state, should_notify = update_view_state(
        state,
        viewed_at="2026-08-06T10:07:00+00:00",
        min_reopen_seconds=300,
    )

    assert should_notify is True
    assert state["view_count"] == 2
    assert state["last_notified_at"] == "2026-08-06T10:07:00+00:00"


def test_notification_cooldown_blocks_refresh_spam() -> None:
    state, _ = update_view_state(
        None,
        viewed_at="2026-08-06T10:00:00+00:00",
        min_reopen_seconds=0,
    )
    state, should_notify = update_view_state(
        state,
        viewed_at="2026-08-06T10:10:00+00:00",
        min_reopen_seconds=0,
        notification_cooldown_seconds=3600,
    )
    assert should_notify is True

    state, should_notify = update_view_state(
        state,
        viewed_at="2026-08-06T10:11:00+00:00",
        min_reopen_seconds=0,
        notification_cooldown_seconds=3600,
    )

    assert should_notify is False
    assert state["view_count"] == 3


def test_build_tracking_url_adds_utm_fields() -> None:
    url = build_tracking_url(
        base_url="https://example.test/track",
        presentation_id="abc123456789",
        company="Acme Inc.",
        prospect="Jane Doe",
        email="jane@example.test",
    )

    assert "proposal_id=abc123456789" in url
    assert "utm_source=proposal" in url
    assert "utm_medium=google_slides" in url
    assert "utm_campaign=proposal_reopen" in url
    assert "utm_content=acme-inc" in url


def test_slack_message_has_follow_up_prompt() -> None:
    text = slack_message(
        company="Acme",
        prospect="Jane Doe",
        email="jane@example.test",
        presentation_id="abc123456789",
        state={
            "view_count": 2,
            "first_viewed_at": "2026-08-06T10:00:00+00:00",
            "previous_viewed_at": "2026-08-06T10:30:00+00:00",
        },
    )

    assert "Proposal reopened" in text
    assert "Wanted to check in while the proposal is fresh" in text
    assert "https://docs.google.com/presentation/d/abc123456789/edit?usp=sharing" in text
