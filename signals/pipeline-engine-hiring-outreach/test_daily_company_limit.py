from datetime import datetime, timezone

from collect_hiring_signals import company_signal_key, daily_company_count, poster_reference


def test_daily_company_count_uses_sofia_calendar_day_and_unique_jobs():
    values = [
        ["signal_type", "detected_at", "job_id", "company_name", "company_domain"],
        ["pipeline_engine_hiring_intent", "2026-06-29T21:30:00+00:00", "job-1", "One", "one.com"],
        ["pipeline_engine_hiring_intent", "2026-06-29T21:30:00+00:00", "job-9", "One Inc", "www.one.com"],
        ["pipeline_engine_hiring_intent", "2026-06-30T20:59:00+00:00", "job-2", "Two", "two.com"],
        ["pipeline_engine_hiring_intent", "2026-06-30T21:00:00+00:00", "job-3", "Three", "three.com"],
        ["other_signal", "2026-06-30T10:00:00+00:00", "job-4", "Four", "four.com"],
    ]

    count = daily_company_count(
        values,
        timezone_name="Europe/Sofia",
        now=datetime(2026, 6, 30, 12, tzinfo=timezone.utc),
    )

    assert count == 2


def test_daily_company_count_falls_back_to_company_name_without_job_id():
    values = [
        ["detected_at", "job_id", "company_name"],
        ["2026-06-30T08:00:00+00:00", "", "Acme"],
        ["2026-06-30T09:00:00+00:00", "", "ACME"],
    ]

    count = daily_company_count(
        values,
        timezone_name="Europe/Sofia",
        now=datetime(2026, 6, 30, 12, tzinfo=timezone.utc),
    )

    assert count == 1


def test_company_signal_key_prefers_domain_then_linkedin_then_name():
    assert company_signal_key(company_domain="https://www.acme.com/about") == "domain:acme.com"
    assert company_signal_key(company_linkedin_url="https://linkedin.com/company/Acme/") == "linkedin:acme"
    assert company_signal_key(company_name="  ACME   Inc  ") == "name:acme inc"


def test_poster_reference_returns_person_profile():
    details = {"references": {"job_posting": [
        {"kind": "company", "url": "/company/acme"},
        {"kind": "person", "url": "/in/jane-recruiter?trk=jobs"},
    ]}}

    assert poster_reference(details) == "https://www.linkedin.com/in/jane-recruiter/"
