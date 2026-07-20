from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extract_contacts import (
    CONTACT_COLUMNS,
    CsvSheet,
    GoogleWorkbook,
    Sheet,
    domain_from_url,
    load_config,
    load_env_file,
)


DEFAULT_CONFIG = Path(__file__).with_name("contact_extraction_config.json")
APOLLO_SKILL_ENV = Path.home() / ".codex" / "skills" / "scrape-leads-apollo" / ".env"
ENRICHMENT_COLUMNS = [
    "lemlist_enrichment_id",
    "email_enriched_at",
    "apollo_enriched_at",
    "placeholder_email_generated_at",
]
LINKEDIN_ONLY_CAMPAIGN = "Technology-based outreach - LinkedIn only"
PLACEHOLDER_EMAIL_DOMAIN = "technology-outreach-linkedin-only.invalid"


class LemlistEnrichmentClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def request_find_email(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            "https://api.lemlist.com/api/v2/enrichments/bulk",
            data=json.dumps(rows).encode(),
            method="POST",
            headers=self._headers(),
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))

    def get_result(self, enrichment_id: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"https://api.lemlist.com/api/enrich/{urllib.parse.quote(enrichment_id)}",
            headers=self._headers(),
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))

    def _headers(self) -> dict[str, str]:
        auth = base64.b64encode(f":{self.api_key}".encode()).decode()
        return {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "User-Agent": "linkedin-mcp-experimentation/1.0",
        }


class ApolloEnrichmentClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def match_person(self, row: dict[str, str]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "reveal_personal_emails": False,
            "reveal_phone_number": False,
        }
        linkedin = row.get("person_linkedin_url", "").strip()
        if linkedin:
            payload["linkedin_url"] = linkedin
        else:
            first_name = row.get("first_name", "").strip()
            last_name = row.get("last_name", "").strip()
            company_domain = row.get("company_domain", "").strip() or domain_from_url(row.get("company_website", ""))
            company_name = row.get("company_name", "").strip()
            if first_name:
                payload["first_name"] = first_name
            if last_name:
                payload["last_name"] = last_name
            if company_domain:
                payload["organization_domain"] = company_domain
            if company_name:
                payload["organization_name"] = company_name
        if not (payload.get("linkedin_url") or (payload.get("first_name") and payload.get("last_name") and (payload.get("organization_domain") or payload.get("organization_name")))):
            return {}
        request = urllib.request.Request(
            "https://api.apollo.io/api/v1/people/match",
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
        return data.get("person") or {}


def open_contacts_sheet(config: dict[str, Any], contacts_csv: Path | None) -> Sheet:
    if contacts_csv:
        sheet = CsvSheet(contacts_csv)
        sheet.ensure_columns([*CONTACT_COLUMNS, *ENRICHMENT_COLUMNS])
        return sheet
    workbook = GoogleWorkbook(str(config["spreadsheet_id"]))
    sheet = workbook.worksheet(
        str(config["contacts_worksheet"]),
        [*CONTACT_COLUMNS, *ENRICHMENT_COLUMNS],
        create_if_missing=True,
    )
    sheet.ensure_columns(ENRICHMENT_COLUMNS)
    return sheet


def enrichment_input(row: dict[str, str]) -> dict[str, str]:
    linkedin = row.get("person_linkedin_url", "").strip()
    if linkedin:
        return {"linkedinUrl": linkedin}
    company_domain = row.get("company_domain", "").strip() or domain_from_url(row.get("company_website", ""))
    first_name = row.get("first_name", "").strip()
    last_name = row.get("last_name", "").strip()
    company_name = row.get("company_name", "").strip()
    if first_name and last_name and company_name and company_domain:
        return {
            "firstName": first_name,
            "lastName": last_name,
            "companyName": company_name,
            "companyDomain": company_domain,
        }
    return {}


def placeholder_email(
    row: dict[str, str],
    placeholder_domain: str = PLACEHOLDER_EMAIL_DOMAIN,
) -> str:
    identity = (
        row.get("person_linkedin_url", "").strip()
        or row.get("person_name", "").strip()
        or row.get("email", "").strip()
        or json.dumps(row, sort_keys=True)
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return f"linkedin-only+{digest}@{placeholder_domain}"


def start_enrichment(sheet: Sheet, client: LemlistEnrichmentClient, dry_run: bool, limit: int | None) -> dict[str, Any]:
    sheet.ensure_columns([*CONTACT_COLUMNS, *ENRICHMENT_COLUMNS])
    candidates = []
    summary = {
        "dry_run": dry_run,
        "mode": "start",
        "rows_seen": 0,
        "queued": 0,
        "skipped": 0,
        "failed": 0,
    }
    for row in sheet.rows():
        summary["rows_seen"] += 1
        data = row.data
        if data.get("status", "").strip().casefold() != "needs_email":
            continue
        if data.get("email", "").strip():
            summary["skipped"] += 1
            continue
        if data.get("lemlist_enrichment_id", "").strip():
            summary["skipped"] += 1
            continue
        input_data = enrichment_input(data)
        if not input_data:
            if not dry_run:
                sheet.update_row(row.number, {
                    "status": "email_enrichment_failed",
                    "email_status": "missing_enrichment_input",
                    "lemlist_error": "Missing LinkedIn URL or first/last/company/domain for email enrichment",
                })
            summary["failed"] += 1
            continue
        candidates.append((row.number, {
            "input": input_data,
            "enrichmentRequests": ["find_email"],
            "metadata": {"row_number": row.number},
        }))
        if limit is not None and len(candidates) >= limit:
            break

    if not candidates:
        return summary

    if dry_run:
        summary["queued"] = len(candidates)
        return summary

    results = client.request_find_email([payload for _, payload in candidates])
    for (row_number, _), result in zip(candidates, results):
        if result.get("id"):
            sheet.update_row(row_number, {
                "status": "email_finding",
                "email_status": "submitted_to_lemlist",
                "lemlist_enrichment_id": str(result["id"]),
                "lemlist_error": "",
            })
            summary["queued"] += 1
        else:
            sheet.update_row(row_number, {
                "status": "email_enrichment_failed",
                "email_status": str(result.get("error", "unknown_error")),
                "lemlist_error": json.dumps(result)[:1000],
            })
            summary["failed"] += 1
    return summary


def apollo_enrichment(sheet: Sheet, client: ApolloEnrichmentClient, dry_run: bool, limit: int | None) -> dict[str, Any]:
    sheet.ensure_columns([*CONTACT_COLUMNS, *ENRICHMENT_COLUMNS])
    summary = {
        "dry_run": dry_run,
        "mode": "apollo",
        "rows_seen": 0,
        "checked": 0,
        "found": 0,
        "not_found": 0,
        "failed": 0,
    }
    for row in sheet.rows():
        if limit is not None and summary["checked"] >= limit:
            break
        summary["rows_seen"] += 1
        data = row.data
        if data.get("status", "").strip().casefold() not in {
            "email_not_found",
            "email_enrichment_failed",
        }:
            continue
        if data.get("email", "").strip():
            continue
        summary["checked"] += 1
        try:
            person = client.match_person(data)
        except Exception as exc:
            if not dry_run:
                sheet.update_row(row.number, {
                    "email_status": "apollo_error",
                    "lemlist_error": str(exc)[:1000],
                })
            summary["failed"] += 1
            continue
        email = str(person.get("email", "") or "").strip()
        email_status = str(person.get("email_status", "") or "").strip()
        if email:
            if not dry_run:
                sheet.update_row(row.number, {
                    "status": "",
                    "email": email,
                    "email_status": email_status or "apollo_found",
                    "apollo_enriched_at": now_iso(),
                    "lemlist_error": "",
                })
            summary["found"] += 1
        else:
            if not dry_run:
                sheet.update_row(row.number, {
                    "status": "apollo_email_not_found",
                    "email_status": email_status or "apollo_not_found",
                    "apollo_enriched_at": now_iso(),
                    "lemlist_error": "",
                })
            summary["not_found"] += 1
    return summary


def finalize_linkedin_only(
    sheet: Sheet,
    dry_run: bool,
    limit: int | None,
    campaign_name: str = LINKEDIN_ONLY_CAMPAIGN,
    placeholder_domain: str = PLACEHOLDER_EMAIL_DOMAIN,
) -> dict[str, Any]:
    sheet.ensure_columns([*CONTACT_COLUMNS, *ENRICHMENT_COLUMNS])
    summary = {
        "dry_run": dry_run,
        "mode": "finalize_linkedin_only",
        "rows_seen": 0,
        "finalized": 0,
        "skipped": 0,
    }
    # Lemlist failures must receive the Apollo fallback before a contact is
    # downgraded to LinkedIn-only routing.
    eligible_statuses = {"email_not_found", "apollo_email_not_found"}
    for row in sheet.rows():
        if limit is not None and summary["finalized"] >= limit:
            break
        summary["rows_seen"] += 1
        data = row.data
        status = data.get("status", "").strip().casefold()
        if status not in eligible_statuses:
            continue
        if data.get("email", "").strip():
            summary["skipped"] += 1
            continue
        linkedin = data.get("person_linkedin_url", "").strip()
        if not linkedin:
            summary["skipped"] += 1
            continue
        if not dry_run:
            sheet.update_row(row.number, {
                "status": "",
                "email": placeholder_email(data, placeholder_domain),
                "email_status": "placeholder_linkedin_only",
                "lemlist_campaign": campaign_name,
                "placeholder_email_generated_at": now_iso(),
                "lemlist_error": "",
            })
        summary["finalized"] += 1
    return summary


def extract_email_result(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data", {})
    find_email = data.get("find_email") or data.get("email") or {}
    if isinstance(find_email, dict):
        email = str(find_email.get("email", "") or "").strip()
        status = str(find_email.get("status", "") or "").strip()
        if not email and find_email.get("notFound"):
            return "", "not_found"
        return email, status or ("found" if email else "")
    return "", ""


def poll_enrichment(sheet: Sheet, client: LemlistEnrichmentClient, dry_run: bool, limit: int | None) -> dict[str, Any]:
    sheet.ensure_columns([*CONTACT_COLUMNS, *ENRICHMENT_COLUMNS])
    summary = {
        "dry_run": dry_run,
        "mode": "poll",
        "rows_seen": 0,
        "checked": 0,
        "found": 0,
        "not_found": 0,
        "pending": 0,
        "failed": 0,
    }
    for row in sheet.rows():
        if limit is not None and summary["checked"] >= limit:
            break
        summary["rows_seen"] += 1
        data = row.data
        if data.get("status", "").strip().casefold() != "email_finding":
            continue
        enrichment_id = data.get("lemlist_enrichment_id", "").strip()
        if not enrichment_id:
            summary["failed"] += 1
            continue
        summary["checked"] += 1
        try:
            result = client.get_result(enrichment_id)
        except Exception as exc:
            if not dry_run:
                sheet.update_row(row.number, {"lemlist_error": str(exc)[:1000]})
            summary["failed"] += 1
            continue
        status = str(result.get("enrichmentStatus", "") or "").casefold()
        if status and status != "done":
            summary["pending"] += 1
            continue
        email, email_status = extract_email_result(result)
        if email:
            if not dry_run:
                sheet.update_row(row.number, {
                    "status": "",
                    "email": email,
                    "email_status": email_status or "found",
                    "email_enriched_at": now_iso(),
                    "lemlist_error": "",
                })
            summary["found"] += 1
            continue
        if not dry_run:
            sheet.update_row(row.number, {
                "status": "email_not_found",
                "email_status": email_status or "not_found",
                "email_enriched_at": now_iso(),
                "lemlist_error": "",
            })
        summary["not_found"] += 1
    return summary


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def apollo_api_key() -> str:
    key = os.environ.get("APOLLO_API_KEY", "").strip()
    if key:
        return key
    if APOLLO_SKILL_ENV.exists():
        for line in APOLLO_SKILL_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "APOLLO_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--contacts-csv", type=Path)
    parser.add_argument("--mode", choices=["start", "poll", "apollo", "finalize-linkedin-only"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    try:
        load_env_file()
        config = load_config(args.config)
        sheet = open_contacts_sheet(config, args.contacts_csv)
        if args.mode == "start":
            api_key = os.environ.get("LEMLIST_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("Set LEMLIST_API_KEY")
            client = LemlistEnrichmentClient(api_key)
            result = start_enrichment(sheet, client, args.dry_run, args.limit)
        elif args.mode == "poll":
            api_key = os.environ.get("LEMLIST_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("Set LEMLIST_API_KEY")
            client = LemlistEnrichmentClient(api_key)
            result = poll_enrichment(sheet, client, args.dry_run, args.limit)
        elif args.mode == "apollo":
            api_key = apollo_api_key()
            if not api_key:
                raise RuntimeError("Set APOLLO_API_KEY")
            result = apollo_enrichment(sheet, ApolloEnrichmentClient(api_key), args.dry_run, args.limit)
        else:
            result = finalize_linkedin_only(
                sheet,
                args.dry_run,
                args.limit,
                campaign_name=str(config.get("linkedin_only_campaign", LINKEDIN_ONLY_CAMPAIGN)),
                placeholder_domain=str(config.get("linkedin_only_placeholder_domain", PLACEHOLDER_EMAIL_DOMAIN)),
            )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
