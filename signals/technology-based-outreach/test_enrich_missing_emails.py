from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from enrich_missing_emails import (
    ApolloEnrichmentClient,
    LemlistEnrichmentClient,
    finalize_linkedin_only,
    placeholder_email,
    apollo_enrichment,
    poll_enrichment,
    start_enrichment,
)
from extract_contacts import CsvSheet


class FakeClient(LemlistEnrichmentClient):
    def __init__(self) -> None:
        self.requests = []
        self.results = {}

    def request_find_email(self, rows):
        self.requests.extend(rows)
        return [
            {"id": f"enr_{index}", "metadata": row["metadata"]}
            for index, row in enumerate(rows, start=1)
        ]

    def get_result(self, enrichment_id):
        return self.results[enrichment_id]


class FakeApolloClient(ApolloEnrichmentClient):
    def __init__(self) -> None:
        self.people = {}

    def match_person(self, row):
        return self.people.get(row.get("person_linkedin_url", ""), {})


class EnrichMissingEmailsTests(unittest.TestCase):
    def test_start_queues_needs_email_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,person_linkedin_url,company_domain,first_name,last_name,company_name,email\n"
                "needs_email,https://linkedin.com/in/ada,example.com,Ada,Lovelace,Example,\n",
                encoding="utf-8",
            )
            sheet = CsvSheet(path)
            client = FakeClient()
            result = start_enrichment(sheet, client, dry_run=False, limit=None)
            self.assertEqual(result["queued"], 1)
            self.assertEqual(client.requests[0]["input"]["linkedinUrl"], "https://linkedin.com/in/ada")
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("email_finding", text)
            self.assertIn("enr_1", text)

    def test_poll_sets_email_and_clears_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,email,email_status,lemlist_enrichment_id\n"
                "email_finding,,submitted_to_lemlist,enr_1\n",
                encoding="utf-8",
            )
            sheet = CsvSheet(path)
            client = FakeClient()
            client.results["enr_1"] = {
                "enrichmentStatus": "done",
                "data": {"email": {"email": "ada@example.com", "notFound": False}},
            }
            result = poll_enrichment(sheet, client, dry_run=False, limit=None)
            self.assertEqual(result["found"], 1)
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("ada@example.com", text)
            self.assertIn(",found,", text)

    def test_apollo_fallback_sets_email_and_clears_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,email,email_status,person_linkedin_url\n"
                "email_not_found,,,https://linkedin.com/in/ada\n",
                encoding="utf-8",
            )
            sheet = CsvSheet(path)
            client = FakeApolloClient()
            client.people["https://linkedin.com/in/ada"] = {
                "email": "ada@apollo.test",
                "email_status": "verified",
            }
            result = apollo_enrichment(sheet, client, dry_run=False, limit=None)
            self.assertEqual(result["found"], 1)
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("ada@apollo.test", text)
            self.assertIn("verified", text)

    def test_apollo_fallback_handles_lemlist_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,email,email_status,person_linkedin_url\n"
                "email_enrichment_failed,,,https://linkedin.com/in/ada\n",
                encoding="utf-8",
            )
            sheet = CsvSheet(path)
            client = FakeApolloClient()
            client.people["https://linkedin.com/in/ada"] = {
                "email": "ada@apollo.test",
                "email_status": "verified",
            }
            result = apollo_enrichment(sheet, client, dry_run=False, limit=None)
            self.assertEqual(result["found"], 1)
            self.assertIn("ada@apollo.test", path.read_text(encoding="utf-8-sig"))

    def test_lemlist_failure_is_not_finalized_before_apollo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,email,email_status,person_linkedin_url,lemlist_campaign\n"
                "email_enrichment_failed,,,https://linkedin.com/in/ada,\n",
                encoding="utf-8",
            )
            result = finalize_linkedin_only(CsvSheet(path), dry_run=False, limit=None)
            self.assertEqual(result["finalized"], 0)
            self.assertNotIn("@technology-outreach", path.read_text(encoding="utf-8-sig"))

    def test_finalize_linkedin_only_sets_placeholder_and_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,email,email_status,person_linkedin_url,lemlist_campaign\n"
                "apollo_email_not_found,,,https://linkedin.com/in/ada,\n",
                encoding="utf-8",
            )
            sheet = CsvSheet(path)
            result = finalize_linkedin_only(sheet, dry_run=False, limit=None)
            self.assertEqual(result["finalized"], 1)
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("placeholder_linkedin_only", text)
            self.assertIn("Technology-based outreach - LinkedIn only", text)
            self.assertIn(placeholder_email({"person_linkedin_url": "https://linkedin.com/in/ada"}), text)

    def test_finalize_linkedin_only_accepts_workflow_specific_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.csv"
            path.write_text(
                "status,email,email_status,person_linkedin_url,lemlist_campaign\n"
                "email_not_found,,,https://linkedin.com/in/grace,\n",
                encoding="utf-8",
            )
            sheet = CsvSheet(path)
            result = finalize_linkedin_only(
                sheet,
                dry_run=False,
                limit=None,
                campaign_name="Technology-based outreach - LinkedIn only",
                placeholder_domain="technology-outreach-linkedin-only.invalid",
            )
            self.assertEqual(result["finalized"], 1)
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("Technology-based outreach - LinkedIn only", text)
            self.assertIn("@technology-outreach-linkedin-only.invalid", text)


if __name__ == "__main__":
    unittest.main()
