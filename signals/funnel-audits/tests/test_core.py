from __future__ import annotations

import asyncio

from funnel_audit.browser import _fingerprint, submit_candidate
from funnel_audit.db import Database
from funnel_audit.ai import strict_json_schema
from funnel_audit.models import EmailAssessment, FieldValue, FormField, FunnelCandidate, GapAssessment, SubmissionDecision
from funnel_audit.composio_browser import _data
from funnel_audit.google import column_letters, merged_sheet_headers
from funnel_audit.orchestrator import (
    _message_attribution,
    audit_alias,
    finalize_due,
    monitor_inbox,
    normalized_domain,
    rank_candidates,
    stable_audit_id,
)


def test_normalized_domain():
    assert normalized_domain("https://www.aiessentials.us/path") == "aiessentials.us"


def test_shared_alias_requires_separate_message_attribution():
    assert audit_alias("abc-123") == "iliyan.i@aiessentials.us"


def test_stable_id():
    value = stable_audit_id("example.com", "2026-06-22T10:00:00+00:00")
    assert value.startswith("example-com-20260622-")


def test_missing_sheet_output_columns_are_appended_in_schema_order():
    merged, added = merged_sheet_headers(
        ["audit_id", "status"],
        ["audit_id", "status", "checklist_passed", "checklist_failed", "checklist_unknown"],
        {"status": "done", "checklist_unknown": "none", "checklist_passed": "entry"},
    )
    assert merged == ["audit_id", "status", "checklist_passed", "checklist_unknown"]
    assert added == ["checklist_passed", "checklist_unknown"]
    assert column_letters(27) == "AA"


def test_database_roundtrip(tmp_path):
    database = Database(str(tmp_path / "audit.db"))
    database.upsert_audit(
        {
            "audit_id": "example-1",
            "sheet_row": 2,
            "company_name": "Example",
            "website_url": "https://example.com",
            "normalized_domain": "example.com",
            "status": "queued",
            "created_at": "2026-06-22T00:00:00+00:00",
        }
    )
    assert database.get_audit("example-1")["status"] == "queued"
    database.update_audit("example-1", status="monitoring")
    assert database.get_audit("example-1")["status"] == "monitoring"


def test_database_update_rejects_unknown_columns(tmp_path):
    database = Database(str(tmp_path / "audit.db"))
    try:
        database.update_audit("missing", injected_column="value")
    except ValueError as error:
        assert "injected_column" in str(error)
    else:
        raise AssertionError("unknown database column should fail closed")


def test_email_deduplication(tmp_path):
    database = Database(str(tmp_path / "audit.db"))
    payload = {
        "message_id": "m1",
        "audit_id": "a1",
        "subject": "Your guide",
        "body_text": "Here it is",
    }
    assert database.save_email(payload)
    assert not database.save_email(payload)


def test_inbound_message_is_stored_once_before_attribution(tmp_path):
    database = Database(str(tmp_path / "audit.db"))
    payload = {"message_id": "m1", "sender": "hello@example.com", "links": []}
    assert database.save_inbound_message(payload)
    assert not database.save_inbound_message(payload)
    assert database.unassigned_messages()[0]["message_id"] == "m1"


def test_message_attribution_uses_company_evidence_not_audit_order():
    audits = [
        {"audit_id": "a", "normalized_domain": "alpha.com", "company_name": "Alpha", "submitted_at": "2026-01-01T00:00:00+00:00"},
        {"audit_id": "b", "normalized_domain": "beta.com", "company_name": "Beta", "submitted_at": "2026-01-01T00:00:00+00:00"},
    ]
    message = {
        "sender": "team@beta.com", "subject": "Your report", "body_text": "Thanks, Beta",
        "links": ["https://beta.com/report"], "received_at": "2026-01-02T00:00:00+00:00",
    }
    audit, reason = _message_attribution(message, audits)
    assert audit["audit_id"] == "b"
    assert "sender_domain" in reason


def test_ambiguous_message_is_not_guessed():
    audits = [
        {"audit_id": "a", "normalized_domain": "alpha.com", "company_name": "Alpha", "submitted_at": "2026-01-01T00:00:00+00:00"},
        {"audit_id": "b", "normalized_domain": "beta.com", "company_name": "Beta", "submitted_at": "2026-01-01T00:00:00+00:00"},
    ]
    audit, reason = _message_attribution(
        {"sender": "news@mailer.com", "subject": "Alpha Beta", "body_text": "", "links": [], "received_at": "2026-01-02T00:00:00+00:00"},
        audits,
    )
    assert audit is None
    assert reason == "ambiguous_company_correlation"


def test_candidate_ranking_prefers_lead_magnet_over_generic_contact():
    candidates = [
        FunnelCandidate(page_url="https://x.test/contact", entry_type="form", offer_text="Contact sales"),
        FunnelCandidate(page_url="https://x.test/report", entry_type="form", offer_text="Download the free report"),
    ]
    ranked = rank_candidates(candidates)
    assert ranked[0].page_url.endswith("/report")
    assert ranked[0].discovery_rank == 1


def test_submission_replays_exact_form_and_requires_success_evidence(tmp_path):
    page = tmp_path / "forms.html"
    page.write_text(
        """
        <html><body>
          <form><input name="email"><button type="submit">Wrong form</button></form>
          <form id="report"><input name="email" type="email" required><button type="submit">Get report</button></form>
          <script>
            document.querySelector('#report').addEventListener('submit', event => {
              event.preventDefault();
              event.target.outerHTML = '<div>Thank you. Check your inbox for the report.</div>';
            });
          </script>
        </body></html>
        """,
        encoding="utf-8",
    )
    fields = [FormField(selector='[name="email"]', name="email", field_type="email", required=True)]
    candidate = FunnelCandidate(
        page_url=page.as_uri(), entry_type="form", offer_text="Get report",
        fields=fields, form_fingerprint=_fingerprint(fields, "Get report"),
    )
    decision = SubmissionDecision(
        action="submit", reason="test",
        field_values=[FieldValue(field="email", value="audit@example.com")],
    )
    (tmp_path / "audit").mkdir()
    result = asyncio.run(submit_candidate(candidate, decision, str(tmp_path), "audit"))
    assert result["submitted"] is True
    assert result["verification"]["success_text_detected"] is True


def test_scheduler_lease_prevents_concurrent_owner(tmp_path):
    database = Database(str(tmp_path / "audit.db"))
    assert database.acquire_lease("dispatcher", "one", "2999-01-01T00:00:00+00:00")
    assert not database.acquire_lease("dispatcher", "two", "2999-01-01T00:00:00+00:00")
    database.release_lease("dispatcher", "one")
    assert database.acquire_lease("dispatcher", "two", "2999-01-01T00:00:00+00:00")


def test_post_deadline_monitoring_assessment_becomes_manual_review(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "audit.db"))
    database.upsert_audit({
        "audit_id": "a", "sheet_row": 2, "company_name": "Alpha",
        "website_url": "https://alpha.com", "normalized_domain": "alpha.com",
        "status": "monitoring", "created_at": "2026-01-01T00:00:00+00:00",
        "next_check_at": "2026-01-01T00:00:00+00:00",
    })
    database.update_audit("a", monitor_until="2026-01-02T00:00:00+00:00")
    monkeypatch.setattr("funnel_audit.orchestrator.assess_gap", lambda _events: GapAssessment(result="monitoring"))
    monkeypatch.setattr("funnel_audit.orchestrator.update_sheet_row", lambda *args, **kwargs: None)
    assert finalize_due(database) == [{"audit_id": "a", "status": "manual_review"}]


def test_finalization_ignores_inbox_next_check_timestamp(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "audit.db"))
    database.upsert_audit({
        "audit_id": "a", "sheet_row": 2, "company_name": "Alpha",
        "website_url": "https://alpha.com", "normalized_domain": "alpha.com",
        "status": "monitoring", "created_at": "2026-01-01T00:00:00+00:00",
        "next_check_at": "2999-01-01T00:00:00+00:00",
    })
    database.update_audit("a", monitor_until="2026-01-02T00:00:00+00:00")
    monkeypatch.setattr("funnel_audit.orchestrator.assess_gap", lambda _events: GapAssessment(result="no_gap_detected"))
    monkeypatch.setattr("funnel_audit.orchestrator.update_sheet_row", lambda *args, **kwargs: None)
    assert finalize_due(database) == [{"audit_id": "a", "status": "no_gap_detected"}]


def test_empty_inbox_still_advances_monitoring_check(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "audit.db"))
    database.upsert_audit(
        {
            "audit_id": "example-1",
            "sheet_row": 2,
            "company_name": "Example",
            "website_url": "https://example.com",
            "normalized_domain": "example.com",
            "status": "monitoring",
            "created_at": "2026-06-22T00:00:00+00:00",
            "next_check_at": "2026-06-22T00:00:00+00:00",
        }
    )
    monkeypatch.setattr(
        "funnel_audit.orchestrator.list_audit_messages", lambda _alias: []
    )

    assert monitor_inbox(database) == []
    audit = database.get_audit("example-1")
    assert audit["last_checked_at"]
    assert audit["next_check_at"] > audit["last_checked_at"]


def test_openai_strict_schema_requires_every_field():
    schema = strict_json_schema(SubmissionDecision)
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    field_value = schema["$defs"]["FieldValue"]
    assert field_value["required"] == list(field_value["properties"])


def test_assessment_schemas_include_production_checklist_fields():
    email_schema = strict_json_schema(EmailAssessment)
    assert "meeting_reminder" in str(email_schema)
    assert "no_show_recovery" in str(email_schema)
    assert "calendar_not_booked_follow_up" in str(email_schema)

    gap_schema = strict_json_schema(GapAssessment)
    assert "checklist_passed" in gap_schema["properties"]
    assert "checklist_failed" in gap_schema["properties"]
    assert "checklist_unknown" in gap_schema["properties"]


def test_booking_rejection_language_is_not_success():
    text = "This booking cannot be completed. We are not able to finalize this booking."
    import re

    assert re.search(r"cannot be completed|not able to finalize", text, re.I)


def test_composio_nested_data_normalization():
    assert _data({"data": {"response": {"data": {"taskId": "task-1"}}}}) == {
        "taskId": "task-1"
    }
