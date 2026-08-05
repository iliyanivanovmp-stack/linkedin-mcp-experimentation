from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from extract_contacts import (
    CascadeDecisionMakerFinder,
    CONTACT_COLUMNS,
    Contact,
    CsvSheet,
    StaticDecisionMakerFinder,
    company_payload,
    extract_contacts,
    lemlist_contact,
    qualified_company,
)


class FakeFinder:
    def __init__(self, contacts: list[Contact]) -> None:
        self.contacts = contacts
        self.calls = 0

    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        self.calls += 1
        return self.contacts[:limit]


class ExtractContactsTests(unittest.TestCase):
    def test_qualified_company_accepts_audit_status(self) -> None:
        row = {"audit_status": "outreach_ready", "company_name": "Acme"}
        self.assertTrue(qualified_company(row, {"outreach_ready"}))

    def test_qualified_company_rejects_do_not_sequence(self) -> None:
        row = {
            "audit_status": "outreach_ready",
            "company_name": "Acme",
            "do_not_sequence": "true",
        }
        self.assertFalse(qualified_company(row, {"outreach_ready"}))

    def test_company_payload_normalizes_domain_company_name(self) -> None:
        row = {
            "domain": "example.com",
            "source_url": "https://example.com",
            "broken_funnel_pages": "[{\"url\":\"https://example.com/demo\"}]",
        }
        payload = company_payload(row)
        self.assertEqual(payload["company_name"], "Example")
        self.assertEqual(payload["company_domain"], "example.com")

    def test_company_payload_preserves_automation_opening_variables(self) -> None:
        payload = company_payload({
            "company_name": "Acme",
            "company_domain": "acme.com",
            "opening_job_title": "AI Workflow Builder",
            "opening_job_url": "https://example.com/jobs/1",
            "opening_compensation": "$100,000 per year",
            "opening_responsibilities": "Build AI agents and workflows.",
            "desired_outcome": "Automate repeatable workflows",
            "build_vs_hire_angle": "Build the system with less risk.",
            "additional_openings": "AI Solutions Engineer",
            "personalized_opener": "Saw Acme is hiring an AI Workflow Builder.",
        })
        self.assertEqual(payload["opening_job_title"], "AI Workflow Builder")
        self.assertEqual(payload["opening_compensation"], "$100,000 per year")
        self.assertEqual(payload["desired_outcome"], "Automate repeatable workflows")
        self.assertIn("less risk", payload["build_vs_hire_angle"])

    def test_extracts_three_contacts_to_blank_status_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            companies = Path(tmp) / "companies.csv"
            contacts = Path(tmp) / "contacts.csv"
            companies.write_text(
                "company_name,company_domain,audit_status,outreach_reason,source_url\n"
                "Acme,acme.com,outreach_ready,Demo form failed,https://acme.com/demo\n",
                encoding="utf-8",
            )
            finder = StaticDecisionMakerFinder({
                "acme.com": [
                    {"person_name": "Ada Lovelace", "person_linkedin_url": "https://linkedin.com/in/ada"},
                    {"person_name": "Grace Hopper", "person_linkedin_url": "https://linkedin.com/in/grace"},
                    {"person_name": "Alan Turing", "person_linkedin_url": "https://linkedin.com/in/alan"},
                    {"person_name": "Katherine Johnson", "person_linkedin_url": "https://linkedin.com/in/katherine"},
                ]
            })
            result = asyncio.run(extract_contacts(
                CsvSheet(companies),
                CsvSheet(contacts),
                finder,
                config(),
                dry_run=False,
                limit=None,
            ))
            self.assertEqual(result["contacts_inserted"], 3)
            text = contacts.read_text(encoding="utf-8-sig")
            self.assertIn("Ada Lovelace", text)
            self.assertIn("Pipeline gap detected", text)
            self.assertTrue(text.startswith(",".join(CONTACT_COLUMNS[:6])))
            company_text = companies.read_text(encoding="utf-8-sig")
            self.assertIn("contacts_generated", company_text)
            self.assertIn("contacts_ready_count", company_text)

    def test_skips_duplicate_contacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            companies = Path(tmp) / "companies.csv"
            contacts = Path(tmp) / "contacts.csv"
            companies.write_text(
                "company_name,company_domain,audit_status,outreach_reason,source_url\n"
                "Acme,acme.com,outreach_ready,Demo form failed,https://acme.com/demo\n",
                encoding="utf-8",
            )
            contacts.write_text(
                "person_linkedin_url,status\n"
                "https://linkedin.com/in/ada,\n",
                encoding="utf-8",
            )
            finder = StaticDecisionMakerFinder({
                "acme.com": [
                    {"person_name": "Ada Lovelace", "person_linkedin_url": "https://linkedin.com/in/ada"},
                ]
            })
            result = asyncio.run(extract_contacts(
                CsvSheet(companies),
                CsvSheet(contacts),
                finder,
                config(),
                dry_run=False,
                limit=None,
            ))
            self.assertEqual(result["duplicates_skipped"], 1)
            self.assertEqual(result["contacts_inserted"], 0)
            company_text = companies.read_text(encoding="utf-8-sig")
            self.assertIn("no_new_contacts", company_text)

    def test_skips_completed_company_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            companies = Path(tmp) / "companies.csv"
            contacts = Path(tmp) / "contacts.csv"
            companies.write_text(
                "company_name,company_domain,audit_status,contacts_status\n"
                "Acme,acme.com,outreach_ready,contacts_generated\n",
                encoding="utf-8",
            )
            finder = StaticDecisionMakerFinder({
                "acme.com": [
                    {"person_name": "Ada Lovelace", "person_linkedin_url": "https://linkedin.com/in/ada"},
                ]
            })
            result = asyncio.run(extract_contacts(
                CsvSheet(companies),
                CsvSheet(contacts),
                finder,
                config(),
                dry_run=False,
                limit=None,
            ))
            self.assertEqual(result["companies_skipped_by_guardrail"], 1)
            self.assertEqual(result["contacts_inserted"], 0)

    def test_daily_contact_limit_stops_and_marks_partial_company(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            companies = Path(tmp) / "companies.csv"
            contacts = Path(tmp) / "contacts.csv"
            companies.write_text(
                "company_name,company_domain,audit_status\n"
                "Acme,acme.com,outreach_ready\n"
                "Beta,beta.com,outreach_ready\n",
                encoding="utf-8",
            )
            finder = StaticDecisionMakerFinder({
                "acme.com": [
                    {"person_name": "A One", "person_linkedin_url": "https://linkedin.com/in/a1"},
                    {"person_name": "A Two", "person_linkedin_url": "https://linkedin.com/in/a2"},
                    {"person_name": "A Three", "person_linkedin_url": "https://linkedin.com/in/a3"},
                ],
                "beta.com": [
                    {"person_name": "B One", "person_linkedin_url": "https://linkedin.com/in/b1"},
                    {"person_name": "B Two", "person_linkedin_url": "https://linkedin.com/in/b2"},
                    {"person_name": "B Three", "person_linkedin_url": "https://linkedin.com/in/b3"},
                ],
            })
            limited_config = {**config(), "daily_contact_limit": 4, "timezone": "Europe/Sofia"}
            result = asyncio.run(extract_contacts(
                CsvSheet(companies),
                CsvSheet(contacts),
                finder,
                limited_config,
                dry_run=False,
                limit=None,
            ))
            self.assertEqual(result["contacts_inserted"], 4)
            self.assertEqual(result["daily_contact_limit"], 4)
            self.assertIn("contacts_partial", companies.read_text(encoding="utf-8-sig"))

    def test_retry_failed_guardrail_allows_failed_company(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            companies = Path(tmp) / "companies.csv"
            contacts = Path(tmp) / "contacts.csv"
            companies.write_text(
                "company_name,company_domain,audit_status,contacts_status\n"
                "Acme,acme.com,outreach_ready,contacts_failed\n",
                encoding="utf-8",
            )
            finder = StaticDecisionMakerFinder({
                "acme.com": [
                    {"person_name": "Ada Lovelace", "person_linkedin_url": "https://linkedin.com/in/ada"},
                ]
            })
            skipped = asyncio.run(extract_contacts(
                CsvSheet(companies),
                CsvSheet(contacts),
                finder,
                config(),
                dry_run=False,
                limit=None,
            ))
            self.assertEqual(skipped["companies_skipped_by_guardrail"], 1)

            retried = asyncio.run(extract_contacts(
                CsvSheet(companies),
                CsvSheet(contacts),
                finder,
                config(),
                dry_run=False,
                limit=None,
                retry_failed=True,
            ))
            self.assertEqual(retried["companies_processed"], 1)
            self.assertEqual(retried["contacts_inserted"], 1)

    def test_cascade_skips_fallback_when_primary_meets_minimum(self) -> None:
        primary = FakeFinder([
            Contact("Ada Lovelace", "https://linkedin.com/in/ada", job_title="Founder", email="ada@example.com"),
            Contact("Grace Hopper", "https://linkedin.com/in/grace", job_title="CEO", email="grace@example.com"),
        ])
        fallback = FakeFinder([
            Contact("Alan Turing", "https://linkedin.com/in/alan", job_title="COO", source="instantly_database", status="needs_email"),
        ])
        finder = CascadeDecisionMakerFinder(primary, fallback, fallback_when_below=2)
        contacts = asyncio.run(finder.find({"company_domain": "acme.com"}, [], 3))
        self.assertEqual(len(contacts), 2)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)

    def test_lemlist_contact_without_email_requires_enrichment(self) -> None:
        contact = lemlist_contact({
            "full_name": "Noah Edis",
            "lead_linkedin_url": "https://linkedin.com/in/noah",
            "experiences": [{
                "order_in_profile": 1,
                "company_domain": "leftclick.ai",
                "title": "Co-Founder, COO",
            }],
        }, "leftclick.ai")
        self.assertIsNotNone(contact)
        assert contact is not None
        self.assertEqual(contact.email, "")
        self.assertEqual(contact.status, "needs_email")
        self.assertEqual(contact.email_status, "needs_email")

    def test_cascade_uses_instantly_fallback_below_minimum(self) -> None:
        primary = FakeFinder([
            Contact("Ada Lovelace", "https://linkedin.com/in/ada", job_title="Founder", email="ada@example.com", source="lemlist_database"),
        ])
        fallback = FakeFinder([
            Contact(
                "Grace Hopper",
                "https://linkedin.com/in/grace",
                job_title="COO",
                source="instantly_database",
                email_status="needs_email",
                status="needs_email",
            ),
        ])
        finder = CascadeDecisionMakerFinder(primary, fallback, fallback_when_below=2)
        contacts = asyncio.run(finder.find({"company_domain": "acme.com"}, [], 3))
        self.assertEqual(len(contacts), 2)
        self.assertEqual(fallback.calls, 1)
        self.assertEqual(contacts[1].status, "needs_email")

    def test_cascade_skips_fallback_when_lemlist_has_one_contact_with_threshold_one(self) -> None:
        primary = FakeFinder([
            Contact("Ada Lovelace", "https://linkedin.com/in/ada", job_title="Founder", email="ada@example.com"),
        ])
        fallback = FakeFinder([
            Contact("Grace Hopper", "https://linkedin.com/in/grace", job_title="CEO", email="grace@example.com"),
        ])
        finder = CascadeDecisionMakerFinder(primary, fallback, fallback_when_below=1)
        contacts = asyncio.run(finder.find({"company_domain": "acme.com"}, [], 3))
        self.assertEqual(len(contacts), 1)
        self.assertEqual(fallback.calls, 0)

    def test_cascade_uses_fallback_when_lemlist_has_zero_contacts_with_threshold_one(self) -> None:
        primary = FakeFinder([])
        fallback = FakeFinder([
            Contact("Grace Hopper", "https://linkedin.com/in/grace", job_title="CEO", email="grace@example.com"),
        ])
        finder = CascadeDecisionMakerFinder(primary, fallback, fallback_when_below=1)
        contacts = asyncio.run(finder.find({"company_domain": "acme.com"}, [], 3))
        self.assertEqual(len(contacts), 1)
        self.assertEqual(fallback.calls, 1)


def config() -> dict:
    return {
        "qualified_statuses": ["outreach_ready"],
        "max_contacts_per_company": 3,
        "decision_maker_titles": ["founder", "ceo"],
        "lemlist_campaign": "Pipeline gap detected",
    }


if __name__ == "__main__":
    unittest.main()
