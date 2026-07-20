from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import feeder


class FeederTests(unittest.TestCase):
    def test_blank_status_is_ready_and_dry_run_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            path.write_text(
                "person_name,email,company_name,company_domain,source_url,icebreaker,status\n"
                "Ada Lovelace,ada@example.com,Example Co,example.com,https://example.com,Relevant note,\n",
                encoding="utf-8",
            )
            config = config_for(path)
            result = feeder.process(config, dry_run=True, limit=None)
            self.assertEqual(result["ready"], 1)
            self.assertEqual(result["plugged"], 1)
            self.assertIn(",\n", path.read_text(encoding="utf-8"))

    def test_missing_required_fields_fail_live_without_calling_lemlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            path.write_text(
                "person_name,company_name,status\n"
                "Ada Lovelace,Example Co,\n",
                encoding="utf-8",
            )
            config = config_for(path)
            result = feeder.process(config, dry_run=False, limit=None)
            self.assertEqual(result["failed"], 1)
            updated = path.read_text(encoding="utf-8")
            self.assertIn("failed", updated)
            self.assertIn("Missing:", updated)

    def test_duplicate_ready_row_is_marked_plugged_without_second_insert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            path.write_text(
                "person_name,email,company_name,company_domain,source_url,icebreaker,status\n"
                "Ada Lovelace,ada@example.com,Example Co,example.com,https://example.com,Relevant note,plugged\n"
                "Ada Lovelace,ada@example.com,Example Co,example.com,https://example.com,Relevant note,\n",
                encoding="utf-8",
            )
            config = config_for(path)
            result = feeder.process(config, dry_run=False, limit=None)
            self.assertEqual(result["duplicates"], 1)
            self.assertIn("duplicate: already plugged", path.read_text(encoding="utf-8"))

    def test_payload_accepts_context_variables(self) -> None:
        row = {
            "person_name": "Ada Lovelace",
            "email": "ada@example.com",
            "person_linkedin_url": "https://linkedin.com/in/ada",
            "company_name": "Example Co",
            "company_website": "https://www.example.com",
            "evidence": "Saw relevant signal",
            "outreach_reason": "Useful opener",
            "gap_reason": "Checkout confirmation never arrived",
            "opener": "Noticed your demo request path leaks intent.",
            "audit_company_key": "domain:example.com",
        }
        payload, missing = feeder.build_payload(row, "America/New_York")
        self.assertEqual(missing, [])
        self.assertEqual(payload["firstName"], "Ada")
        self.assertEqual(payload["companyDomain"], "example.com")
        self.assertEqual(payload["linkedinUrl"], "https://linkedin.com/in/ada")
        self.assertEqual(payload["gapReason"], "Checkout confirmation never arrived")
        self.assertEqual(payload["outreachReason"], "Useful opener")
        self.assertEqual(payload["opener"], "Noticed your demo request path leaks intent.")
        self.assertEqual(payload["auditCompanyKey"], "domain:example.com")

    def test_custom_variables_are_separated_from_standard_lead_payload(self) -> None:
        row = {
            "person_name": "Ada Lovelace",
            "email": "ada@example.com",
            "company_name": "Example Co",
            "company_domain": "example.com",
            "evidence": "Broken demo flow",
            "gap_reason": "Demo form does not confirm submission",
            "outreach_reason": "They are leaking high-intent demo requests",
            "opener": "Quick note on your demo request flow.",
            "solution_angle": "Add confirmation and routing alerts.",
            "source_url": "https://example.com/demo",
            "icebreaker": "Relevant note",
        }
        payload, missing = feeder.build_payload(row, "America/New_York")
        self.assertEqual(missing, [])
        standard = feeder.standard_lead_payload(payload)
        custom = feeder.custom_variables_for_lemlist(row)
        self.assertIn("email", standard)
        self.assertNotIn("gapReason", standard)
        self.assertEqual(custom["gapReason"], "Demo form does not confirm submission")
        self.assertEqual(custom["outreachReason"], "They are leaking high-intent demo requests")
        self.assertEqual(custom["opener"], "Quick note on your demo request flow.")
        self.assertEqual(custom["solutionAngle"], "Add confirmation and routing alerts.")

    def test_payload_requires_email_for_current_lemlist_api(self) -> None:
        row = {
            "person_name": "Ada Lovelace",
            "person_linkedin_url": "https://linkedin.com/in/ada",
            "company_name": "Example Co",
            "company_website": "https://www.example.com",
            "evidence": "Saw relevant signal",
            "outreach_reason": "Useful opener",
        }
        _, missing = feeder.build_payload(row, "America/New_York")
        self.assertEqual(missing, ["email"])

    def test_custom_variables_accept_sheet_aliases(self) -> None:
        variables = feeder.custom_variables({
            "detected_gap": "Broken popup CTA",
            "opportunity_reason": "Their lead magnet flow drops the next step",
            "email_opener": "Quick note on the popup flow.",
        })
        self.assertEqual(variables["gapReason"], "Broken popup CTA")
        self.assertEqual(
            variables["outreachReason"],
            "Their lead magnet flow drops the next step",
        )
        self.assertEqual(variables["opener"], "Quick note on the popup flow.")

    def test_source_specific_custom_variables(self) -> None:
        aliases = feeder.variable_aliases({
            "custom_variables": {
                "technologies": ["technologies"],
                "automationOpportunity1": ["automation_opportunity_1"],
            }
        })
        variables = feeder.custom_variables_for_lemlist({
            "technologies": "Slack, ClickUp",
            "automation_opportunity_1": "Send ClickUp leads to Slack.",
            "gap_reason": "Must not leak into this campaign",
        }, aliases)
        self.assertEqual(variables, {
            "technologies": "Slack, ClickUp",
            "automationOpportunity1": "Send ClickUp leads to Slack.",
        })

    def test_daily_limit_counts_plugged_rows_in_source_timezone(self) -> None:
        rows = [
            feeder.SheetRow(2, {
                "status": "plugged",
                "lemlist_campaign": "Technology-based outreach",
                "plugged_at": "2026-06-27T08:00:00+00:00",
            }),
            feeder.SheetRow(3, {
                "status": "plugged",
                "lemlist_campaign": "Another campaign",
                "plugged_at": "2026-06-27T09:00:00+00:00",
            }),
        ]
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            feeder.plugged_today(rows, "Technology-based outreach", "Europe/Sofia", now),
            1,
        )

    def test_campaign_id_is_resolved_by_exact_case_insensitive_name(self) -> None:
        campaigns = [
            {"_id": "cam_one", "name": "Pipeline gap detected"},
            {"_id": "cam_two", "name": "Technology-based outreach"},
        ]
        self.assertEqual(
            feeder.campaign_id_from_items(campaigns, "technology-BASED outreach"),
            "cam_two",
        )
        self.assertEqual(feeder.campaign_id_from_items(campaigns, "Technology"), "")

    def test_cross_campaign_duplicate_error_is_not_a_generic_failure(self) -> None:
        self.assertTrue(feeder.is_cross_campaign_duplicate(
            "HTTP Error 500: Lead already in other campaign"
        ))
        self.assertFalse(feeder.is_cross_campaign_duplicate("Missing campaign ID"))

    def test_same_campaign_duplicate_error_is_idempotent(self) -> None:
        self.assertTrue(feeder.is_campaign_duplicate(
            "HTTP Error 400: Bad Request: Lead already in the campaign"
        ))
        self.assertTrue(feeder.is_campaign_duplicate(
            "HTTP Error 500: Lead already in other campaign"
        ))
        self.assertFalse(feeder.is_campaign_duplicate("Missing campaign ID"))

    def test_historical_duplicate_failure_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            path.write_text(
                "person_name,email,company_name,status,lemlist_campaign,lemlist_error\n"
                "Ada Lovelace,ada@example.com,Example Co,failed,Technology-based outreach,HTTP Error 400: Bad Request: Lead already in the campaign\n",
                encoding="utf-8",
            )
            result = feeder.process(config_for(path), dry_run=False, limit=None)
            self.assertEqual(result["duplicates"], 1)
            updated = path.read_text(encoding="utf-8")
            self.assertIn("skipped_existing_campaign", updated)
            self.assertNotIn(",failed,", updated)

    def test_daily_limit_group_counts_both_campaigns(self) -> None:
        config = {
            "campaigns": {
                "technology": {"name": "Technology-based outreach"},
                "technology_linkedin": {"name": "Technology-based outreach - LinkedIn only"},
            },
            "sources": [
                {"campaign_key": "technology", "daily_limit_group": "technology"},
                {"campaign_key": "technology_linkedin", "daily_limit_group": "technology"},
            ],
        }
        names = feeder.campaign_names_for_daily_limit_group(
            config,
            config["sources"][0],
            "Technology-based outreach",
        )
        self.assertEqual(names, {
            "Technology-based outreach",
            "Technology-based outreach - LinkedIn only",
        })

    def test_source_filter_only_processes_selected_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            selected = Path(tmp) / "selected.csv"
            skipped = Path(tmp) / "skipped.csv"
            content = (
                "person_name,email,company_name,company_domain,source_url,icebreaker,status\n"
                "Ada Lovelace,ada@example.com,Example Co,example.com,https://example.com,Relevant note,\n"
            )
            selected.write_text(content, encoding="utf-8")
            skipped.write_text(content, encoding="utf-8")
            config = config_for(selected)
            config["sources"].append({
                "key": "skipped",
                "campaign_key": "technology",
                "type": "csv",
                "path": str(skipped),
            })
            result = feeder.process(config, dry_run=True, limit=None, source_keys={"technology"})
            self.assertEqual(len(result["sources"]), 1)
            self.assertEqual(result["sources"][0]["source"], "technology")
            self.assertEqual(result["ready"], 1)

    def test_row_campaign_name_routes_contacts_to_matching_campaign_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            path.write_text(
                "person_name,email,company_name,company_domain,source_url,icebreaker,status,lemlist_campaign\n"
                "Ada Lovelace,ada@example.com,Example Co,example.com,https://example.com,Relevant note,,Pipeline gap detected - LinkedIn only\n",
                encoding="utf-8",
            )
            config = {
                "default_timezone": "America/New_York",
                "query_params": {},
                "campaigns": {
                    "pipeline_gap": {
                        "name": "Pipeline gap detected",
                        "campaign_id": "cam_email",
                    },
                    "pipeline_gap_linkedin_only": {
                        "name": "Pipeline gap detected - LinkedIn only",
                        "campaign_id": "cam_linkedin",
                    },
                },
                "sources": [
                    {
                        "key": "pipeline_gap",
                        "campaign_key": "pipeline_gap",
                        "type": "csv",
                        "path": str(path),
                    },
                    {
                        "key": "pipeline_gap_linkedin_only",
                        "campaign_key": "pipeline_gap_linkedin_only",
                        "type": "csv",
                        "path": str(path),
                    },
                ],
            }
            normal = feeder.process(config, dry_run=True, limit=None, source_keys={"pipeline_gap"})
            linkedin_only = feeder.process(config, dry_run=True, limit=None, source_keys={"pipeline_gap_linkedin_only"})
            self.assertEqual(normal["ready"], 0)
            self.assertEqual(linkedin_only["ready"], 1)


def config_for(path: Path) -> dict:
    return {
        "default_timezone": "America/New_York",
        "query_params": {},
        "campaigns": {
            "technology": {
                "name": "Technology-based outreach",
                "campaign_id": "cam_test",
            }
        },
        "sources": [
            {
                "key": "technology",
                "campaign_key": "technology",
                "type": "csv",
                "path": str(path),
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
