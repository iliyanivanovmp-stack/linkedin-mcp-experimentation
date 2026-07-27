from prepare_context import build_context, prepare_context
from extract_contacts import MemorySheet


def test_build_context_uses_verified_job_signal():
    result = build_context({
        "company_name": "Acme",
        "job_title": "Sales Development Representative",
        "job_url": "https://linkedin.com/jobs/view/123",
        "offer_angle": "Build the outbound infrastructure around the role.",
    })
    assert result["hiring_opener"] == "Noticed Acme is hiring a Sales Development Representative."
    assert "targeting" in result["hiring_automation_opportunity"]
    assert result["source_url"].endswith("/123")


def test_prepare_context_qualifies_one_row_and_rejects_missing_domain():
    sheet = MemorySheet([
        "status", "company_name", "company_domain", "job_title", "job_url", "offer_angle"
    ], [
        {"status": "opportunity_detected", "company_name": "Acme", "company_domain": "acme.com", "job_title": "SDR", "job_url": "https://linkedin.com/jobs/view/1"},
        {"status": "opportunity_detected", "company_name": "No Domain", "company_domain": "", "job_title": "BDR", "job_url": "https://linkedin.com/jobs/view/2"},
    ])
    result = prepare_context(sheet, dry_run=False)
    assert result["updated"] == 1
    assert result["missing_domain"] == 1
    rows = sheet.rows()
    assert rows[0].data["status"] == "outreach_ready"
    assert rows[1].data["status"] == "needs_company_domain"


def test_prepare_context_dry_run_does_not_change_schema_or_rows():
    sheet = MemorySheet(
        ["status", "company_name", "company_domain", "job_title", "job_url"],
        [{
            "status": "opportunity_detected",
            "company_name": "Acme",
            "company_domain": "acme.com",
            "job_title": "SDR",
            "job_url": "https://linkedin.com/jobs/view/1",
        }],
    )
    original_headers = list(sheet.headers)
    original_row = dict(sheet.rows()[0].data)

    result = prepare_context(sheet, dry_run=True)

    assert result["updated"] == 1
    assert sheet.headers == original_headers
    assert sheet.rows()[0].data == original_row
