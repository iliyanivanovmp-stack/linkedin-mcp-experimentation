from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
APOLLO_SKILL_ENV = Path.home() / ".codex" / "skills" / "scrape-leads-apollo" / ".env"

CONTACT_COLUMNS = [
    "status",
    "lemlist_campaign",
    "lemlist_campaign_id",
    "lemlist_lead_id",
    "plugged_at",
    "lemlist_error",
    "detected_at",
    "company_name",
    "company_domain",
    "company_website",
    "company_linkedin_url",
    "person_name",
    "first_name",
    "last_name",
    "person_linkedin_url",
    "job_title",
    "headline",
    "email",
    "source_url",
    "evidence",
    "gap_reason",
    "outreach_reason",
    "opener",
    "icebreaker",
    "hiring_job_title",
    "hiring_job_url",
    "hiring_role_family",
    "hiring_intent_score",
    "hiring_evidence_terms",
    "hiring_offer_angle",
    "hiring_outreach_reason",
    "hiring_opener",
    "hiring_automation_opportunity",
    "compensation_text",
    "hiring_company_key",
    "contact_source",
    "email_status",
    "lemlist_enrichment_id",
    "email_enriched_at",
]

COMPANY_GUARDRAIL_COLUMNS = [
    "contacts_status",
    "contacts_generated_at",
    "contacts_found_count",
    "contacts_ready_count",
    "contacts_needs_email_count",
    "contacts_duplicates_skipped",
    "contacts_error",
    "contacts_attempts",
]

COMPANY_CONTACT_DONE_STATUSES = {"contacts_generated"}


COMPANY_ALIASES = {
    "company_name": ["company_name", "company", "Company", "domain"],
    "company_domain": ["company_domain", "domain", "Domain"],
    "company_website": ["company_website", "website_url", "entry_url", "website", "Website", "source_url"],
    "company_linkedin_url": ["company_linkedin_url", "linkedin_company_url"],
    "source_url": ["source_url", "job_url", "entry_url", "website_url", "website", "Website"],
    "evidence": ["evidence", "outreach_reason", "evidence_terms", "job_description"],
    "gap_reason": ["gap_reason", "detected_gap", "gap", "problem_detected", "evidence"],
    "outreach_reason": ["outreach_reason", "reason", "gap_reason", "evidence", "broken_funnel_pages"],
    "opener": ["opener", "email_opener", "opening_line", "outreach_reason"],
    "solution_angle": ["solution_angle", "recommended_solution", "solution", "how_solved", "outreach_reason"],
    "icebreaker": ["icebreaker", "personalization", "opener", "outreach_reason"],
    "technologies": ["technologies", "selected_outreach_tools", "matched_technologies"],
    "selected_outreach_tools": ["selected_outreach_tools", "technologies", "matched_technologies"],
    "automation_opportunity_1": ["automation_opportunity_1", "automation_example_1"],
    "automation_opportunity_2": ["automation_opportunity_2", "automation_example_2"],
    "automation_opportunity_3": ["automation_opportunity_3", "automation_example_3"],
    "outreach_angle": ["outreach_angle", "solution_angle", "outreach_reason"],
    "hiring_job_title": ["hiring_job_title", "job_title"],
    "hiring_job_url": ["hiring_job_url", "job_url", "source_url"],
    "hiring_role_family": ["hiring_role_family", "role_family"],
    "hiring_intent_score": ["hiring_intent_score", "intent_score"],
    "hiring_evidence_terms": ["hiring_evidence_terms", "evidence_terms"],
    "hiring_offer_angle": ["hiring_offer_angle", "offer_angle"],
    "hiring_outreach_reason": ["hiring_outreach_reason", "outreach_reason"],
    "hiring_opener": ["hiring_opener", "opener", "icebreaker"],
    "hiring_automation_opportunity": ["hiring_automation_opportunity"],
    "compensation_text": ["compensation_text"],
    "status": ["opportunity_status", "status", "audit_status"],
    "signal_found": ["signal_found"],
    "do_not_sequence": ["do_not_sequence", "do_not_contact"],
}


@dataclass
class SheetRow:
    number: int
    data: dict[str, str]


@dataclass
class Contact:
    person_name: str
    person_linkedin_url: str
    headline: str = ""
    job_title: str = ""
    email: str = ""
    source: str = ""
    email_status: str = ""
    status: str = ""


class Sheet(Protocol):
    headers: list[str]

    def rows(self) -> list[SheetRow]:
        ...

    def ensure_columns(self, columns: list[str]) -> None:
        ...

    def append_rows(self, rows: list[dict[str, str]]) -> None:
        ...

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        ...


class CsvSheet:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.headers: list[str] = []
        self._rows: list[dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.headers = []
            self._rows = []
            return
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            self.headers = list(reader.fieldnames or [])
            self._rows = [
                {header: row.get(header, "") for header in self.headers}
                for row in reader
            ]

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(
                {header: row.get(header, "") for header in self.headers}
                for row in self._rows
            )

    def rows(self) -> list[SheetRow]:
        return [
            SheetRow(number=index + 2, data=dict(row))
            for index, row in enumerate(self._rows)
        ]

    def ensure_columns(self, columns: list[str]) -> None:
        changed = False
        if not self.headers:
            self.headers = list(columns)
            changed = True
        for column in columns:
            if column not in self.headers:
                self.headers.append(column)
                changed = True
        if changed:
            for row in self._rows:
                for column in self.headers:
                    row.setdefault(column, "")
            self._write()

    def append_rows(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        self.ensure_columns(CONTACT_COLUMNS)
        for row in rows:
            self._rows.append({header: str(row.get(header, "")) for header in self.headers})
        self._write()

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        index = row_number - 2
        if index < 0 or index >= len(self._rows):
            raise IndexError(f"CSV row {row_number} is out of range")
        for column in updates:
            if column not in self.headers:
                self.headers.append(column)
        self._rows[index].update(updates)
        self._write()


class MemorySheet:
    def __init__(self, headers: list[str] | None = None, rows: list[dict[str, str]] | None = None) -> None:
        self.headers = list(headers or [])
        self._rows = list(rows or [])

    def rows(self) -> list[SheetRow]:
        return [
            SheetRow(number=index + 2, data=dict(row))
            for index, row in enumerate(self._rows)
        ]

    def ensure_columns(self, columns: list[str]) -> None:
        for column in columns:
            if column not in self.headers:
                self.headers.append(column)
        for row in self._rows:
            for column in self.headers:
                row.setdefault(column, "")

    def append_rows(self, rows: list[dict[str, str]]) -> None:
        self.ensure_columns(CONTACT_COLUMNS)
        self._rows.extend(rows)

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        index = row_number - 2
        if index < 0 or index >= len(self._rows):
            raise IndexError(f"memory row {row_number} is out of range")
        self._rows[index].update(updates)


class GoogleWorkbook:
    def __init__(self, spreadsheet_id: str) -> None:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:
            raise RuntimeError(
                "Google Sheets sources require gspread and google-auth"
            ) from exc

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if service_json:
            credentials = Credentials.from_service_account_info(
                json.loads(service_json),
                scopes=scopes,
            )
            client = gspread.authorize(credentials)
        else:
            credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if not credentials_path:
                raise RuntimeError(
                    "Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON"
                )
            client = gspread.service_account(filename=credentials_path)
        self.spreadsheet = client.open_by_key(spreadsheet_id)

    def worksheet(
        self,
        title: str,
        headers: list[str] | None = None,
        create_if_missing: bool = True,
    ) -> "GoogleSheet":
        try:
            worksheet = self.spreadsheet.worksheet(title)
        except Exception:
            if not create_if_missing:
                raise RuntimeError(f"Worksheet not found: {title}")
            worksheet = self.spreadsheet.add_worksheet(
                title=title,
                rows=1000,
                cols=max(26, len(headers or [])),
            )
            if headers:
                worksheet.update(range_name="A1", values=[headers])
        return GoogleSheet(worksheet)


class GoogleSheet:
    def __init__(self, worksheet: Any) -> None:
        self.worksheet = worksheet
        self.headers = list(self.worksheet.row_values(1))

    def rows(self) -> list[SheetRow]:
        values = self.worksheet.get_all_values()
        if not values:
            return []
        self.headers = list(values[0])
        rows = []
        for index, values_row in enumerate(values[1:], start=2):
            rows.append(SheetRow(
                number=index,
                data={
                    header: values_row[column_index] if column_index < len(values_row) else ""
                    for column_index, header in enumerate(self.headers)
                },
            ))
        return rows

    def ensure_columns(self, columns: list[str]) -> None:
        missing = [column for column in columns if column not in self.headers]
        if not missing:
            return
        start = len(self.headers) + 1
        self.headers.extend(missing)
        current_cols = int(getattr(self.worksheet, "col_count", 0) or 0)
        if current_cols and len(self.headers) > current_cols:
            self.worksheet.add_cols(len(self.headers) - current_cols)
        self.worksheet.update(
            range_name=f"{column_letter(start)}1:{column_letter(len(self.headers))}1",
            values=[missing],
        )

    def append_rows(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        self.ensure_columns(CONTACT_COLUMNS)
        values = [
            [str(row.get(header, "")) for header in self.headers]
            for row in rows
        ]
        self.worksheet.append_rows(values, value_input_option="RAW")

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        cells = []
        for column, value in updates.items():
            if column not in self.headers:
                self.ensure_columns([column])
            cells.append({
                "range": f"{column_letter(self.headers.index(column) + 1)}{row_number}",
                "values": [[value]],
            })
        if cells:
            self.worksheet.batch_update(cells)


class DecisionMakerFinder(Protocol):
    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        ...


class NoContactProvider:
    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        raise RuntimeError(
            "No non-LinkedIn contact provider configured. "
            "Pass --static-contacts-csv for a safe test, or configure Lemlist/Instantly providers."
        )


class StaticDecisionMakerFinder:
    def __init__(self, contacts_by_domain: dict[str, list[dict[str, str]]]) -> None:
        self.contacts_by_domain = contacts_by_domain

    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        domain = company.get("company_domain", "").casefold()
        return [
            Contact(
                person_name=row.get("person_name", ""),
                person_linkedin_url=row.get("person_linkedin_url", ""),
                headline=row.get("headline", ""),
                job_title=row.get("job_title", ""),
                email=row.get("email", ""),
                source=row.get("contact_source", "static"),
                email_status=row.get("email_status", ""),
                status=row.get("status", ""),
            )
            for row in self.contacts_by_domain.get(domain, [])[:limit]
        ]


class LemlistDecisionMakerFinder:
    def __init__(self, api_key: str, page_size: int = 100) -> None:
        self.api_key = api_key
        self.page_size = page_size

    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        domain = company.get("company_domain", "").strip().casefold()
        if not domain:
            return []
        data = await asyncio.to_thread(self._search, domain)
        contacts = [
            contact
            for lead in data.get("results", [])
            if (contact := lemlist_contact(lead, domain))
            and matches_decision_maker_title(contact.job_title, titles)
        ]
        return rank_contacts(dedupe_contacts(contacts))[:limit]

    def _search(self, domain: str) -> dict[str, Any]:
        payload = {
            "mode": "people",
            "page": 1,
            "size": self.page_size,
            "filters": [
                {"filterId": "currentCompanyWebsiteUrl", "in": [domain], "out": []},
            ],
        }
        auth = base64.b64encode(f":{self.api_key}".encode()).decode()
        request = urllib.request.Request(
            "https://api.lemlist.com/api/database/people",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
                "User-Agent": "linkedin-mcp-experimentation/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))


class InstantlyDecisionMakerFinder:
    def __init__(self, api_key: str, page_size: int = 25) -> None:
        self.api_key = api_key
        self.page_size = page_size

    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        domain = company.get("company_domain", "").strip().casefold()
        if not domain:
            return []
        search_limit = max(limit * 10, self.page_size)
        leads = await asyncio.to_thread(self._search, domain, search_limit)
        contacts = [
            contact
            for lead in leads
            if (contact := instantly_contact(lead))
            and matches_decision_maker_title(contact.job_title, titles)
        ]
        return rank_contacts(dedupe_contacts(contacts))[:limit]

    def _search(self, domain: str, limit: int) -> list[dict[str, Any]]:
        leads: list[dict[str, Any]] = []
        page = 0
        while len(leads) < limit:
            payload = {
                "search_filters": {"domains": [domain]},
                "page": page,
                "pageSize": self.page_size,
            }
            request = urllib.request.Request(
                "https://api.instantly.ai/api/v2/supersearch-enrichment/preview-leads-from-supersearch",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "linkedin-mcp-experimentation/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8", "ignore"))
            batch = data.get("leads", [])
            if not batch:
                break
            leads.extend(batch)
            if len(batch) < self.page_size:
                break
            page += 1
        return leads[:limit]


class ApolloDecisionMakerFinder:
    def __init__(self, api_key: str, page_size: int = 25) -> None:
        self.api_key = api_key
        self.page_size = page_size

    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        domain = company.get("company_domain", "").strip().casefold()
        if not domain:
            return []
        people = await asyncio.to_thread(self._search, domain, titles, max(limit * 3, self.page_size))
        contacts = []
        for person in people[: max(limit * 3, limit)]:
            apollo_id = str(person.get("id", "") or "").strip()
            enriched = await asyncio.to_thread(self._match_person, apollo_id) if apollo_id else person
            if (
                (contact := apollo_contact(enriched or person, domain))
                and matches_decision_maker_title(contact.job_title, titles)
            ):
                contacts.append(contact)
            if len(contacts) >= limit:
                break
        return rank_contacts(dedupe_contacts(contacts))[:limit]

    def _search(self, domain: str, titles: list[str], limit: int) -> list[dict[str, Any]]:
        payload = {
            "page": 1,
            "per_page": min(max(limit, 1), 100),
            "q_organization_domains_list": [domain],
            "person_titles": titles,
            "person_seniorities": ["owner", "founder", "c_suite", "vp", "head", "director"],
            "include_similar_titles": True,
        }
        data = self._post("mixed_people/api_search", payload)
        return list(data.get("people", []))

    def _match_person(self, apollo_id: str) -> dict[str, Any]:
        data = self._post("people/match", {
            "id": apollo_id,
            "reveal_personal_emails": False,
            "reveal_phone_number": False,
        })
        return dict(data.get("person") or {})

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"https://api.apollo.io/api/v1/{endpoint}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": "linkedin-mcp-experimentation/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8", "ignore"))
        if data.get("error"):
            raise RuntimeError(json.dumps(data)[:1000])
        return data


class CascadeDecisionMakerFinder:
    def __init__(
        self,
        primary: DecisionMakerFinder,
        fallback: DecisionMakerFinder | None,
        fallback_when_below: int,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.fallback_when_below = fallback_when_below

    async def find(self, company: dict[str, str], titles: list[str], limit: int) -> list[Contact]:
        contacts = await self.primary.find(company, titles, limit)
        contacts = dedupe_contacts(contacts)
        if self.fallback and len(contacts) < min(limit, self.fallback_when_below):
            fallback_contacts = await self.fallback.find(company, titles, limit)
            contacts = dedupe_contacts([*contacts, *fallback_contacts])
        return rank_contacts(contacts)[:limit]


def column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def first_value(row: dict[str, str], aliases: list[str]) -> str:
    for key in aliases:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    lower = {key.casefold(): value for key, value in row.items()}
    for key in aliases:
        value = str(lower.get(key.casefold(), "") or "").strip()
        if value:
            return value
    return ""


def truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y", "x"}


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def apollo_api_key(env_name: str = "APOLLO_API_KEY") -> str:
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    if APOLLO_SKILL_ENV.exists():
        for line in APOLLO_SKILL_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == env_name:
                return value.strip().strip('"').strip("'")
    return ""


def qualified_company(row: dict[str, str], qualified_statuses: set[str]) -> bool:
    if truthy(first_value(row, COMPANY_ALIASES["do_not_sequence"])):
        return False
    status = first_value(row, COMPANY_ALIASES["status"]).casefold()
    if status in qualified_statuses:
        return True
    return truthy(first_value(row, COMPANY_ALIASES["signal_found"]))


def company_payload(row: dict[str, str]) -> dict[str, str]:
    website = first_value(row, COMPANY_ALIASES["company_website"])
    domain = first_value(row, COMPANY_ALIASES["company_domain"]) or domain_from_url(website)
    company_name = first_value(row, COMPANY_ALIASES["company_name"])
    if company_name == domain:
        company_name = domain.split(".")[0].replace("-", " ").title()
    return {
        "company_name": company_name,
        "company_domain": domain,
        "company_website": website or (f"https://{domain}" if domain else ""),
        "company_linkedin_url": first_value(row, COMPANY_ALIASES["company_linkedin_url"]),
        "source_url": first_value(row, COMPANY_ALIASES["source_url"]) or (f"https://{domain}" if domain else ""),
        "evidence": first_value(row, COMPANY_ALIASES["evidence"]),
        "gap_reason": first_value(row, COMPANY_ALIASES["gap_reason"]),
        "outreach_reason": first_value(row, COMPANY_ALIASES["outreach_reason"]),
        "opener": first_value(row, COMPANY_ALIASES["opener"]),
        "solution_angle": first_value(row, COMPANY_ALIASES["solution_angle"]),
        "icebreaker": first_value(row, COMPANY_ALIASES["icebreaker"]),
        "technologies": first_value(row, COMPANY_ALIASES["technologies"]),
        "selected_outreach_tools": first_value(row, COMPANY_ALIASES["selected_outreach_tools"]),
        "automation_opportunity_1": first_value(row, COMPANY_ALIASES["automation_opportunity_1"]),
        "automation_opportunity_2": first_value(row, COMPANY_ALIASES["automation_opportunity_2"]),
        "automation_opportunity_3": first_value(row, COMPANY_ALIASES["automation_opportunity_3"]),
        "outreach_angle": first_value(row, COMPANY_ALIASES["outreach_angle"]),
        "hiring_job_title": first_value(row, COMPANY_ALIASES["hiring_job_title"]),
        "hiring_job_url": first_value(row, COMPANY_ALIASES["hiring_job_url"]),
        "hiring_role_family": first_value(row, COMPANY_ALIASES["hiring_role_family"]),
        "hiring_intent_score": first_value(row, COMPANY_ALIASES["hiring_intent_score"]),
        "hiring_evidence_terms": first_value(row, COMPANY_ALIASES["hiring_evidence_terms"]),
        "hiring_offer_angle": first_value(row, COMPANY_ALIASES["hiring_offer_angle"]),
        "hiring_outreach_reason": first_value(row, COMPANY_ALIASES["hiring_outreach_reason"]),
        "hiring_opener": first_value(row, COMPANY_ALIASES["hiring_opener"]),
        "hiring_automation_opportunity": first_value(row, COMPANY_ALIASES["hiring_automation_opportunity"]),
        "compensation_text": first_value(row, COMPANY_ALIASES["compensation_text"]),
    }


def decision_maker_titles_for_company(company: dict[str, str], config: dict[str, Any]) -> list[str]:
    family = str(company.get("hiring_role_family", "") or "").strip()
    by_family = config.get("decision_maker_titles_by_role_family", {})
    configured = by_family.get(family) if isinstance(by_family, dict) else None
    titles = configured or config.get("decision_maker_titles", [])
    return [str(title) for title in titles if str(title).strip()]


def company_key(company: dict[str, str]) -> str:
    if company.get("company_domain"):
        return f"domain:{company['company_domain'].casefold()}"
    if company.get("company_website"):
        return f"domain:{domain_from_url(company['company_website'])}"
    return f"name:{company.get('company_name', '').strip().casefold()}"


def should_skip_for_guardrail(
    row: dict[str, str],
    retry_failed: bool,
    force: bool,
    retry_config: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> bool:
    if force:
        return False
    status = str(row.get("contacts_status", "") or "").strip().casefold()
    if status in COMPANY_CONTACT_DONE_STATUSES:
        return True
    if status not in {"contacts_failed", "no_new_contacts"}:
        return False
    config = retry_config or {}
    attempts = int(row.get("contacts_attempts", "0") or 0)
    if attempts >= int(config.get("max_attempts", 3)):
        return True
    if status == "contacts_failed" and not retry_failed:
        return True
    generated_at = str(row.get("contacts_generated_at", "") or "").strip()
    if generated_at:
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            hours = int(config.get("retry_after_hours" if status == "contacts_failed" else "retry_empty_after_hours", 24 if status == "contacts_failed" else 72))
            if parsed + timedelta(hours=hours) > (now or datetime.now(timezone.utc)):
                return True
        except ValueError:
            pass
    return False


def company_guardrail_updates(
    status: str,
    generated_at: str,
    contacts_found: int = 0,
    ready_count: int = 0,
    needs_email_count: int = 0,
    duplicates_skipped: int = 0,
    error: str = "",
    attempts: int = 1,
) -> dict[str, str]:
    return {
        "contacts_status": status,
        "contacts_generated_at": generated_at,
        "contacts_found_count": str(contacts_found),
        "contacts_ready_count": str(ready_count),
        "contacts_needs_email_count": str(needs_email_count),
        "contacts_duplicates_skipped": str(duplicates_skipped),
        "contacts_error": error,
        "contacts_attempts": str(attempts),
    }


def contact_key(row: dict[str, str]) -> str:
    linkedin = normalize_url(row.get("person_linkedin_url", ""))
    if linkedin:
        return f"linkedin:{linkedin}"
    email = row.get("email", "").strip().casefold()
    if email:
        return f"email:{email}"
    return ""


def contact_identity(contact: Contact) -> str:
    linkedin = normalize_url(contact.person_linkedin_url)
    if linkedin:
        return f"linkedin:{linkedin}"
    if contact.email:
        return f"email:{contact.email.strip().casefold()}"
    if contact.person_name and contact.job_title:
        return f"name:{contact.person_name.strip().casefold()}|{contact.job_title.strip().casefold()}"
    return ""


def dedupe_contacts(contacts: list[Contact]) -> list[Contact]:
    seen = set()
    output = []
    for contact in contacts:
        key = contact_identity(contact)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(contact)
    return output


def title_score(title: str) -> tuple[int, int, int]:
    text = title.casefold()
    if re.search(r"\b(founder|co-founder|co founder|owner|ceo|chief executive|president|managing director)\b", text):
        tier = 0
    elif re.search(r"\b(coo|cfo|cto|cmo|cro|cpo|chief operating|chief financial|chief technology|chief marketing|chief revenue|chief product)\b", text):
        tier = 1
    elif re.search(r"\b(head of|director|vp|vice president|team lead|lead)\b", text):
        tier = 2
    elif re.search(r"\b(operations|growth|revenue|sales|marketing|business development|affiliate|partnerships).{0,30}manager\b", text):
        tier = 3
    elif "manager" in text:
        tier = 4
    else:
        tier = 9
    penalty = 1 if re.search(r"\b(junior|assistant|support|specialist|designer|developer|engineer|qa|accountant|analyst)\b", text) else 0
    return tier, penalty, -len(title)


def canonical_title(value: str) -> str:
    text = value.casefold().replace("&", " and ")
    replacements = {
        r"\bco[\s-]?founder\b": "cofounder",
        r"\bchief executive officer\b": "ceo",
        r"\bchief revenue officer\b": "cro",
        r"\bvice president\b": "vp",
        r"\brevenue operations\b": "revops",
        r"\brev ops\b": "revops",
        r"\bhead of\b": "head",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def matches_decision_maker_title(title: str, configured_titles: list[str]) -> bool:
    """Require an actual configured decision-maker title, irrespective of word order."""
    if re.search(r"\b(intern|internship|student|trainee)\b", title, flags=re.I):
        return False
    if re.search(r"\bfounder['’]s\b", title, flags=re.I):
        return False
    candidate = set(canonical_title(title).split())
    if not candidate:
        return False
    ignored = {"of", "the", "and"}
    for configured in configured_titles:
        target = set(canonical_title(configured).split()) - ignored
        if target and target.issubset(candidate):
            return True
    return False


def rank_contacts(contacts: list[Contact]) -> list[Contact]:
    return sorted(
        contacts,
        key=lambda contact: (
            title_score(contact.job_title),
            0 if contact.email else 1,
            contact.person_name.casefold(),
        ),
    )


def lemlist_current_experience(lead: dict[str, Any]) -> dict[str, Any]:
    experiences = lead.get("experiences", [])
    if isinstance(experiences, list):
        for experience in experiences:
            if experience.get("order_in_profile") == 1:
                return experience
        if experiences:
            return experiences[0]
    return {}


def lemlist_contact(lead: dict[str, Any], domain: str) -> Contact | None:
    experience = lemlist_current_experience(lead)
    company_domain = str(experience.get("company_domain", "") or "").strip().casefold()
    if normalize_domain(company_domain) != normalize_domain(domain):
        return None
    name = str(lead.get("full_name", "") or "").strip()
    linkedin = str(lead.get("lead_linkedin_url", "") or "").strip()
    email = str(lead.get("potential_email", "") or "").strip()
    title = str(experience.get("title", "") or "").strip()
    if not (name or linkedin or email):
        return None
    return Contact(
        person_name=name,
        person_linkedin_url=linkedin,
        headline=title,
        job_title=title,
        email=email,
        source="lemlist_database",
        email_status="provided" if email else "needs_email",
        status="" if email else "needs_email",
    )


def instantly_contact(lead: dict[str, Any]) -> Contact | None:
    name = str(lead.get("fullName") or f"{lead.get('firstName', '')} {lead.get('lastName', '')}").strip()
    linkedin = str(lead.get("linkedIn", "") or "").strip()
    title = str(lead.get("jobTitle", "") or "").strip()
    if not (name or linkedin):
        return None
    return Contact(
        person_name=name,
        person_linkedin_url=linkedin,
        headline=title,
        job_title=title,
        email="",
        source="instantly_database",
        email_status="needs_email",
        status="needs_email",
    )


def apollo_contact(person: dict[str, Any], domain: str) -> Contact | None:
    organization = person.get("organization") or person.get("account") or {}
    organization_domain = str(
        organization.get("primary_domain")
        or organization.get("website_url")
        or organization.get("domain")
        or ""
    )
    if organization_domain and normalize_domain(organization_domain) != normalize_domain(domain):
        return None
    name = str(
        person.get("name")
        or f"{person.get('first_name', '')} {person.get('last_name', '')}"
    ).strip()
    linkedin = str(person.get("linkedin_url", "") or "").strip()
    title = str(person.get("title", "") or "").strip()
    email = str(person.get("email", "") or "").strip()
    if not (name or linkedin or email):
        return None
    return Contact(
        person_name=name,
        person_linkedin_url=linkedin,
        headline=title,
        job_title=title,
        email=email,
        source="apollo",
        email_status=str(person.get("email_status", "") or ("provided" if email else "needs_email")),
        status="" if email else "needs_email",
    )


def contact_row(
    company: dict[str, str],
    contact: Contact,
    campaign_name: str,
    detected_at: str,
) -> dict[str, str]:
    first_name, last_name = split_name(contact.person_name)
    reason = company.get("outreach_reason") or company.get("evidence")
    return {
        "status": contact.status,
        "lemlist_campaign": campaign_name,
        "detected_at": detected_at,
        "company_name": company.get("company_name", ""),
        "company_domain": company.get("company_domain", ""),
        "company_website": company.get("company_website", ""),
        "company_linkedin_url": company.get("company_linkedin_url", ""),
        "person_name": contact.person_name,
        "first_name": first_name,
        "last_name": last_name,
        "person_linkedin_url": normalize_url(contact.person_linkedin_url),
        "job_title": contact.job_title,
        "headline": contact.headline,
        "email": contact.email,
        "source_url": company.get("source_url", ""),
        "evidence": company.get("evidence", ""),
        "gap_reason": company.get("gap_reason", "") or company.get("evidence", ""),
        "outreach_reason": company.get("outreach_reason", ""),
        "opener": company.get("opener", "") or company.get("outreach_reason", ""),
        "hiring_job_title": company.get("hiring_job_title", ""),
        "hiring_job_url": company.get("hiring_job_url", ""),
        "hiring_role_family": company.get("hiring_role_family", ""),
        "hiring_intent_score": company.get("hiring_intent_score", ""),
        "hiring_evidence_terms": company.get("hiring_evidence_terms", ""),
        "hiring_offer_angle": company.get("hiring_offer_angle", ""),
        "hiring_outreach_reason": company.get("hiring_outreach_reason", ""),
        "hiring_opener": company.get("hiring_opener", ""),
        "hiring_automation_opportunity": company.get("hiring_automation_opportunity", ""),
        "compensation_text": company.get("compensation_text", ""),
        "icebreaker": company.get("icebreaker", "") or company.get("hiring_opener", "") or (
            f"Noticed {company.get('company_name', 'your company')} is hiring a "
            f"{company.get('hiring_job_title', 'pipeline role')}."
        ).strip(),
        "hiring_company_key": company_key(company),
        "contact_source": contact.source,
        "email_status": contact.email_status,
    }


def clean_person_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s+-\s+LinkedIn$", "", value, flags=re.I)
    return value


def split_name(value: str) -> tuple[str, str]:
    parts = value.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("/"):
        value = f"https://www.linkedin.com{value}"
    parsed = urllib.parse.urlparse(value)
    if not parsed.netloc:
        return value.rstrip("/").casefold()
    host = parsed.netloc.casefold().removeprefix("www.")
    return f"{parsed.scheme or 'https'}://{host}{parsed.path.rstrip('/')}"


def domain_from_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.casefold().removeprefix("www.")


def normalize_domain(value: str) -> str:
    value = value.strip().casefold()
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.casefold().removeprefix("www.")


def load_static_contacts(path: Path) -> dict[str, list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    contacts: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        domain = row.get("company_domain", "").strip().casefold()
        contacts.setdefault(domain, []).append(row)
    return contacts


async def extract_contacts(
    companies_sheet: Sheet,
    contacts_sheet: Sheet,
    finder: DecisionMakerFinder,
    config: dict[str, Any],
    dry_run: bool,
    limit: int | None,
    retry_failed: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        companies_sheet.ensure_columns(COMPANY_GUARDRAIL_COLUMNS)
        contacts_sheet.ensure_columns(CONTACT_COLUMNS)
    existing_contact_rows = contacts_sheet.rows()
    existing_contact_keys = {
        contact_key(row.data)
        for row in existing_contact_rows
        if contact_key(row.data)
    }
    qualified_statuses = {
        str(status).casefold()
        for status in config.get("qualified_statuses", [])
    }
    max_contacts = int(config.get("max_contacts_per_company", 3))
    retry_config = config.get("contact_retry", {})
    campaign_name = str(config["lemlist_campaign"])
    detected_at = datetime.now(timezone.utc).isoformat()
    daily_contact_limit = int(config.get("daily_contact_limit", 0) or 0)
    contact_timezone = str(config.get("timezone", "Europe/Sofia"))
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(contact_timezone)).date()
    contacts_created_today = sum(
        1
        for row in existing_contact_rows
        if (value := str(row.data.get("detected_at", "") or "").strip())
        and _date_in_timezone(value, contact_timezone) == today
    )
    daily_remaining = (
        max(0, daily_contact_limit - contacts_created_today)
        if daily_contact_limit
        else None
    )
    summary = {
        "dry_run": dry_run,
        "companies_seen": 0,
        "companies_qualified": 0,
        "companies_skipped_by_guardrail": 0,
        "companies_processed": 0,
        "companies_marked_generated": 0,
        "companies_marked_no_new_contacts": 0,
        "contacts_found": 0,
        "contacts_inserted": 0,
        "contacts_ready_for_lemlist": 0,
        "contacts_needing_email": 0,
        "duplicates_skipped": 0,
        "failures": 0,
        "daily_contact_limit": daily_contact_limit or None,
        "contacts_created_today": contacts_created_today,
        "daily_remaining_before_run": daily_remaining,
    }
    rows_to_append: list[dict[str, str]] = []
    pending_company_updates: list[tuple[int, dict[str, str]]] = []

    for source_row in companies_sheet.rows():
        if daily_remaining is not None and len(rows_to_append) >= daily_remaining:
            break
        if limit is not None and summary["companies_processed"] >= limit:
            break
        summary["companies_seen"] += 1
        if not qualified_company(source_row.data, qualified_statuses):
            continue
        summary["companies_qualified"] += 1
        if should_skip_for_guardrail(source_row.data, retry_failed=retry_failed, force=force, retry_config=retry_config):
            summary["companies_skipped_by_guardrail"] += 1
            continue
        company = company_payload(source_row.data)
        titles = decision_maker_titles_for_company(company, config)
        attempts = int(source_row.data.get("contacts_attempts", "0") or 0) + 1
        if not (company["company_name"] or company["company_domain"]):
            summary["failures"] += 1
            if not dry_run:
                companies_sheet.update_row(source_row.number, company_guardrail_updates(
                    "contacts_failed",
                    detected_at,
                    error="Missing company name and company domain",
                    attempts=attempts,
                ))
            continue
        try:
            contacts = await finder.find(company, titles, max_contacts)
        except Exception as exc:
            summary["failures"] += 1
            if not dry_run:
                companies_sheet.update_row(source_row.number, company_guardrail_updates(
                    "contacts_failed",
                    detected_at,
                    error=str(exc)[:500],
                    attempts=attempts,
                ))
            continue
        summary["companies_processed"] += 1
        summary["contacts_found"] += len(contacts)
        company_ready_count = 0
        company_needs_email_count = 0
        company_duplicates_skipped = 0
        company_rows_to_append = []
        candidate_contacts = contacts[:max_contacts]
        cap_truncated = False
        for contact in candidate_contacts:
            if daily_remaining is not None and len(rows_to_append) >= daily_remaining:
                cap_truncated = True
                break
            row = contact_row(company, contact, campaign_name, detected_at)
            key = contact_key(row)
            if not key or key in existing_contact_keys:
                summary["duplicates_skipped"] += 1
                company_duplicates_skipped += 1
                continue
            existing_contact_keys.add(key)
            rows_to_append.append(row)
            company_rows_to_append.append(row)
            if row.get("status"):
                summary["contacts_needing_email"] += 1
                company_needs_email_count += 1
            else:
                summary["contacts_ready_for_lemlist"] += 1
                company_ready_count += 1

        if company_rows_to_append:
            summary["companies_marked_generated"] += 1
            pending_company_updates.append((
                source_row.number,
                company_guardrail_updates(
                    "contacts_partial" if cap_truncated else "contacts_generated",
                    detected_at,
                    contacts_found=len(contacts),
                    ready_count=company_ready_count,
                    needs_email_count=company_needs_email_count,
                    duplicates_skipped=company_duplicates_skipped,
                    attempts=attempts,
                ),
            ))
        elif not cap_truncated:
            summary["companies_marked_no_new_contacts"] += 1
            if not dry_run:
                companies_sheet.update_row(source_row.number, company_guardrail_updates(
                    "no_new_contacts",
                    detected_at,
                    contacts_found=len(contacts),
                    duplicates_skipped=company_duplicates_skipped,
                    attempts=attempts,
                ))

    if rows_to_append and not dry_run:
        contacts_sheet.append_rows(rows_to_append)
        for row_number, updates in pending_company_updates:
            companies_sheet.update_row(row_number, updates)
    summary["contacts_inserted"] = len(rows_to_append)
    return summary


def _date_in_timezone(value: str, timezone_name: str):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(timezone_name)).date()
    except (ValueError, TypeError, KeyError):
        return None


def open_sheets(
    config: dict[str, Any],
    companies_csv: Path | None,
    contacts_csv: Path | None,
    dry_run: bool,
) -> tuple[Sheet, Sheet]:
    if companies_csv or contacts_csv:
        if not companies_csv or not contacts_csv:
            raise ValueError("Both --companies-csv and --contacts-csv are required for CSV mode")
        companies_sheet = CsvSheet(companies_csv)
        contacts_sheet = CsvSheet(contacts_csv)
        if not dry_run:
            contacts_sheet.ensure_columns(CONTACT_COLUMNS)
        return companies_sheet, contacts_sheet
    workbook = GoogleWorkbook(str(config["spreadsheet_id"]))
    companies = workbook.worksheet(str(config["companies_worksheet"]))
    try:
        contacts = workbook.worksheet(
            str(config["contacts_worksheet"]),
            CONTACT_COLUMNS,
            create_if_missing=not dry_run,
        )
    except RuntimeError:
        if not dry_run:
            raise
        contacts = MemorySheet(CONTACT_COLUMNS)
    return companies, contacts


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def build_finder(config: dict[str, Any], static_contacts_csv: Path | None) -> DecisionMakerFinder:
    if static_contacts_csv:
        return StaticDecisionMakerFinder(load_static_contacts(static_contacts_csv))

    provider_config = config.get("contact_providers", {})
    primary_name = str(provider_config.get("primary", "")).strip().casefold()
    fallback_name = str(provider_config.get("fallback", "")).strip().casefold()
    fallback_when_below = int(provider_config.get("fallback_when_below_contacts", 2))

    if primary_name != "lemlist":
        return NoContactProvider()

    lemlist_key = os.environ.get(str(provider_config.get("lemlist_api_key_env", "LEMLIST_API_KEY")), "").strip()
    if not lemlist_key:
        raise RuntimeError("Set LEMLIST_API_KEY to use the Lemlist contact provider")

    primary = LemlistDecisionMakerFinder(lemlist_key)
    fallback: DecisionMakerFinder | None = None

    if fallback_name == "instantly":
        instantly_key = os.environ.get(str(provider_config.get("instantly_api_key_env", "INSTANTLY_API_KEY")), "").strip()
        if not instantly_key:
            raise RuntimeError("Set INSTANTLY_API_KEY to use the configured Instantly fallback provider")
        fallback = InstantlyDecisionMakerFinder(instantly_key)
    elif fallback_name == "apollo":
        apollo_key = apollo_api_key(str(provider_config.get("apollo_api_key_env", "APOLLO_API_KEY")))
        if not apollo_key:
            raise RuntimeError("Set APOLLO_API_KEY to use the configured Apollo fallback provider")
        fallback = ApolloDecisionMakerFinder(apollo_key)
    elif fallback_name:
        raise RuntimeError(f"Unsupported fallback contact provider: {fallback_name}")

    return CascadeDecisionMakerFinder(
        primary=primary,
        fallback=fallback,
        fallback_when_below=fallback_when_below,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--companies-csv", type=Path)
    parser.add_argument("--contacts-csv", type=Path)
    parser.add_argument("--static-contacts-csv", type=Path)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    try:
        load_env_file()
        companies_sheet, contacts_sheet = open_sheets(
            config,
            args.companies_csv,
            args.contacts_csv,
            args.dry_run,
        )
        finder = build_finder(config, args.static_contacts_csv)
        result = asyncio.run(extract_contacts(
            companies_sheet,
            contacts_sheet,
            finder,
            config,
            args.dry_run,
            args.limit,
            retry_failed=args.retry_failed,
            force=args.force,
        ))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
