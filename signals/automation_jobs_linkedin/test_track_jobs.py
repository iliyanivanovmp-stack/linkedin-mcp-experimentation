import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import track_jobs
from modal_app import _is_authorized
from track_jobs import (
    description_from_guest_html,
    evaluate_job,
    filter_new_sheet_rows,
    load_seen,
    poster_url_from_guest_html,
    save_seen,
    validate_config,
    write_rows_to_canonical_columns,
)


CONFIG = json.loads((Path(__file__).parent / "config.json").read_text())


def test_extracts_profile_from_hirer_card():
    raw = '''
    <section class="hirer-card__container">
      <a href="https://www.linkedin.com/in/jane-recruiter?trk=public_jobs">Jane</a>
    </section>
    '''
    assert poster_url_from_guest_html(raw) == "https://www.linkedin.com/in/jane-recruiter/"


def test_ignores_unrelated_profile_link():
    raw = '<nav><a href="https://www.linkedin.com/in/unrelated">Profile</a></nav>'
    assert poster_url_from_guest_html(raw) == ""


@pytest.mark.parametrize(
    ("title", "description"),
    [
        (
            "AI Transformation Engineer (AI Solutions / Automation)",
            "Remote contract building AI-powered tools and workflow automation.",
        ),
        (
            "AI Solutions Engineer - Automation",
            "Build API integrations, LLM workflows, and business automations.",
        ),
        (
            "Marketing Automation Manager",
            "Remote short-term project creating lifecycle email and CRM automation.",
        ),
        (
            "Marketing Automation Specialist, Journey Builder",
            "Contract role configuring automated customer journeys.",
        ),
        (
            "AI Systems User - Fully Remote",
            "Contract role evaluating practical AI agents and business outcomes.",
        ),
        (
            "Freelance Ecommerce Automation Specialist",
            "Project-based workflow automation and API integration work.",
        ),
        (
            "AI Trainer - Marketing Automation",
            "Evaluate LLM applications for email marketing and CRM automation.",
        ),
    ],
)
def test_accepts_candidate_aligned_jobs(title, description):
    result = evaluate_job(title, description, CONFIG)
    assert result["accepted"], result
    assert result["score"] >= CONFIG["relevance"]["minimum_score"]


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Data Scientist, Healthcare Analytics and AI", "Build analytical models."),
        ("Digital Product Content Manager", "Own product content and taxonomy."),
        ("Business Analyst", "Gather requirements for HR systems."),
        ("AI Data Engineer", "Build data pipelines and dashboards."),
        ("Associate AI/ML Developer", "Predictive analytics and machine learning."),
        ("Robotics Automation Engineer", "Design robotic handling systems."),
        ("Software Engineer - AI Automation", "Build production software."),
        ("Founding ML Engineer", "Design multimodal model architectures."),
        ("AI Engineer/Analyst", "Analyze operational datasets."),
        ("AI Trainer - Industrial Engineers", "Improve models using industrial engineering expertise."),
        ("Regulatory Compliance Manager - Freelance AI Trainer", "Banking compliance expertise required."),
        ("Armenian Language Specialist - Freelance AI Trainer", "Language specialist project."),
        ("Test Automation Engineer - AI Trainer", "Solve coding problems and test software."),
        ("AI Trainer", "General project with no stated subject-matter domain."),
    ],
)
def test_rejects_misaligned_jobs(title, description):
    result = evaluate_job(title, description, CONFIG)
    assert not result["accepted"], result
    assert result["rejection_reason"]


def test_generic_ai_title_requires_aligned_role_family():
    result = evaluate_job(
        "AI Engineer",
        "Remote role that mentions automation but primarily builds model infrastructure.",
        CONFIG,
    )
    assert not result["accepted"]
    assert result["rejection_reason"] == "no candidate-aligned role family in title"


@pytest.mark.parametrize(
    "title",
    [
        "AI Agent & Automation Engineer",
        "AI Workflow Builder",
        "AI & Automation Engineer",
        "AI Solutions & Automation Developer",
        "Enterprise Automation & AI Engineer",
    ],
)
def test_accepts_observed_ai_automation_title_variants(title):
    result = evaluate_job(
        title,
        "Remote contract building AI agents, n8n workflows, and API integrations.",
        CONFIG,
    )
    assert result["accepted"], result
    assert result["score"] >= 14


def test_ai_automation_ranks_above_marketing_automation():
    ai_result = evaluate_job(
        "AI Agent & Automation Engineer",
        "Remote contract building AI agents and business workflows.",
        CONFIG,
    )
    marketing_result = evaluate_job(
        "Marketing Automation Specialist",
        "Remote contract building CRM and lifecycle automation.",
        CONFIG,
    )
    assert ai_result["accepted"]
    assert marketing_result["accepted"]
    assert ai_result["score"] > marketing_result["score"]


def test_first_two_search_lanes_are_ai_first():
    assert all("AI" in query for query in CONFIG["search_queries"][:2])
    assert "marketing automation" in CONFIG["search_queries"][2].casefold()


@pytest.mark.parametrize(
    "description",
    [
        "Remote role with a hybrid schedule and two office days each week.",
        "Listed as remote, but this is an on-site position.",
        "Remote contract. You must visit the office once per quarter.",
        "Work from home, with monthly in-person office attendance required.",
        "Remote on Mondays and Fridays; working from the office on other days.",
    ],
)
def test_rejects_any_physical_office_requirement(description):
    result = evaluate_job("AI Automation Specialist", description, CONFIG)
    assert not result["accepted"], result
    assert result["rejection_reason"].startswith("not fully remote:")


@pytest.mark.parametrize(
    "description",
    [
        "Fully remote contract building workflow automations.",
        "100% remote, work from anywhere, with async collaboration.",
        # LinkedIn's remote-only filter is the source of truth when the body is silent.
        "Contract role building n8n and API automations.",
    ],
)
def test_accepts_remote_roles_without_physical_presence(description):
    result = evaluate_job("AI Automation Specialist", description, CONFIG)
    assert result["accepted"], result
    assert "LinkedIn remote-only filter" in result["positive_signals"]


@pytest.mark.parametrize(
    "description",
    [
        "Build secure tools for hybrid workers in a fully remote role.",
        "Remote contract. The benefits page also lists in-office snacks.",
        "Remote position supporting customers with office-based employees.",
    ],
)
def test_incidental_workplace_words_do_not_cause_false_rejection(description):
    result = evaluate_job("AI Automation Specialist", description, CONFIG)
    assert result["accepted"], result


@pytest.mark.parametrize(
    "description",
    [
        (
            "All applicants applying for U.S. job openings must be legally "
            "authorized to work in the United States."
        ),
        "Candidates are required to have valid U.S. work authorization.",
        "U.S. work rights are required for this contract.",
        "Visa sponsorship is not available for this position.",
        "We are unable to sponsor employment visas at this time.",
    ],
)
def test_rejects_jobs_requiring_us_work_rights(description):
    result = evaluate_job("Marketing Automation Specialist", description, CONFIG)
    assert not result["accepted"], result
    assert result["rejection_reason"].startswith("work authorization incompatible:")


@pytest.mark.parametrize(
    "description",
    [
        "Remote contract open worldwide; no existing U.S. work authorization is required.",
        "Visa sponsorship is available for qualified candidates.",
        "We support candidates through the U.S. work authorization process.",
    ],
)
def test_does_not_reject_compatible_authorization_language(description):
    result = evaluate_job("AI Automation Specialist", description, CONFIG)
    assert result["accepted"], result


def test_config_validation_requires_remote_only_search():
    unsafe = json.loads(json.dumps(CONFIG))
    unsafe["work_type"] = "remote,hybrid"
    with pytest.raises(ValueError, match="exactly 'remote'"):
        validate_config(unsafe, Path(__file__).parent / "config.json")


def test_nested_guest_description_is_not_truncated():
    raw = """
    <div class="show-more-less-html__markup">
      <p>Build workflows</p>
      <div><strong>Requirements</strong><ul><li>n8n</li><li>APIs</li></ul></div>
      <p>Remote contract</p>
    </div>
    """
    assert description_from_guest_html(raw).splitlines() == [
        "Build workflows", "Requirements", "n8n", "APIs", "Remote contract",
    ]


def test_guest_description_tolerates_valueless_class_attributes():
    raw = '<div class><div class="show-more-less-html__markup"><p>Valid text</p></div></div>'
    assert description_from_guest_html(raw) == "Valid text"


def test_negative_opportunity_signals_reduce_score():
    normal = evaluate_job(
        "Marketing Automation Specialist", "Remote contract CRM automation.", CONFIG,
    )
    restricted = evaluate_job(
        "Marketing Automation Specialist",
        "Remote contract CRM automation. Must be located in the United States. "
        "Requires 10+ years experience.",
        CONFIG,
    )
    assert restricted["score"] < normal["score"]
    assert "restricted remote geography" in restricted["negative_signals"]


def test_candidate_profile_contract_and_regexes_validate():
    profile = validate_config(CONFIG, Path(__file__).parent / "config.json")
    assert profile["schema_version"] == 1


@pytest.mark.parametrize(
    "example",
    CONFIG["relevance"]["profile_coverage_examples"],
)
def test_every_profile_coverage_example_is_accepted(example):
    result = evaluate_job(example["title"], example["description"], CONFIG)
    assert result["accepted"], result


def test_state_write_is_atomic_and_round_trips(tmp_path):
    state = tmp_path / "nested" / "seen.json"
    save_seen(state, {"2", "1"})
    assert load_seen(state) == {"1", "2"}
    assert not list(state.parent.glob(".seen.json.*"))


def test_corrupt_state_fails_loudly(tmp_path):
    state = tmp_path / "seen.json"
    state.write_text("not json")
    with pytest.raises(RuntimeError, match="unreadable"):
        load_seen(state)


def test_sheet_dedup_uses_job_id_job_url_and_current_batch():
    header = ["company_name", "job_url", "job_id"]
    existing = [
        header,
        ["Existing", "https://linkedin.com/jobs/view/1/", "1"],
    ]
    rows = [
        {"company_name": "Same ID", "job_url": "https://other.test/1", "job_id": "1"},
        {"company_name": "Same URL", "job_url": "https://linkedin.com/jobs/view/1/", "job_id": "2"},
        {"company_name": "New", "job_url": "https://linkedin.com/jobs/view/3/", "job_id": "3"},
        {"company_name": "Batch duplicate", "job_url": "https://duplicate.test/3", "job_id": "3"},
    ]

    new_rows, duplicates_skipped = filter_new_sheet_rows(rows, header, existing)

    assert new_rows == [rows[2]]
    assert duplicates_skipped == 3


def test_sheet_rows_are_written_to_explicit_a_based_range():
    class Worksheet:
        def __init__(self):
            self.calls = []

        def update(self, **kwargs):
            self.calls.append(kwargs)

    ws = Worksheet()
    header = ["detected_at", "company_name", "job_url"]
    rows = [
        {"detected_at": "now", "company_name": "Acme", "job_url": "job-1"},
        {"detected_at": "later", "company_name": "Beta", "job_url": "job-2"},
    ]

    write_rows_to_canonical_columns(ws, rows, header, start_row=31)

    assert ws.calls == [{
        "values": [
            ["now", "Acme", "job-1"],
            ["later", "Beta", "job-2"],
        ],
        "range_name": "A31:C32",
        "value_input_option": "RAW",
    }]


def test_http_bearer_authentication_is_fail_closed():
    assert _is_authorized("Bearer correct", "correct")
    assert _is_authorized("bearer correct", "correct")
    assert not _is_authorized(None, "correct")
    assert not _is_authorized("Bearer wrong", "correct")
    assert not _is_authorized("Bearer correct", "")
    assert not _is_authorized("correct", "correct")


def test_http_get_retries_rate_limits(monkeypatch):
    attempts = []
    sleeps = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"ok"

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "rate limited", {"Retry-After": "1"}, None,
            )
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", sleeps.append)
    assert track_jobs._http_get("https://example.test") == "ok"
    assert len(attempts) == 2
    assert sleeps == [1.0]


def _accepted_collection(job_id="new-job"):
    return {
        "searches": [],
        "jobs_inspected": 1,
        "evaluations": [{
            "job_id": job_id, "job_title": "AI Automation Specialist",
            "accepted": True, "score": 10, "positive_signals": ["automation role"],
            "negative_signals": [], "rejection_reason": "",
        }],
        "jobs": [{
            "job_id": job_id, "job_title": "AI Automation Specialist",
            "company_name": "Example", "company_website": "https://example.com",
            "job_url": f"https://linkedin.com/jobs/view/{job_id}/",
            "poster_linkedin_url": "", "text": "Example\nAI Automation Specialist\nAbout the job\nRemote contract",
            "relevance_score": 10, "relevance_signals": ["automation role"],
            "negative_signals": [], "search_lane": 1,
        }],
        "health": {"collector": "test", "detail_failures": 0, "failures": []},
    }


def _run_main(monkeypatch, tmp_path, *, reset=False, credentials=True, sheet_error=None, slack_error=None):
    state = tmp_path / "seen.json"
    save_seen(state, {"historical-job"})
    creds = tmp_path / "creds.json"
    if credentials:
        creds.write_text("{}")

    async def fake_collect(config):
        return _accepted_collection()

    def fake_append(rows, path):
        if sheet_error:
            raise sheet_error
        return {
            "sheet_url": "https://example.test/sheet",
            "rows_written": len(rows),
            "duplicates_skipped": 0,
        }

    def fake_slack(*args):
        if slack_error:
            raise slack_error

    monkeypatch.setattr(track_jobs, "collect", fake_collect)
    monkeypatch.setattr(track_jobs, "append_to_sheet", fake_append)
    monkeypatch.setattr(track_jobs, "send_slack", fake_slack)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.test/hook")
    argv = ["track_jobs.py", "--state", str(state), "--credentials", str(creds)]
    if reset:
        argv.append("--reset-state")
    monkeypatch.setattr(sys, "argv", argv)
    return state


def test_reset_reprocesses_without_erasing_history(monkeypatch, tmp_path, capsys):
    state = _run_main(monkeypatch, tmp_path, reset=True)
    track_jobs.main()
    assert load_seen(state) == {"historical-job", "new-job"}
    assert json.loads(capsys.readouterr().out)["delivery_status"] == "delivered"


def test_preview_without_credentials_does_not_mark_job_seen(monkeypatch, tmp_path, capsys):
    state = _run_main(monkeypatch, tmp_path, credentials=False)
    track_jobs.main()
    assert load_seen(state) == {"historical-job"}
    assert json.loads(capsys.readouterr().out)["delivery_status"] == "preview_not_delivered"


def test_sheet_failure_does_not_mark_job_seen(monkeypatch, tmp_path):
    state = _run_main(monkeypatch, tmp_path, sheet_error=RuntimeError("sheet down"))
    with pytest.raises(RuntimeError, match="sheet down"):
        track_jobs.main()
    assert load_seen(state) == {"historical-job"}


def test_slack_failure_does_not_undo_successful_delivery(monkeypatch, tmp_path, capsys):
    state = _run_main(monkeypatch, tmp_path, slack_error=RuntimeError("slack down"))
    track_jobs.main()
    assert load_seen(state) == {"historical-job", "new-job"}
    payload = json.loads(capsys.readouterr().out)
    assert payload["delivery_status"] == "delivered"
    assert payload["slack_status"].startswith("failed:")
