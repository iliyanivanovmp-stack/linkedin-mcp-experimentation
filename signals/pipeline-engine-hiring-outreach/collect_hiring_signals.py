"""Detect active hiring intent for Pipeline Engine-related roles."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
from lead_sheet import append_leads  # noqa: E402
from linkedin_mcp_client import LinkedInMCPClient, LinkedInMCPExtractor  # noqa: E402

DEFAULT_CONFIG = ROOT / "sourcing_config.json"
DEFAULT_OUTPUT = ROOT / "exports" / "pipeline_engine_hiring_opportunities.csv"
DEFAULT_STATE = ROOT / "state" / "seen_job_ids.json"
DEFAULT_LEAD_SHEET = ROOT / "exports" / "pipeline_leads.csv"
DEFAULT_SYSTEM_CONFIG = ROOT / "config.json"

FIELDS = [
    "signal_type",
    "detected_at",
    "job_id",
    "job_url",
    "poster_linkedin_url",
    "company_name",
    "company_linkedin_url",
    "company_website",
    "company_domain",
    "job_title",
    "job_description",
    "compensation_text",
    "compensation_min",
    "compensation_max",
    "compensation_currency",
    "compensation_period",
    "role_family",
    "intent_score",
    "evidence_terms",
    "offer_angle",
    "outreach_reason",
    "status",
]


def clean_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()
    ]


def job_identity(text: str) -> tuple[str, str]:
    lines = clean_lines(text)
    return (lines[0] if lines else "", lines[1] if len(lines) > 1 else "")


def normalize_linkedin_url(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("/"):
        value = f"https://www.linkedin.com{value}"
    return value.rstrip("/") + "/" if value else ""


def company_reference(details: dict[str, Any]) -> tuple[str, str]:
    for reference in details.get("references", {}).get("job_posting", []):
        if reference.get("kind") != "company":
            continue
        company_url = normalize_linkedin_url(str(reference.get("url", "")))
        match = re.search(r"/company/([^/?#]+)", company_url)
        return company_url, match.group(1) if match else ""
    return "", ""


def poster_reference(details: dict[str, Any]) -> str:
    """Return the profile LinkedIn identifies as the job's reachable contact."""
    for reference in details.get("references", {}).get("job_posting", []):
        if reference.get("kind") != "person":
            continue
        url = normalize_linkedin_url(str(reference.get("url", "")))
        match = re.search(r"(https://www\.linkedin\.com/in/[^/?#]+)", url)
        return f"{match.group(1)}/" if match else url
    return ""


async def poster_reference_from_loaded_page(page: Any) -> str:
    """Read the contact from the job DOM without navigation or another request."""
    value = await page.evaluate("""() => {
      const contactText = /hiring team|reach out to|contact the job poster|meet the hiring/i;
      const known = document.querySelector(
        'main [class*="hirer-card"] a[href*="/in/"], ' +
        'main [class*="hiring-team"] a[href*="/in/"], ' +
        'main [class*="job-poster"] a[href*="/in/"]'
      );
      if (known) return known.href;
      for (const node of document.querySelectorAll('main section, main div, main li')) {
        if (!contactText.test(node.innerText || '')) continue;
        const link = node.querySelector('a[href*="/in/"]');
        if (link) return link.href;
      }
      return '';
    }""")
    if not value:
        return ""
    match = re.search(r"(https://(?:www\.)?linkedin\.com/in/[^/?#]+)", str(value))
    return normalize_linkedin_url(match.group(1) if match else "")


def company_website(company: dict[str, Any]) -> str:
    for reference in company.get("references", {}).get("about", []):
        if reference.get("kind") == "external":
            return str(reference.get("url", "")).strip()
    return ""


def website_domain(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.casefold().split(":", 1)[0].removeprefix("www.")
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    public_suffix = ".".join(parts[-2:])
    if public_suffix in {"co.uk", "com.au", "co.nz", "co.za", "com.br", "com.mx"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def google_client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if service_json:
        return gspread.authorize(
            Credentials.from_service_account_info(
                json.loads(service_json), scopes=scopes
            )
        )
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not credentials_path:
        raise RuntimeError(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS"
        )
    return gspread.service_account(filename=credentials_path)


def append_google_rows(
    system_config: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, int]:
    if not rows:
        return {"received": 0, "inserted": 0, "duplicates_skipped": 0}
    worksheet = (
        google_client()
        .open_by_key(str(system_config["spreadsheet_id"]))
        .worksheet(str(system_config["companies_worksheet"]))
    )
    values = worksheet.get_all_values()
    headers = values[0] if values else []
    missing_headers = [field for field in FIELDS if field not in headers]
    if missing_headers:
        headers.extend(missing_headers)
        worksheet.update(
            range_name=f"A1:{_column_letter(len(headers))}1", values=[headers]
        )
    job_index = headers.index("job_id")
    existing_ids = {
        str(row[job_index]).strip()
        for row in values[1:]
        if len(row) > job_index and str(row[job_index]).strip()
    }
    fresh = [
        row for row in rows if str(row.get("job_id", "")).strip() not in existing_ids
    ]
    if fresh:
        worksheet.append_rows(
            [[str(row.get(header, "") or "") for header in headers] for row in fresh],
            value_input_option="RAW",
        )
    return {
        "received": len(rows),
        "inserted": len(fresh),
        "duplicates_skipped": len(rows) - len(fresh),
    }


def google_existing_job_ids(system_config: dict[str, Any]) -> set[str]:
    worksheet = (
        google_client()
        .open_by_key(str(system_config["spreadsheet_id"]))
        .worksheet(str(system_config["companies_worksheet"]))
    )
    headers = worksheet.row_values(1)
    if "job_id" not in headers:
        return set()
    column = headers.index("job_id") + 1
    return {
        str(value).strip()
        for value in worksheet.col_values(column)[1:]
        if str(value).strip()
    }


def company_signal_key(
    *,
    company_domain: str = "",
    company_linkedin_url: str = "",
    company_name: str = "",
    job_id: str = "",
) -> str:
    domain = website_domain(company_domain)
    if domain:
        return f"domain:{domain}"
    match = re.search(r"/company/([^/?#]+)", company_linkedin_url.casefold())
    if match:
        return f"linkedin:{match.group(1)}"
    normalized_name = re.sub(r"\s+", " ", company_name).strip().casefold()
    if normalized_name:
        return f"name:{normalized_name}"
    return f"job:{job_id.strip()}" if job_id.strip() else ""


def daily_company_keys(
    values: list[list[str]],
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> set[str]:
    """Return unique hiring-signal company keys already added today."""
    if not values:
        return set()
    headers = values[0]
    required = {"detected_at", "job_id"}
    if not required.issubset(headers):
        return set()
    timezone_info = ZoneInfo(timezone_name)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    today = current.astimezone(timezone_info).date()
    detected_index = headers.index("detected_at")
    job_index = headers.index("job_id")
    signal_index = headers.index("signal_type") if "signal_type" in headers else None
    company_index = headers.index("company_name") if "company_name" in headers else None
    domain_index = (
        headers.index("company_domain") if "company_domain" in headers else None
    )
    linkedin_index = (
        headers.index("company_linkedin_url")
        if "company_linkedin_url" in headers
        else None
    )
    company_keys: set[str] = set()
    for row in values[1:]:
        if signal_index is not None and len(row) > signal_index:
            signal_type = str(row[signal_index]).strip()
            if signal_type and signal_type != "pipeline_engine_hiring_intent":
                continue
        if len(row) <= detected_index or not str(row[detected_index]).strip():
            continue
        try:
            detected = datetime.fromisoformat(
                str(row[detected_index]).strip().replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=timezone.utc)
        if detected.astimezone(timezone_info).date() != today:
            continue
        key = company_signal_key(
            company_domain=(
                str(row[domain_index]).strip()
                if domain_index is not None and len(row) > domain_index
                else ""
            ),
            company_linkedin_url=(
                str(row[linkedin_index]).strip()
                if linkedin_index is not None and len(row) > linkedin_index
                else ""
            ),
            company_name=(
                str(row[company_index]).strip()
                if company_index is not None and len(row) > company_index
                else ""
            ),
            job_id=str(row[job_index]).strip() if len(row) > job_index else "",
        )
        if key:
            company_keys.add(key)
    return company_keys


def daily_company_count(
    values: list[list[str]],
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> int:
    return len(daily_company_keys(values, timezone_name=timezone_name, now=now))


def google_daily_company_keys(
    system_config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> set[str]:
    worksheet = (
        google_client()
        .open_by_key(str(system_config["spreadsheet_id"]))
        .worksheet(str(system_config["companies_worksheet"]))
    )
    return daily_company_keys(
        worksheet.get_all_values(),
        timezone_name=str(system_config.get("timezone", "Europe/Sofia")),
        now=now,
    )


def _column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def parse_amount(value: str) -> float | None:
    match = re.search(r"(?i)(\d[\d,.]*)(?:\s*)(k|m)?", value)
    if not match:
        return None
    raw_number = match.group(1)
    # LinkedIn occasionally drops the final zero in copied salary text,
    # producing values such as "$80,00" for "$80,000".
    if re.fullmatch(r"\d{2,3},\d{2}", raw_number):
        raw_number += "0"
    number = float(raw_number.replace(",", ""))
    multiplier = {"k": 1_000, "m": 1_000_000}.get((match.group(2) or "").casefold(), 1)
    return number * multiplier


def compensation_details(text: str) -> dict[str, Any]:
    currency_pattern = r"[$€£]\s*\d[\d,.]*(?:\s*[kKmM])?"
    pay_words = (
        r"salary|compensation|base pay|pay range|hourly|annual pay|"
        r"annual salary|on-target earnings|ote"
    )
    relevant_lines = []
    for line in clean_lines(text):
        pay_candidate = re.sub(r"(?i)\b401\s*\(?k\)?\b", "", line)
        currency_amounts = re.findall(currency_pattern, pay_candidate)
        has_pay_period = re.search(
            r"(?i)(?:/|\bper\s+)(?:hr|hour|day|week|month|mo|year|yr)\b",
            pay_candidate,
        )
        has_pay_language = re.search(rf"(?i)\b(?:{pay_words})\b", pay_candidate)
        has_pipeline_metric = re.search(
            r"(?i)\b(?:sourced\s+pipeline|pipeline\s+(?:target|quota|per\s+)|"
            r"revenue\s+(?:target|quota|per\s+)|bookings?\s+(?:target|quota|per\s+))",
            pay_candidate,
        )
        if has_pipeline_metric and not has_pay_language:
            continue
        has_currency_amount = currency_amounts and (
            len(currency_amounts) >= 2 or has_pay_period or has_pay_language
        )
        has_pay_number = re.search(
            rf"(?i)\b(?:{pay_words})\b.{{0,100}}\d", pay_candidate
        )
        if has_currency_amount or has_pay_number:
            relevant_lines.append(line)

    if not relevant_lines:
        return {
            "compensation_text": "",
            "compensation_min": "",
            "compensation_max": "",
            "compensation_currency": "",
            "compensation_period": "",
        }

    compensation_text = " | ".join(dict.fromkeys(relevant_lines[:5]))
    parseable_compensation = re.sub(r"(?i)\b401\s*\(?k\)?\b", "", relevant_lines[0])
    amount_tokens = re.findall(
        r"(?:[$€£]\s*)?\d[\d,.]*(?:\s*[kKmM])?", parseable_compensation
    )
    amounts = [
        amount
        for token in amount_tokens
        if (amount := parse_amount(token)) is not None and amount >= 10
    ]
    currency = (
        "USD"
        if "$" in compensation_text
        else "EUR"
        if "€" in compensation_text
        else "GBP"
        if "£" in compensation_text
        else ""
    )
    lower = compensation_text.casefold()
    period = (
        "hour"
        if re.search(r"(?:\b(?:hour|hourly|per hour)\b|/hr\b)", lower)
        else "year"
        if re.search(r"(?:\b(?:year|annual|annually|per year)\b|/yr\b)", lower)
        else "month"
        if re.search(r"(?:\b(?:month|monthly|per month)\b|/mo\b)", lower)
        else "year"
        if amounts and max(amounts) >= 1_000
        else ""
    )
    return {
        "compensation_text": compensation_text,
        "compensation_min": min(amounts) if amounts else "",
        "compensation_max": max(amounts) if amounts else "",
        "compensation_currency": currency,
        "compensation_period": period,
    }


def job_description_text(text: str) -> str:
    marker = re.search(r"(?im)^about the job\s*$", text)
    description = text[marker.end() :] if marker else text
    description = re.split(
        r"(?im)^(?:… more|set alert for similar jobs|about the company)\s*$",
        description,
        maxsplit=1,
    )[0]
    return description.strip()


def indefinite_article(value: str) -> str:
    return "an" if value[:1].casefold() in {"a", "e", "i", "o", "u"} else "a"


def classify_job(text: str, config: dict[str, Any]) -> dict[str, Any] | None:
    company_name, job_title = job_identity(text)
    title = job_title.casefold()
    company = company_name.casefold()
    lower = text.casefold()
    if any(term.casefold() in title for term in config.get("exclude_title_terms", [])):
        return None
    if any(
        term.casefold() in company for term in config.get("exclude_company_terms", [])
    ):
        return None
    if any(
        term.casefold() in lower for term in config.get("exclude_description_terms", [])
    ):
        return None

    candidates = []
    for family, rules in config["role_families"].items():
        matches = [term for term in rules["title_terms"] if term.casefold() in title]
        if matches:
            candidates.append((int(rules["score"]), family, rules, matches))
    if not candidates:
        return None

    score, family, rules, title_matches = max(candidates, key=lambda item: item[0])
    evidence = [
        term for term in config.get("evidence_terms", []) if term.casefold() in lower
    ]
    if rules.get("require_evidence") and not evidence:
        return None
    if evidence:
        score = min(100, score + min(10, len(evidence) * 2))

    return {
        "company_name": company_name,
        "job_title": job_title,
        "role_family": family,
        "intent_score": score,
        "title_matches": title_matches,
        "evidence_terms": evidence,
        "offer_angle": rules["offer_angle"],
        "outreach_reason": (
            f"{company_name} is actively hiring {indefinite_article(job_title)} "
            f"{job_title}. "
            "The role indicates current investment in outbound or pipeline capacity."
        ),
    }


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text())
    return {str(job_id) for job_id in payload.get("job_ids", [])}


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "job_ids": sorted(seen),
            },
            indent=2,
        )
    )


def append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows: list[dict[str, str]] = []
    if path.exists() and path.stat().st_size > 0:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            existing_rows = list(reader)

    by_job_id = {
        row.get("job_id", ""): {field: row.get(field, "") for field in FIELDS}
        for row in existing_rows
        if row.get("job_id", "")
    }
    order = [row.get("job_id", "") for row in existing_rows if row.get("job_id", "")]
    for row in rows:
        job_id = str(row.get("job_id", ""))
        if job_id not in by_job_id:
            order.append(job_id)
        by_job_id[job_id] = {field: str(row.get(field, "")) for field in FIELDS}

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(by_job_id[job_id] for job_id in order)


async def collect(
    config: dict[str, Any],
    known_job_ids: list[str] | None = None,
    skip_job_ids: set[str] | None = None,
    skip_company_keys: set[str] | None = None,
) -> dict[str, Any]:
    searches = []
    opportunities = []
    inspected: set[str] = set()
    selected_company_keys = set(skip_company_keys or set())
    client = LinkedInMCPClient()
    try:
        extractor = LinkedInMCPExtractor(client)
        query_job_ids = known_job_ids
        for query in config["search_queries"]:
            if query_job_ids is not None:
                search = {"job_ids": query_job_ids, "url": "known-job-ids"}
            else:
                search = await extractor.search_jobs(
                    query,
                    location=config.get("location"),
                    max_pages=int(config.get("max_pages", 1)),
                    date_posted=config.get("date_posted"),
                    job_type=config.get("job_type"),
                    experience_level=config.get("experience_level"),
                    work_type=config.get("work_type"),
                    easy_apply=bool(config.get("easy_apply", False)),
                    sort_by=config.get("sort_by", "date"),
                )
            searches.append({
                "query": query,
                "url": search.get("url", ""),
                "jobs_found": len(search.get("job_ids", [])),
            })
            detail_limit = int(config.get("max_job_details_per_query", 10))
            opportunity_limit = int(config.get("max_opportunities_per_run", 10))
            for job_id in search.get("job_ids", []):
                job_id = str(job_id)
                if job_id in inspected or job_id in (skip_job_ids or set()):
                    continue
                if len(inspected) >= detail_limit:
                    break
                inspected.add(job_id)
                try:
                    details = await asyncio.wait_for(
                        extractor.scrape_job(job_id),
                        timeout=60,
                    )
                except Exception:
                    continue
                text = details.get("sections", {}).get("job_posting", "")
                classification = classify_job(text, config)
                if not classification:
                    continue
                company_linkedin_url, company_slug = company_reference(details)
                website = ""
                if company_slug:
                    try:
                        company = await asyncio.wait_for(
                            extractor.scrape_company(company_slug, {"about"}),
                            timeout=45,
                        )
                        company_linkedin_url = normalize_linkedin_url(company.get("url", "")) or company_linkedin_url
                        website = company_website(company)
                    except Exception:
                        pass
                domain = website_domain(website)
                selected_company_key = company_signal_key(
                    company_domain=domain,
                    company_linkedin_url=company_linkedin_url,
                    company_name=classification["company_name"],
                    job_id=job_id,
                )
                if selected_company_key in selected_company_keys:
                    continue
                selected_company_keys.add(selected_company_key)
                opportunities.append({
                    "job_id": job_id,
                    "job_url": details.get("url") or f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "poster_linkedin_url": poster_reference(details),
                    "company_linkedin_url": company_linkedin_url,
                    "company_website": website,
                    "company_domain": domain,
                    "job_description": job_description_text(text),
                    **compensation_details(text),
                    "text": text,
                    **classification,
                })
                if len(opportunities) >= opportunity_limit:
                    break
            if query_job_ids is not None or len(opportunities) >= opportunity_limit:
                break
        if known_job_ids is None and not inspected:
            raise RuntimeError(
                "Central LinkedIn MCP returned zero job IDs across all configured searches"
            )
        return {
            "searches": searches,
            "jobs_inspected": len(inspected),
            "opportunities": opportunities,
        }
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--lead-sheet", type=Path, default=DEFAULT_LEAD_SHEET)
    parser.add_argument("--system-config", type=Path, default=DEFAULT_SYSTEM_CONFIG)
    parser.add_argument("--job-id", action="append", dest="job_ids")
    parser.add_argument(
        "--limit", type=int, help="Bound job details/opportunities for a test run"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and qualify jobs without writing local state, CSV files, or Google Sheets",
    )
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    seen = set() if args.reset_state else load_seen(args.state)
    system_config = json.loads(args.system_config.read_text())
    daily_limit = max(0, int(system_config.get("daily_company_limit", 10)))
    company_keys_added_today = google_daily_company_keys(system_config)
    companies_added_today = len(company_keys_added_today)
    daily_remaining = max(0, daily_limit - companies_added_today)
    requested_limit = daily_remaining
    if args.limit is not None:
        requested_limit = min(requested_limit, max(0, args.limit))
    effective_limit = min(
        requested_limit,
        max(0, int(config.get("max_opportunities_per_run", requested_limit))),
    )
    # Inspection capacity and accepted-company capacity are deliberately
    # separate. Rejected, duplicate, removed, and timed-out jobs must not
    # prevent the system from filling the daily accepted-company target.
    config["max_job_details_per_query"] = max(
        effective_limit,
        max(0, int(config.get("max_job_details_per_query", effective_limit))),
    )
    config["max_opportunities_per_run"] = effective_limit
    sheet_job_ids = google_existing_job_ids(system_config)
    skip_job_ids = set() if args.job_ids is not None else (seen | sheet_job_ids)
    result = (
        asyncio.run(
            collect(config, args.job_ids, skip_job_ids, company_keys_added_today)
        )
        if effective_limit > 0
        else {"searches": [], "jobs_inspected": 0, "opportunities": []}
    )
    detected_at = datetime.now(timezone.utc).isoformat()
    rows = []
    lead_rows = []
    duplicate_jobs = 0

    for opportunity in result["opportunities"]:
        job_id = opportunity["job_id"]
        if job_id in seen:
            duplicate_jobs += 1
            continue
        seen.add(job_id)
        row = {
            "signal_type": "pipeline_engine_hiring_intent",
            "detected_at": detected_at,
            "job_id": job_id,
            "job_url": opportunity["job_url"],
            "poster_linkedin_url": opportunity["poster_linkedin_url"],
            "company_name": opportunity["company_name"],
            "company_linkedin_url": opportunity["company_linkedin_url"],
            "company_website": opportunity["company_website"],
            "company_domain": opportunity["company_domain"],
            "job_title": opportunity["job_title"],
            "job_description": opportunity["job_description"],
            "compensation_text": opportunity["compensation_text"],
            "compensation_min": opportunity["compensation_min"],
            "compensation_max": opportunity["compensation_max"],
            "compensation_currency": opportunity["compensation_currency"],
            "compensation_period": opportunity["compensation_period"],
            "role_family": opportunity["role_family"],
            "intent_score": opportunity["intent_score"],
            "evidence_terms": ", ".join(opportunity["evidence_terms"]),
            "offer_angle": opportunity["offer_angle"],
            "outreach_reason": opportunity["outreach_reason"],
            "status": "opportunity_detected",
        }
        rows.append(row)
        lead_rows.append(
            {
                "signal_type": row["signal_type"],
                "detected_at": detected_at,
                "lead_type": "company",
                "lead_key": f"job:{job_id}",
                "company_name": row["company_name"],
                "company_linkedin_url": row["company_linkedin_url"],
                "company_website": row["company_website"],
                "company_domain": row["company_domain"],
                "source_url": row["job_url"],
                "evidence": row["outreach_reason"],
                "metadata_json": {
                    "job_id": job_id,
                    "job_title": row["job_title"],
                    "poster_linkedin_url": row["poster_linkedin_url"],
                    "company_linkedin_url": row["company_linkedin_url"],
                    "company_website": row["company_website"],
                    "compensation_text": row["compensation_text"],
                    "compensation_min": row["compensation_min"],
                    "compensation_max": row["compensation_max"],
                    "compensation_currency": row["compensation_currency"],
                    "compensation_period": row["compensation_period"],
                    "role_family": row["role_family"],
                    "intent_score": row["intent_score"],
                    "evidence_terms": opportunity["evidence_terms"],
                    "offer_angle": row["offer_angle"],
                    "status": row["status"],
                },
            }
        )

    if args.dry_run:
        lead_result = {
            "received": len(lead_rows),
            "inserted": 0,
            "duplicates_skipped": 0,
            "would_insert": len(lead_rows),
        }
        google_result = {
            "received": len(rows),
            "inserted": 0,
            "duplicates_skipped": 0,
            "would_insert": len(rows),
        }
    else:
        append_csv(args.output, rows)
        lead_result = append_leads(args.lead_sheet, lead_rows)
        google_result = append_google_rows(system_config, rows)
        save_seen(args.state, seen)
    print(
        json.dumps(
            {
                "status": "success",
                "dry_run": args.dry_run,
                "searches": result["searches"],
                "jobs_inspected": result["jobs_inspected"],
                "opportunities_qualified": len(result["opportunities"]),
                "new_opportunities": len(rows),
                "daily_company_limit": daily_limit,
                "companies_added_today_before_run": companies_added_today,
                "daily_company_capacity_requested": effective_limit,
                "daily_company_capacity_used": google_result["inserted"],
                "daily_company_capacity_remaining": max(
                    0,
                    daily_remaining
                    - (0 if args.dry_run else google_result["inserted"]),
                ),
                "duplicate_jobs_skipped": duplicate_jobs,
                "output": str(args.output),
                "state": str(args.state),
                "lead_sheet": str(args.lead_sheet),
                "lead_sheet_result": lead_result,
                "google_sheet_result": google_result,
                "rows": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
