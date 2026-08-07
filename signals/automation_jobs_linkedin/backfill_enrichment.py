"""Backfill domain and compensation fields on the Automation Jobs sheet."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from enrichment import (
    ApolloCompanyClient,
    ENRICHMENT_FIELDS,
    LemlistCompanyClient,
    enrich_company,
    load_domain_overrides,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = ROOT.parent.parent / "credentials.json"


def column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def google_sheet(credentials_path: Path, sheet_id: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
    return gspread.authorize(credentials).open_by_key(sheet_id).sheet1


def ensure_columns(worksheet, headers: list[str]) -> list[str]:
    missing = [field for field in ENRICHMENT_FIELDS if field not in headers]
    if not missing:
        return headers
    start = len(headers) + 1
    end = len(headers) + len(missing)
    if end > worksheet.col_count:
        worksheet.add_cols(end - worksheet.col_count)
    worksheet.update(
        range_name=f"{column_letter(start)}1:{column_letter(end)}1",
        values=[missing],
    )
    return [*headers, *missing]


async def enrich_row(
    row: dict[str, Any],
    lemlist: LemlistCompanyClient | None,
    apollo: ApolloCompanyClient | None,
    domain_overrides: dict[str, str],
) -> dict[str, Any]:
    website = str(row.get("company_website", "") or "").strip()
    company_linkedin_url = str(row.get("company_linkedin_url", "") or "").strip()
    updates = enrich_company(
        str(row.get("company_name", "") or "").strip(),
        website,
        str(row.get("job_description", "") or ""),
        company_linkedin_url,
        lemlist=lemlist,
        apollo=apollo,
        domain_overrides=domain_overrides,
    )
    if website:
        updates["company_website"] = website
    return updates


async def backfill(worksheet, dry_run: bool, limit: int | None) -> dict[str, Any]:
    values = worksheet.get_all_values()
    if not values:
        raise RuntimeError("Automation Jobs sheet is empty")
    headers = list(values[0])
    if headers[:7] != [
        "detected_at", "company_name", "company_website", "job_title",
        "job_description", "job_url", "poster_linkedin_url",
    ]:
        raise RuntimeError("Unexpected Automation Jobs sheet schema")
    if not dry_run:
        headers = ensure_columns(worksheet, headers)

    lemlist_key = os.environ.get("LEMLIST_API_KEY", "").strip()
    lemlist = LemlistCompanyClient(lemlist_key) if lemlist_key else None
    apollo_key = os.environ.get("APOLLO_API_KEY", "").strip()
    apollo = ApolloCompanyClient(apollo_key) if apollo_key else None
    domain_overrides = load_domain_overrides()
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "rows_seen": 0,
        "rows_updated": 0,
        "domains_resolved": 0,
        "domains_unresolved": 0,
        "domains_ambiguous": 0,
        "compensation_found": 0,
        "errors": [],
    }
    for row_number, raw in enumerate(values[1:], start=2):
        row = {header: raw[index] if index < len(raw) else "" for index, header in enumerate(headers)}
        if not str(row.get("job_id", "")).strip():
            continue
        if limit is not None and summary["rows_seen"] >= limit:
            break
        summary["rows_seen"] += 1
        try:
            updates = await enrich_row(row, lemlist, apollo, domain_overrides)
        except Exception as exc:
            summary["errors"].append({"row": row_number, "error": f"{type(exc).__name__}: {exc}"[:500]})
            continue
        status = str(updates.get("domain_status", "unresolved"))
        if status == "resolved":
            summary["domains_resolved"] += 1
        elif status == "ambiguous":
            summary["domains_ambiguous"] += 1
        else:
            summary["domains_unresolved"] += 1
        if updates.get("compensation_text"):
            summary["compensation_found"] += 1
        changed = {
            key: value
            for key, value in updates.items()
            if key in headers and str(row.get(key, "")) != str(value)
        }
        if changed:
            summary["rows_updated"] += 1
            if not dry_run:
                worksheet.batch_update([
                    {
                        "range": f"{column_letter(headers.index(key) + 1)}{row_number}",
                        "values": [[str(value)]],
                    }
                    for key, value in changed.items()
                ])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--sheet-id", default=os.environ.get("AUTOMATION_JOBS_SHEET_ID", "1GmV-FEfYKEIODbpJanLqxlMDbjMa7DHijNJtnZZpsnk"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    worksheet = google_sheet(args.credentials, args.sheet_id)
    print(json.dumps(asyncio.run(backfill(worksheet, args.dry_run, args.limit)), indent=2))


if __name__ == "__main__":
    main()
