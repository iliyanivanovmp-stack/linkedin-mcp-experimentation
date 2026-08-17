import sys
import json

import run_system


def test_result_metrics_counts_feeder_source_errors():
    metrics = run_system.result_metrics(
        [
            {
                "step": "feed_existing_contacts",
                "result": {
                    "plugged": 2,
                    "failed": 1,
                    "source_errors": [
                        {"source": "hiring", "error": "sheet unavailable"}
                    ],
                },
            }
        ]
    )

    assert metrics["contacts_plugged"] == 2
    assert metrics["failures"] == 2


def test_result_metrics_counts_contact_extraction_failures():
    metrics = run_system.result_metrics(
        [
            {
                "step": "extract_contacts",
                "result": {"contacts_inserted": 9, "failures": 7},
            }
        ]
    )

    assert metrics["contacts_inserted"] == 9
    assert metrics["failures"] == 7


def test_slack_message_reports_success_metrics():
    message = run_system.slack_message(
        {
            "status": "success",
            "finished_at": "2026-08-06T12:00:00+00:00",
            "metrics": {
                "companies_inserted": 2,
                "contacts_inserted": 5,
                "contacts_plugged": 4,
                "failures": 0,
            },
        }
    )

    assert "completed" in message
    assert "Companies added: 2" in message
    assert "Lemlist leads added: 4" in message


def test_slack_message_labels_dry_run():
    message = run_system.slack_message(
        {
            "status": "success",
            "dry_run": True,
            "metrics": {},
        }
    )

    assert "dry run completed" in message


def test_slack_message_labels_failed_dry_run():
    message = run_system.slack_message(
        {
            "status": "error",
            "dry_run": True,
            "metrics": {},
            "steps": [],
        }
    )

    assert "dry run failed" in message


def test_slack_message_reports_failed_step():
    message = run_system.slack_message(
        {
            "status": "error",
            "finished_at": "2026-08-06T12:00:00+00:00",
            "metrics": {},
            "steps": [
                {
                    "step": "collect_hiring_signals",
                    "ok": False,
                    "stderr": "No authentication found",
                }
            ],
        }
    )

    assert "failed" in message
    assert "Error step: collect_hiring_signals" in message
    assert "No authentication found" in message


def test_slack_message_uses_structured_error_when_stderr_empty():
    message = run_system.slack_message(
        {
            "status": "error",
            "metrics": {},
            "steps": [
                {
                    "step": "collect_hiring_signals",
                    "ok": False,
                    "stderr": "",
                    "result": {"error": "Central LinkedIn MCP session is not valid"},
                }
            ],
        }
    )

    assert "Error step: collect_hiring_signals" in message
    assert "Central LinkedIn MCP session is not valid" in message


def test_post_slack_message_uses_bot_token(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"ok": true, "ts": "123.456"}'

        def close(self):
            return None

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_system.urllib.request, "urlopen", fake_urlopen)

    result = run_system.post_slack_message("xoxb-test", "C123", "hello")

    assert result == "123.456"
    assert captured["authorization"] == "Bearer xoxb-test"
    assert captured["payload"] == {"channel": "C123", "text": "hello"}
    assert captured["timeout"] == 15


def test_dry_run_is_propagated_to_sourcing(monkeypatch, capsys):
    commands = []

    def fake_run(name, command, env):
        commands.append((name, command))
        return {
            "step": name,
            "ok": True,
            "returncode": 0,
            "result": {},
            "stderr": "",
        }

    monkeypatch.setattr(run_system, "run", fake_run)
    monkeypatch.setattr(run_system, "load_env", lambda: {})
    monkeypatch.setattr(run_system, "notify_result", lambda env, payload: None)
    monkeypatch.setattr(sys, "argv", ["run_system.py", "--dry-run"])

    run_system.main()

    sourcing = next(
        command for name, command in commands if name == "collect_hiring_signals"
    )
    assert "--dry-run" in sourcing
    assert all(
        "--dry-run" in command
        for name, command in commands
        if name != "collect_hiring_signals" or "--dry-run" in command
    )
    capsys.readouterr()
