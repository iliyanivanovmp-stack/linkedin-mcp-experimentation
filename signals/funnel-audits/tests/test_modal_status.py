from __future__ import annotations

import modal_app


def test_success_has_no_alert_fingerprint():
    assert modal_app._alert_fingerprint("success", {}, {}, {"ok": True}) == ""


def test_warning_fingerprint_is_stable_and_excludes_zero_counts():
    first = modal_app._alert_fingerprint(
        "attention_required",
        {},
        {"failed_booking_cancellations": 1, "unassigned_inbound_messages": 0},
        {"ok": True, "healthy": True},
    )
    second = modal_app._alert_fingerprint(
        "attention_required",
        {},
        {"unassigned_inbound_messages": 0, "failed_booking_cancellations": 1},
        {"healthy": True, "ok": True},
    )
    assert first == second
    assert "failed_booking_cancellations" in first
    assert "unassigned_inbound_messages" not in first


def test_scheduler_alert_text_identifies_actionable_stage():
    text = modal_app._scheduler_alert_text(
        "partial_failure",
        "2026-07-27T12:00:00+00:00",
        {"discovery": {"status": "failed"}},
        {"failed_booking_cancellations": 1},
        {"ok": False, "healthy": False},
    )
    assert "discovery" in text
    assert "failed_booking_cancellations=1" in text
    assert "Downstream pipeline failed" in text


def test_scheduler_alert_fails_closed_when_webhook_is_missing(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert modal_app._send_scheduler_alert("test") == {
        "status": "not_configured"
    }
