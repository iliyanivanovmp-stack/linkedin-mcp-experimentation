from datetime import datetime, timedelta, timezone

from collect_hiring_signals import classify_job
from extract_contacts import MemorySheet, decision_maker_titles_for_company
from feed_lemlist import retry_due
from recover_company_domains import recover_domains


def sourcing_config():
    return {
        "role_families": {
            "direct_outbound": {"score": 100, "title_terms": ["sales development representative"], "offer_angle": "outbound"},
            "growth_demand": {"score": 65, "title_terms": ["growth manager"], "offer_angle": "growth", "require_evidence": True},
        },
        "exclude_title_terms": ["intern"],
        "exclude_company_terms": ["staffing"],
        "exclude_description_terms": ["commission only"],
        "evidence_terms": ["outbound", "crm"],
    }


def test_growth_role_requires_pipeline_evidence():
    assert classify_job("Acme\nGrowth Manager\nOwn partnerships and events", sourcing_config()) is None
    assert classify_job("Acme\nGrowth Manager\nOwn outbound prospecting and CRM", sourcing_config())


def test_staffing_company_and_commission_only_role_are_rejected():
    config = sourcing_config()
    assert classify_job("Acme Staffing\nSales Development Representative\nOutbound", config) is None
    assert classify_job("Acme\nSales Development Representative\nCommission only outbound", config) is None


def test_role_family_selects_relevant_decision_makers():
    config = {
        "decision_maker_titles": ["founder"],
        "decision_maker_titles_by_role_family": {"growth_demand": ["head of growth", "cmo"]},
    }
    assert decision_maker_titles_for_company({"hiring_role_family": "growth_demand"}, config) == ["head of growth", "cmo"]
    assert decision_maker_titles_for_company({"hiring_role_family": "unknown"}, config) == ["founder"]


def test_delivery_retry_is_bounded_and_time_aware():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert not retry_due({"status": "delivery_failed", "delivery_attempts": "1", "delivery_next_retry_at": future}, 4)
    assert retry_due({"status": "delivery_failed", "delivery_attempts": "1", "delivery_next_retry_at": ""}, 4)
    assert not retry_due({"status": "delivery_failed", "delivery_attempts": "4", "delivery_next_retry_at": ""}, 4)


def test_domain_recovery_derives_domain_from_known_website():
    sheet = MemorySheet(
        ["status", "company_name", "company_website", "company_domain"],
        [{"status": "needs_company_domain", "company_name": "Acme", "company_website": "https://www.acme.com/about", "company_domain": ""}],
    )
    result = recover_domains(sheet, client=None, dry_run=False, limit=None)
    assert result["recovered_from_website"] == 1
    assert sheet.rows()[0].data["company_domain"] == "acme.com"
    assert sheet.rows()[0].data["status"] == "opportunity_detected"
