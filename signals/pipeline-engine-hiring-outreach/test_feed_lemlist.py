from datetime import datetime, timezone

import feed_lemlist
from feed_lemlist import (
    SheetRow,
    local_date,
    plugged_today_for_campaigns,
    process,
)


def test_local_date_converts_timestamp_to_sofia_calendar_day():
    assert (
        local_date("2026-07-26T22:30:00+00:00", "Europe/Sofia")
        == "2026-07-27"
    )
    assert local_date("", "Europe/Sofia") == ""
    assert local_date("not-a-date", "Europe/Sofia") == ""


def test_shared_daily_cap_counts_both_campaigns():
    rows = [
        SheetRow(2, {
            "status": "plugged",
            "lemlist_campaign": "Pipeline Engine hiring outreach",
            "plugged_at": "2026-07-27T06:00:00+00:00",
        }),
        SheetRow(3, {
            "status": "plugged",
            "lemlist_campaign": "Pipeline Engine hiring outreach - LinkedIn only",
            "plugged_at": "2026-07-27T07:00:00+00:00",
        }),
        SheetRow(4, {
            "status": "plugged",
            "lemlist_campaign": "Pipeline Engine hiring outreach",
            "plugged_at": "2026-07-26T06:00:00+00:00",
        }),
    ]

    assert plugged_today_for_campaigns(
        rows,
        {
            "Pipeline Engine hiring outreach",
            "Pipeline Engine hiring outreach - LinkedIn only",
        },
        "Europe/Sofia",
        datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
    ) == 2


def test_source_open_failure_is_reported_as_a_pipeline_error(monkeypatch):
    def fail_open(_source):
        raise RuntimeError("sheet unavailable")

    monkeypatch.setattr(feed_lemlist, "open_sheet", fail_open)
    config = {
        "lemlist_api_key_env": "UNSET_TEST_LEMLIST_KEY",
        "campaigns": {
            "hiring": {
                "name": "Pipeline Engine hiring outreach",
                "campaign_id": "cam_test",
            },
        },
        "sources": [{
            "key": "hiring",
            "campaign_key": "hiring",
            "type": "google_sheet",
            "spreadsheet_id": "sheet_test",
            "worksheet": "Contacts",
        }],
    }

    result = process(config, dry_run=True, limit=None)

    assert result["source_errors"] == [{
        "source": "hiring",
        "error": "sheet unavailable",
    }]
    assert result["sources"][0]["error"] == "sheet unavailable"
