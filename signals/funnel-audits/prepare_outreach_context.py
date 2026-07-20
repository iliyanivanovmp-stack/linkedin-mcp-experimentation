from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extract_contacts import (
    CsvSheet,
    GoogleWorkbook,
    Sheet,
    company_payload,
    load_config,
    load_env_file,
    qualified_company,
)


DEFAULT_CONFIG = Path(__file__).with_name("contact_extraction_config.json")
CONTEXT_COLUMNS = ["opener", "solution_angle", "outreach_context_generated_at"]


def compact_sentence(value: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return fallback
    text = text.rstrip(".")
    return f"{text}."


def generated_opener(company: dict[str, str]) -> str:
    company_name = company.get("company_name") or "your team"
    gap = company.get("gap_reason") or company.get("evidence") or "a possible pipeline gap"
    return compact_sentence(
        f"Quick note on the funnel gap for {company_name}: {gap}",
        f"Quick note on a possible pipeline gap I noticed for {company_name}.",
    )


def generated_solution_angle(company: dict[str, str]) -> str:
    outreach_reason = company.get("outreach_reason") or ""
    gap = company.get("gap_reason") or company.get("evidence") or ""
    basis = outreach_reason or gap
    if basis:
        return compact_sentence(
            f"Turn the detected gap into a cleaner conversion path with clearer next steps, faster follow-up, and better routing around this issue: {basis}",
            "Tighten the conversion path with clearer next steps, faster follow-up, and better routing.",
        )
    return "Tighten the conversion path with clearer next steps, faster follow-up, and better routing."


def exact_cell(row: dict[str, str], column: str) -> str:
    return str(row.get(column, "") or "").strip()


def prepare_context(
    sheet: Sheet,
    config: dict[str, Any],
    dry_run: bool,
    limit: int | None,
    force: bool = False,
) -> dict[str, Any]:
    qualified_statuses = {
        str(status).casefold()
        for status in config.get("qualified_statuses", [])
    }
    if not dry_run:
        sheet.ensure_columns(CONTEXT_COLUMNS)
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "dry_run": dry_run,
        "rows_seen": 0,
        "qualified": 0,
        "updated": 0,
        "skipped": 0,
    }
    for row in sheet.rows():
        if limit is not None and summary["updated"] >= limit:
            break
        summary["rows_seen"] += 1
        if not qualified_company(row.data, qualified_statuses):
            continue
        summary["qualified"] += 1
        company = company_payload(row.data)
        updates = {}
        if force or not exact_cell(row.data, "opener"):
            updates["opener"] = generated_opener(company)
        if force or not exact_cell(row.data, "solution_angle"):
            updates["solution_angle"] = generated_solution_angle(company)
        if updates:
            updates["outreach_context_generated_at"] = generated_at
            if not dry_run:
                sheet.update_row(row.number, updates)
            summary["updated"] += 1
        else:
            summary["skipped"] += 1
    return summary


def open_company_sheet(config: dict[str, Any], companies_csv: Path | None) -> Sheet:
    if companies_csv:
        return CsvSheet(companies_csv)
    workbook = GoogleWorkbook(str(config["spreadsheet_id"]))
    return workbook.worksheet(str(config["companies_worksheet"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--companies-csv", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        load_env_file()
        config = load_config(args.config)
        sheet = open_company_sheet(config, args.companies_csv)
        result = prepare_context(sheet, config, args.dry_run, args.limit, args.force)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
