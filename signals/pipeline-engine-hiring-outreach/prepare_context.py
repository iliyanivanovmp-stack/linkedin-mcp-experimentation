from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extract_contacts import CsvSheet, GoogleWorkbook, Sheet, load_config, load_env_file


DEFAULT_CONFIG = Path(__file__).with_name("config.json")
CONTEXT_COLUMNS = [
    "hiring_opener",
    "hiring_automation_opportunity",
    "icebreaker",
    "source_url",
    "outreach_context_generated_at",
]


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def build_context(row: dict[str, str]) -> dict[str, str]:
    company = clean(row.get("company_name")) or "your company"
    title = clean(row.get("job_title")) or "a pipeline role"
    offer = clean(row.get("offer_angle")) or (
        "Build the targeting, lead sourcing, sequences, follow-ups, CRM updates, "
        "attribution, and reporting around the role."
    )
    opener = f"Noticed {company} is hiring a {title}."
    opportunity = (
        f"Support the {title} with the targeting, lead sourcing, follow-up, CRM updates, "
        "attribution, and reporting needed to ramp pipeline faster."
    )
    return {
        "hiring_opener": opener,
        "hiring_automation_opportunity": opportunity,
        "icebreaker": opener,
        "source_url": clean(row.get("job_url")),
        "offer_angle": offer,
    }


def prepare_context(sheet: Sheet, dry_run: bool, limit: int | None = None) -> dict[str, Any]:
    if not dry_run:
        sheet.ensure_columns(CONTEXT_COLUMNS)
    now = datetime.now(timezone.utc).isoformat()
    summary = {"dry_run": dry_run, "rows_seen": 0, "updated": 0, "skipped": 0, "missing_domain": 0}
    claimed_domains = {
        clean(row.data.get("company_domain")).casefold()
        for row in sheet.rows()
        if clean(row.data.get("company_domain"))
        and clean(row.data.get("status")).casefold() in {"outreach_ready", "duplicate_company_signal"}
    }
    for row in sheet.rows():
        if limit is not None and summary["updated"] >= limit:
            break
        summary["rows_seen"] += 1
        if clean(row.data.get("status")).casefold() != "opportunity_detected":
            summary["skipped"] += 1
            continue
        domain = clean(row.data.get("company_domain")).casefold()
        if not domain:
            if not dry_run:
                sheet.update_row(row.number, {"status": "needs_company_domain"})
            summary["missing_domain"] += 1
            continue
        if domain in claimed_domains:
            if not dry_run:
                sheet.update_row(row.number, {"status": "duplicate_company_signal"})
            summary["skipped"] += 1
            continue
        updates = build_context(row.data)
        updates.update({"status": "outreach_ready", "outreach_context_generated_at": now})
        if not dry_run:
            sheet.update_row(row.number, updates)
        claimed_domains.add(domain)
        summary["updated"] += 1
    return summary


def open_sheet(config: dict[str, Any], csv_path: Path | None) -> Sheet:
    if csv_path:
        return CsvSheet(csv_path)
    return GoogleWorkbook(str(config["spreadsheet_id"])).worksheet(
        str(config["companies_worksheet"]),
        create_if_missing=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    load_env_file(Path(__file__).resolve().parent / ".env")
    config = load_config(args.config)
    print(json.dumps(prepare_context(open_sheet(config, args.csv), args.dry_run, args.limit), indent=2))


if __name__ == "__main__":
    main()
