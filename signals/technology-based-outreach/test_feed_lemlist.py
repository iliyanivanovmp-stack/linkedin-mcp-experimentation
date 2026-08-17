from __future__ import annotations

import unittest
from unittest.mock import patch

from feed_lemlist import (
    attempt_count,
    build_payload,
    custom_variables,
    process,
    retryable_row,
    variable_aliases,
)


class MemorySheet:
    def __init__(self, rows):
        self.headers = list(rows[0].keys()) if rows else []
        self._rows = [dict(row) for row in rows]

    def rows(self):
        from feed_lemlist import SheetRow

        return [
            SheetRow(number=index + 2, data=dict(row))
            for index, row in enumerate(self._rows)
        ]

    def ensure_columns(self, columns):
        for column in columns:
            if column not in self.headers:
                self.headers.append(column)
                for row in self._rows:
                    row[column] = ""

    def update_row(self, row_number, updates):
        self._rows[row_number - 2].update(updates)


class FakeLemlistClient:
    payloads = []

    def __init__(self, api_key, query_params):
        self.api_key = api_key
        self.query_params = query_params

    def create_lead(self, campaign_id, payload):
        self.payloads.append((campaign_id, payload))
        return {"_id": "lea_linkedin"}

    def add_custom_variables(self, lead_id, variables):
        return {"ok": True}


class FeedLemlistRetryTests(unittest.TestCase):
    def test_transient_failures_retry_up_to_three_attempts(self) -> None:
        self.assertTrue(retryable_row("failed", 1))
        self.assertTrue(retryable_row("failed", 2))
        self.assertFalse(retryable_row("failed", 3))

    def test_validation_failures_are_terminal(self) -> None:
        self.assertFalse(retryable_row("validation_failed", 1))

    def test_malformed_attempt_count_recovers_safely(self) -> None:
        self.assertEqual(attempt_count("not-a-number"), 0)

    def test_contrarian_hook_is_derived_from_technologies(self) -> None:
        aliases = variable_aliases({
            "custom_variables": {"contrarianHook": ["contrarian_hook"]},
        })
        variables = custom_variables({"technologies": "HubSpot, Slack"}, aliases)
        self.assertIn("HubSpot and Slack", variables["contrarianHook"])

    def test_missing_message_variable_fails_validation(self) -> None:
        aliases = variable_aliases({
            "custom_variables": {
                "technologies": ["technologies"],
                "automationOpportunity1": ["automation_opportunity_1"],
            },
        })
        _, missing = build_payload(
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "company_name": "Analytical Engines",
                "company_domain": "analytical.example",
                "source_url": "https://analytical.example",
                "icebreaker": "Saw your team is using HubSpot and Slack.",
                "technologies": "HubSpot, Slack",
            },
            "Europe/Sofia",
            aliases,
            ["technologies", "automationOpportunity1"],
        )
        self.assertIn("custom variable automationOpportunity1", missing)

    def test_linkedin_only_source_processes_email_campaign_plugged_rows(self) -> None:
        sheet = MemorySheet([
            {
                "status": "plugged",
                "lemlist_campaign": "Technology-based outreach",
                "lemlist_lead_id": "lea_email",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "person_name": "Ada Lovelace",
                "person_linkedin_url": "https://linkedin.com/in/ada",
                "email": "ada@example.com",
                "company_name": "Analytical Engines",
                "company_domain": "analytical.example",
                "source_url": "https://analytical.example",
                "icebreaker": "Saw your team is using HubSpot.",
            }
        ])
        config = {
            "default_timezone": "Europe/Sofia",
            "lemlist_api_key_env": "LEMLIST_API_KEY",
            "campaigns": {
                "technology_linkedin_only": {
                    "name": "Technology-based outreach - LinkedIn only",
                    "campaign_id": "cam_linkedin",
                }
            },
            "sources": [
                {
                    "key": "technology_linkedin_only",
                    "campaign_key": "technology_linkedin_only",
                    "type": "google_sheet",
                    "state_prefix": "linkedin_only",
                    "email_mode": "linkedin_placeholder",
                    "worksheet": "Contacts",
                    "daily_limit": 0,
                }
            ],
        }
        FakeLemlistClient.payloads = []
        with patch.dict("os.environ", {"LEMLIST_API_KEY": "key"}), patch(
            "feed_lemlist.open_sheet",
            return_value=sheet,
        ), patch("feed_lemlist.LemlistClient", FakeLemlistClient):
            result = process(config, dry_run=False, limit=None)

        self.assertEqual(result["plugged"], 1)
        campaign_id, payload = FakeLemlistClient.payloads[0]
        self.assertEqual(campaign_id, "cam_linkedin")
        self.assertTrue(payload["email"].startswith("linkedin-only+"))
        self.assertNotEqual(payload["email"], "ada@example.com")
        self.assertEqual(sheet._rows[0]["status"], "plugged")
        self.assertEqual(sheet._rows[0]["lemlist_campaign"], "Technology-based outreach")
        self.assertEqual(sheet._rows[0]["linkedin_only_status"], "plugged")
        self.assertEqual(sheet._rows[0]["linkedin_only_lemlist_lead_id"], "lea_linkedin")

    def test_linkedin_only_source_respects_legacy_plugged_rows(self) -> None:
        sheet = MemorySheet([
            {
                "status": "plugged",
                "lemlist_campaign": "Technology-based outreach - LinkedIn only",
                "lemlist_lead_id": "lea_existing",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "person_linkedin_url": "https://linkedin.com/in/ada",
                "email": "linkedin-only+existing@technology-outreach-linkedin-only.invalid",
                "company_name": "Analytical Engines",
                "company_domain": "analytical.example",
                "source_url": "https://analytical.example",
                "icebreaker": "Saw your team is using HubSpot.",
            }
        ])
        config = {
            "default_timezone": "Europe/Sofia",
            "lemlist_api_key_env": "LEMLIST_API_KEY",
            "campaigns": {
                "technology_linkedin_only": {
                    "name": "Technology-based outreach - LinkedIn only",
                    "campaign_id": "cam_linkedin",
                }
            },
            "sources": [
                {
                    "key": "technology_linkedin_only",
                    "campaign_key": "technology_linkedin_only",
                    "type": "google_sheet",
                    "state_prefix": "linkedin_only",
                    "email_mode": "linkedin_placeholder",
                    "worksheet": "Contacts",
                    "daily_limit": 0,
                }
            ],
        }
        FakeLemlistClient.payloads = []
        with patch.dict("os.environ", {"LEMLIST_API_KEY": "key"}), patch(
            "feed_lemlist.open_sheet",
            return_value=sheet,
        ), patch("feed_lemlist.LemlistClient", FakeLemlistClient):
            result = process(config, dry_run=False, limit=None)

        self.assertEqual(result["plugged"], 0)
        self.assertEqual(FakeLemlistClient.payloads, [])


if __name__ == "__main__":
    unittest.main()
