from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from extract_contacts import (
    CONTACT_COLUMNS,
    CsvSheet,
    GoogleWorkbook,
    Sheet,
    company_payload,
    domain_from_url,
    load_config,
    load_env_file,
)


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import feeder  # noqa: E402


DEFAULT_CONFIG = Path(__file__).with_name("contact_extraction_config.json")
CONTEXT_COLUMNS = [
    "gap_reason",
    "outreach_reason",
    "opener",
    "solution_angle",
]


def company_context_by_domain(companies: Sheet) -> dict[str, dict[str, str]]:
    output = {}
    for row in companies.rows():
        company = company_payload(row.data)
        domain = company.get("company_domain") or domain_from_url(company.get("company_website", ""))
        if not domain:
            continue
        output[domain.casefold()] = {
            column: company.get(column, "")
            for column in CONTEXT_COLUMNS
            if company.get(column, "")
        }
    return output


def sync_contact_context(
    companies: Sheet,
    contacts: Sheet,
    dry_run: bool,
    sync_lemlist: bool,
    limit: int | None,
    force: bool = False,
) -> dict[str, Any]:
    contacts.ensure_columns(CONTACT_COLUMNS)
    contexts = company_context_by_domain(companies)
    lemlist = None
    if sync_lemlist and not dry_run:
        api_key = os.environ.get("LEMLIST_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Set LEMLIST_API_KEY to sync variables into Lemlist")
        lemlist = feeder.LemlistClient(api_key, {})
    summary = {
        "dry_run": dry_run,
        "rows_seen": 0,
        "sheet_rows_updated": 0,
        "lemlist_leads_synced": 0,
        "lemlist_sync_skipped": 0,
        "failed": 0,
    }
    for row in contacts.rows():
        if limit is not None and summary["rows_seen"] >= limit:
            break
        summary["rows_seen"] += 1
        data = row.data
        domain = (data.get("company_domain") or domain_from_url(data.get("company_website", ""))).strip().casefold()
        context = contexts.get(domain, {})
        updates = {
            column: value
            for column in CONTEXT_COLUMNS
            if (value := context.get(column, ""))
            and (force or not str(data.get(column, "") or "").strip())
        }
        if updates:
            data = {**data, **updates}
            if not dry_run:
                contacts.update_row(row.number, updates)
            summary["sheet_rows_updated"] += 1
        if not sync_lemlist:
            continue
        lead_id = str(data.get("lemlist_lead_id", "") or "").strip()
        status = str(data.get("status", "") or "").strip().casefold()
        if status != "plugged" or not lead_id:
            summary["lemlist_sync_skipped"] += 1
            continue
        variables = feeder.custom_variables_for_lemlist(data)
        if not variables:
            summary["lemlist_sync_skipped"] += 1
            continue
        if dry_run:
            summary["lemlist_leads_synced"] += 1
            continue
        try:
            assert lemlist is not None
            lemlist.add_custom_variables(lead_id, variables)
            summary["lemlist_leads_synced"] += 1
        except Exception as exc:
            summary["failed"] += 1
            if not dry_run:
                contacts.update_row(row.number, {"lemlist_error": str(exc)[:1000]})
    return summary


def open_sheets(config: dict[str, Any], companies_csv: Path | None, contacts_csv: Path | None) -> tuple[Sheet, Sheet]:
    if companies_csv or contacts_csv:
        if not companies_csv or not contacts_csv:
            raise ValueError("Both --companies-csv and --contacts-csv are required for CSV mode")
        return CsvSheet(companies_csv), CsvSheet(contacts_csv)
    workbook = GoogleWorkbook(str(config["spreadsheet_id"]))
    return (
        workbook.worksheet(str(config["companies_worksheet"])),
        workbook.worksheet(str(config["contacts_worksheet"]), CONTACT_COLUMNS, create_if_missing=True),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--companies-csv", type=Path)
    parser.add_argument("--contacts-csv", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-lemlist-sync", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        load_env_file()
        feeder.load_env_file()
        config = load_config(args.config)
        companies, contacts = open_sheets(config, args.companies_csv, args.contacts_csv)
        result = sync_contact_context(
            companies,
            contacts,
            args.dry_run,
            sync_lemlist=not args.no_lemlist_sync,
            limit=args.limit,
            force=args.force,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    status = "partial_failure" if int(result.get("failed", 0) or 0) else "success"
    print(json.dumps({"status": status, **result}, indent=2))
    if status != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
