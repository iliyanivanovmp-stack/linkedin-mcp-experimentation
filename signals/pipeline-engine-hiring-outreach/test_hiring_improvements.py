from datetime import datetime, timedelta, timezone

import asyncio
import json
from pathlib import Path

from collect_hiring_signals import classify_job, compensation_details, guest_search_jobs
from extract_contacts import (
    MemorySheet,
    decision_maker_titles_for_company,
    matches_decision_maker_title,
)
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


def production_sourcing_config():
    return json.loads((Path(__file__).parent / "sourcing_config.json").read_text())


def test_production_searches_use_plain_role_terms_and_recency_filter():
    config = production_sourcing_config()

    assert config["date_posted"] == "past_24_hours"
    assert config["sort_by"] == "date"
    assert config["max_pages"] == 1
    assert all(" OR " not in query for query in config["search_queries"])
    assert all("remote" not in query.casefold() for query in config["search_queries"])
    assert all("24" not in query for query in config["search_queries"])


def test_hiring_guest_search_maps_structured_filters(monkeypatch):
    captured_urls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'<a href="/jobs/view/1234567890/">Job</a>'

    def fake_urlopen(request, timeout):
        captured_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr("collect_hiring_signals.urlopen", fake_urlopen)

    result = asyncio.run(guest_search_jobs(
        "sales development representative",
        "United States",
        1,
        "past_24_hours",
        "full_time,contract",
        "entry,associate",
        "remote",
        True,
        "date",
    ))

    assert result["job_ids"] == ["1234567890"]
    url = captured_urls[0]
    assert "keywords=sales+development+representative" in url
    assert "f_TPR=r86400" in url
    assert "f_JT=F%2CC" in url
    assert "f_E=2%2C3" in url
    assert "f_WT=2" in url
    assert "f_EA=true" in url
    assert "sortBy=DD" in url


def test_growth_role_requires_pipeline_evidence():
    assert classify_job("Acme\nGrowth Manager\nOwn partnerships and events", sourcing_config()) is None
    assert classify_job("Acme\nGrowth Manager\nOwn outbound prospecting and CRM", sourcing_config())


def test_compensation_ignores_pipeline_kpis():
    details = compensation_details(
        "$150K–$250K in sourced pipeline per month\n"
        "Salary Range: $90,000 USD - $100,000 USD"
    )

    assert details["compensation_min"] == 90_000
    assert details["compensation_max"] == 100_000
    assert details["compensation_period"] == "year"
    assert "sourced pipeline" not in details["compensation_text"]


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


def test_irrelevant_titles_do_not_match_outbound_decision_makers():
    titles = [
        "founder", "co-founder", "ceo", "chief revenue officer", "cro",
        "vp sales", "head of sales", "sales director",
    ]
    assert not matches_decision_maker_title("Senior Product Designer", titles)
    assert not matches_decision_maker_title("Technical Product Owner", titles)
    assert not matches_decision_maker_title("Founder's Associate Intern", titles)
    assert not matches_decision_maker_title("Founder's Associate", titles)
    assert matches_decision_maker_title("Vice President of Sales", titles)


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


def test_domain_recovery_dry_run_does_not_change_schema_or_rows():
    sheet = MemorySheet(
        ["status", "company_name", "company_website", "company_domain"],
        [{"status": "needs_company_domain", "company_name": "Acme", "company_website": "https://www.acme.com", "company_domain": ""}],
    )
    original_headers = list(sheet.headers)
    original_row = dict(sheet.rows()[0].data)

    result = recover_domains(sheet, client=None, dry_run=True, limit=None)

    assert result["recovered_from_website"] == 1
    assert sheet.headers == original_headers
    assert sheet.rows()[0].data == original_row
