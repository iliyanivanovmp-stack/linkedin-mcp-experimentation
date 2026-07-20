"""Detect active hiring intent for Pipeline Engine-related roles."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SIGNALS = ROOT.parent
sys.path.insert(0, str(SIGNALS / "common"))
from lead_sheet import append_leads  # noqa: E402

DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_OUTPUT = SIGNALS / "exports" / "pipeline_engine_hiring_opportunities.csv"
DEFAULT_STATE = ROOT / "state" / "seen_job_ids.json"
DEFAULT_LEAD_SHEET = SIGNALS / "exports" / "pipeline_leads.csv"

FIELDS = [
    "signal_type",
    "detected_at",
    "job_id",
    "job_url",
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
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


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


def company_website(company: dict[str, Any]) -> str:
    for reference in company.get("references", {}).get("about", []):
        if reference.get("kind") == "external":
            return str(reference.get("url", "")).strip()
    return ""


def website_domain(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.casefold().removeprefix("www.")


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
    multiplier = {"k": 1_000, "m": 1_000_000}.get(
        (match.group(2) or "").casefold(), 1
    )
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
    parseable_compensation = re.sub(
        r"(?i)\b401\s*\(?k\)?\b", "", relevant_lines[0]
    )
    amount_tokens = re.findall(
        r"(?:[$€£]\s*)?\d[\d,.]*(?:\s*[kKmM])?", parseable_compensation
    )
    amounts = [
        amount for token in amount_tokens
        if (amount := parse_amount(token)) is not None and amount >= 10
    ]
    currency = (
        "USD" if "$" in compensation_text
        else "EUR" if "€" in compensation_text
        else "GBP" if "£" in compensation_text
        else ""
    )
    lower = compensation_text.casefold()
    period = (
        "hour" if re.search(r"(?:\b(?:hour|hourly|per hour)\b|/hr\b)", lower)
        else "year" if re.search(r"(?:\b(?:year|annual|annually|per year)\b|/yr\b)", lower)
        else "month" if re.search(r"(?:\b(?:month|monthly|per month)\b|/mo\b)", lower)
        else "year" if amounts and max(amounts) >= 1_000
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
    description = text[marker.end():] if marker else text
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
    if any(term.casefold() in title for term in config.get("exclude_title_terms", [])):
        return None

    candidates = []
    for family, rules in config["role_families"].items():
        matches = [
            term for term in rules["title_terms"] if term.casefold() in title
        ]
        if matches:
            candidates.append((int(rules["score"]), family, rules, matches))
    if not candidates:
        return None

    score, family, rules, title_matches = max(candidates, key=lambda item: item[0])
    lower = text.casefold()
    evidence = [
        term for term in config.get("evidence_terms", [])
        if term.casefold() in lower
    ]
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
    path.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "job_ids": sorted(seen),
    }, indent=2))


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


async def collect(config: dict[str, Any], known_job_ids: list[str] | None = None) -> dict[str, Any]:
    original = sys.argv[:]
    sys.argv = [sys.argv[0]]
    from linkedin_mcp_server.drivers.browser import close_browser, get_or_create_browser
    from linkedin_mcp_server.scraping import LinkedInExtractor

    searches = []
    opportunities = []
    inspected: set[str] = set()
    try:
        browser = await get_or_create_browser()
        extractor = LinkedInExtractor(browser.page)
        query_job_ids = known_job_ids
        for query in config["search_queries"]:
            search = (
                {"job_ids": query_job_ids, "url": "known-job-ids"}
                if query_job_ids is not None
                else await extractor.search_jobs(
                    query,
                    location=config.get("location"),
                    max_pages=int(config.get("max_pages", 1)),
                    date_posted=config.get("date_posted"),
                    sort_by=config.get("sort_by", "date"),
                )
            )
            searches.append({
                "query": query,
                "url": search.get("url", ""),
                "jobs_found": len(search.get("job_ids", [])),
            })
            detail_limit = (
                len(search.get("job_ids", []))
                if query_job_ids is not None
                else int(config.get("max_job_details_per_query", 10))
            )
            opportunity_limit = (
                len(search.get("job_ids", []))
                if query_job_ids is not None
                else int(config.get("max_opportunities_per_run", 10))
            )
            for job_id in search.get("job_ids", [])[:detail_limit]:
                job_id = str(job_id)
                if job_id in inspected:
                    continue
                inspected.add(job_id)
                details = await extractor.scrape_job(job_id)
                text = details.get("sections", {}).get("job_posting", "")
                classification = classify_job(text, config)
                if not classification:
                    continue
                company_linkedin_url, company_slug = company_reference(details)
                website = ""
                if company_slug:
                    try:
                        company = await extractor.scrape_company(company_slug, {"about"})
                        company_linkedin_url = (
                            normalize_linkedin_url(company.get("url", ""))
                            or company_linkedin_url
                        )
                        website = company_website(company)
                    except Exception:
                        # The hiring event remains valid when company-page
                        # enrichment is unavailable or rate-limited.
                        pass
                opportunities.append({
                    "job_id": job_id,
                    "job_url": details.get("url") or f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "company_linkedin_url": company_linkedin_url,
                    "company_website": website,
                    "company_domain": website_domain(website),
                    "job_description": job_description_text(text),
                    **compensation_details(text),
                    "text": text,
                    **classification,
                })
                if len(opportunities) >= opportunity_limit:
                    break
            if query_job_ids is not None or len(opportunities) >= opportunity_limit:
                break
        return {
            "searches": searches,
            "jobs_inspected": len(inspected),
            "opportunities": opportunities,
        }
    finally:
        try:
            await close_browser()
        finally:
            sys.argv = original


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--lead-sheet", type=Path, default=DEFAULT_LEAD_SHEET)
    parser.add_argument("--job-id", action="append", dest="job_ids")
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    result = asyncio.run(collect(config, args.job_ids))
    seen = set() if args.reset_state else load_seen(args.state)
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
        lead_rows.append({
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
        })

    append_csv(args.output, rows)
    lead_result = append_leads(args.lead_sheet, lead_rows)
    save_seen(args.state, seen)
    print(json.dumps({
        "status": "success",
        "searches": result["searches"],
        "jobs_inspected": result["jobs_inspected"],
        "opportunities_qualified": len(result["opportunities"]),
        "new_opportunities": len(rows),
        "duplicate_jobs_skipped": duplicate_jobs,
        "output": str(args.output),
        "state": str(args.state),
        "lead_sheet": str(args.lead_sheet),
        "lead_sheet_result": lead_result,
        "rows": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
