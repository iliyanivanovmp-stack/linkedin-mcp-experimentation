from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from extract_contacts import CsvSheet, GoogleWorkbook, Sheet, load_config, load_env_file


DEFAULT_CONFIG = Path(__file__).with_name("contact_extraction_config.json")
ATTENTION_CONTACT_STATUSES = {
    "failed",
    "needs_email",
    "email_finding",
    "email_not_found",
    "apollo_email_not_found",
    "email_enrichment_failed",
}
ATTENTION_COMPANY_STATUSES = {"contacts_failed"}


def status_value(row: dict[str, str], key: str) -> str:
    return str(row.get(key, "") or "").strip() or "<blank>"


def sample_rows(rows: list[dict[str, str]], fields: list[str], limit: int) -> list[dict[str, str]]:
    output = []
    for row in rows[:limit]:
        output.append({field: str(row.get(field, "") or "") for field in fields})
    return output


def monitor(companies: Sheet, contacts: Sheet, sample_limit: int) -> dict[str, Any]:
    company_rows = [row.data for row in companies.rows()]
    contact_rows = [row.data for row in contacts.rows()]
    company_status_counts = Counter(status_value(row, "contacts_status") for row in company_rows)
    contact_status_counts = Counter(status_value(row, "status") for row in contact_rows)
    email_status_counts = Counter(status_value(row, "email_status") for row in contact_rows)

    company_attention = [
        row for row in company_rows
        if status_value(row, "contacts_status").casefold() in ATTENTION_COMPANY_STATUSES
    ]
    contact_attention = [
        row for row in contact_rows
        if status_value(row, "status").casefold() in ATTENTION_CONTACT_STATUSES
    ]
    missing_context = [
        row for row in contact_rows
        if not str(row.get("gap_reason", "") or "").strip()
        or not str(row.get("outreach_reason", "") or "").strip()
    ]
    missing_lemlist_ids = [
        row for row in contact_rows
        if str(row.get("status", "") or "").strip().casefold() == "plugged"
        and not str(row.get("lemlist_lead_id", "") or "").strip()
    ]
    return {
        "companies_total": len(company_rows),
        "contacts_total": len(contact_rows),
        "company_contacts_status_counts": dict(sorted(company_status_counts.items())),
        "contact_status_counts": dict(sorted(contact_status_counts.items())),
        "email_status_counts": dict(sorted(email_status_counts.items())),
        "attention_counts": {
            "company_contact_failures": len(company_attention),
            "contact_rows_requiring_action": len(contact_attention),
            "contacts_missing_gap_context": len(missing_context),
            "plugged_contacts_missing_lemlist_id": len(missing_lemlist_ids),
        },
        "samples": {
            "company_contact_failures": sample_rows(
                company_attention,
                ["company_name", "website_url", "contacts_error"],
                sample_limit,
            ),
            "contact_rows_requiring_action": sample_rows(
                contact_attention,
                ["company_name", "person_name", "status", "email_status", "lemlist_error"],
                sample_limit,
            ),
            "contacts_missing_gap_context": sample_rows(
                missing_context,
                ["company_name", "person_name", "status", "gap_reason", "outreach_reason"],
                sample_limit,
            ),
            "plugged_contacts_missing_lemlist_id": sample_rows(
                missing_lemlist_ids,
                ["company_name", "person_name", "email", "status"],
                sample_limit,
            ),
        },
    }


def open_sheets(config: dict[str, Any], companies_csv: Path | None, contacts_csv: Path | None) -> tuple[Sheet, Sheet]:
    if companies_csv or contacts_csv:
        if not companies_csv or not contacts_csv:
            raise ValueError("Both --companies-csv and --contacts-csv are required for CSV mode")
        return CsvSheet(companies_csv), CsvSheet(contacts_csv)
    workbook = GoogleWorkbook(str(config["spreadsheet_id"]))
    return (
        workbook.worksheet(str(config["companies_worksheet"])),
        workbook.worksheet(str(config["contacts_worksheet"]), create_if_missing=False),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--companies-csv", type=Path)
    parser.add_argument("--contacts-csv", type=Path)
    parser.add_argument("--sample-limit", type=int, default=5)
    args = parser.parse_args()

    try:
        load_env_file()
        companies, contacts = open_sheets(config := load_config(args.config), args.companies_csv, args.contacts_csv)
        result = monitor(companies, contacts, args.sample_limit)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
