import sys

import run_system


def test_result_metrics_counts_feeder_source_errors():
    metrics = run_system.result_metrics([{
        "step": "feed_existing_contacts",
        "result": {
            "plugged": 2,
            "failed": 1,
            "source_errors": [{"source": "hiring", "error": "sheet unavailable"}],
        },
    }])

    assert metrics["contacts_plugged"] == 2
    assert metrics["failures"] == 2


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

    sourcing = next(command for name, command in commands if name == "collect_hiring_signals")
    assert "--dry-run" in sourcing
    assert all(
        "--dry-run" in command
        for name, command in commands
        if name != "collect_hiring_signals" or "--dry-run" in command
    )
    capsys.readouterr()
