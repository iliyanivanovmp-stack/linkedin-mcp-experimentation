"""Shared pipeline lead sheet with signal-scoped deduplication."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


FIELDS = [
    "signal_type",
    "detected_at",
    "lead_type",
    "lead_key",
    "person_name",
    "person_linkedin_url",
    "headline",
    "company_name",
    "company_linkedin_url",
    "company_website",
    "company_domain",
    "source_url",
    "evidence",
    "metadata_json",
]


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.netloc:
        return value.rstrip("/").casefold()
    host = parsed.netloc.casefold().removeprefix("www.")
    return f"{parsed.scheme or 'https'}://{host}{parsed.path.rstrip('/')}"


def normalize_domain(value: str) -> str:
    value = (value or "").strip().casefold()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.removeprefix("www.")


def lead_key(row: dict[str, Any]) -> str:
    explicit = str(row.get("lead_key", "")).strip().casefold()
    if explicit:
        return explicit
    profile = normalize_url(str(row.get("person_linkedin_url", "")))
    if profile:
        return f"person:{profile}"
    domain = normalize_domain(str(row.get("company_domain", "")))
    if domain:
        return f"company:{domain}"
    company = str(row.get("company_name", "")).strip().casefold()
    if company:
        return f"company-name:{company}"
    source = normalize_url(str(row.get("source_url", "")))
    if source:
        return f"source:{source}"
    raise ValueError("A lead requires a profile URL, company, domain, or source URL")


def prepare_row(row: dict[str, Any]) -> dict[str, str]:
    prepared = {field: "" for field in FIELDS}
    for field in FIELDS:
        value = row.get(field, "")
        if field == "metadata_json" and isinstance(value, (dict, list)):
            prepared[field] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            prepared[field] = str(value or "").strip()
    prepared["person_linkedin_url"] = normalize_url(prepared["person_linkedin_url"])
    prepared["company_domain"] = normalize_domain(prepared["company_domain"])
    prepared["source_url"] = normalize_url(prepared["source_url"])
    prepared["lead_key"] = lead_key(prepared)
    if not prepared["signal_type"]:
        raise ValueError("signal_type is required")
    return prepared


def append_leads(path: Path, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows: list[dict[str, str]] = []
    existing_by_key: dict[tuple[str, str], dict[str, str]] = {}
    if path.exists() and path.stat().st_size:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            existing_rows = list(csv.DictReader(handle))
            existing_by_key = {
                (row.get("signal_type", ""), row.get("lead_key", "")): row
                for row in existing_rows
            }

    prepared_rows = [prepare_row(row) for row in rows]
    fresh: list[dict[str, str]] = []
    run_seen: set[tuple[str, str]] = set()
    updated = 0
    for row in prepared_rows:
        key = (row["signal_type"], row["lead_key"])
        if key in run_seen:
            continue
        run_seen.add(key)
        if key in existing_by_key:
            existing_row = existing_by_key[key]
            changed = False
            for field in FIELDS:
                if not existing_row.get(field, "") and row.get(field, ""):
                    existing_row[field] = row[field]
                    changed = True
            updated += int(changed)
            continue
        fresh.append(row)

    if updated:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(
                {field: row.get(field, "") for field in FIELDS}
                for row in existing_rows
            )

    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(fresh)

    return {
        "received": len(prepared_rows),
        "inserted": len(fresh),
        "updated": updated,
        "duplicates_skipped": len(prepared_rows) - len(fresh) - updated,
    }
