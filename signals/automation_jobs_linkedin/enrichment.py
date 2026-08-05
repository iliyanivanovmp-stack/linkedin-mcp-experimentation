"""Company-domain and compensation enrichment for Automation Jobs rows."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ENRICHMENT_FIELDS = [
    "company_linkedin_url",
    "company_domain",
    "compensation_text",
    "compensation_min",
    "compensation_max",
    "compensation_currency",
    "compensation_period",
    "domain_source",
    "domain_status",
]


def load_domain_overrides(path: Path | None = None) -> dict[str, str]:
    path = path or Path(__file__).with_name("company_domain_overrides.json")
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        normalize_company_name(company): domain_from_url(domain)
        for company, domain in raw.items()
        if domain_from_url(domain)
    }


def clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines() if line.strip()]


def domain_from_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.casefold().split(":", 1)[0].removeprefix("www.")
    if not host or host.endswith("linkedin.com"):
        return ""
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    suffix = ".".join(parts[-2:])
    if suffix in {"co.uk", "com.au", "co.nz", "co.za", "com.br", "com.mx"}:
        return ".".join(parts[-3:])
    return suffix


def normalize_company_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    return " ".join(value.split())


def parse_amount(value: str) -> float | None:
    match = re.search(r"(?i)(\d[\d,.]*)(?:\s*)(k|m)?", value)
    if not match:
        return None
    raw_number = match.group(1)
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
    relevant_lines: list[str] = []
    for line in clean_lines(text):
        candidate = re.sub(r"(?i)\b401\s*\(?k\)?\b", "", line)
        amounts = re.findall(currency_pattern, candidate)
        has_period = re.search(r"(?i)(?:/|\bper\s+)(?:hr|hour|day|week|month|mo|year|yr)\b", candidate)
        has_pay_language = re.search(rf"(?i)\b(?:{pay_words})\b", candidate)
        has_pipeline_metric = re.search(
            r"(?i)\b(?:sourced\s+pipeline|pipeline\s+(?:target|quota|per\s+)|"
            r"revenue\s+(?:target|quota|per\s+)|bookings?\s+(?:target|quota|per\s+))",
            candidate,
        )
        if has_pipeline_metric and not has_pay_language:
            continue
        if (amounts and (len(amounts) >= 2 or has_period or has_pay_language)) or re.search(
            rf"(?i)\b(?:{pay_words})\b.{{0,100}}\d", candidate
        ):
            relevant_lines.append(line)

    empty = {
        "compensation_text": "",
        "compensation_min": "",
        "compensation_max": "",
        "compensation_currency": "",
        "compensation_period": "",
    }
    if not relevant_lines:
        return empty

    compensation_text = " | ".join(dict.fromkeys(relevant_lines[:5]))
    first_line = re.sub(r"(?i)\b401\s*\(?k\)?\b", "", relevant_lines[0])
    tokens = re.findall(r"(?:[$€£]\s*)?\d[\d,.]*(?:\s*[kKmM])?", first_line)
    values = [amount for token in tokens if (amount := parse_amount(token)) is not None and amount >= 10]
    lower = compensation_text.casefold()
    return {
        "compensation_text": compensation_text,
        "compensation_min": min(values) if values else "",
        "compensation_max": max(values) if values else "",
        "compensation_currency": (
            "USD" if "$" in compensation_text else "EUR" if "€" in compensation_text else "GBP" if "£" in compensation_text else ""
        ),
        "compensation_period": (
            "hour" if re.search(r"(?:\b(?:hour|hourly|per hour)\b|/hr\b)", lower)
            else "year" if re.search(r"(?:\b(?:year|annual|annually|per year)\b|/yr\b)", lower)
            else "month" if re.search(r"(?:\b(?:month|monthly|per month)\b|/mo\b)", lower)
            else "year" if values and max(values) >= 1_000 else ""
        ),
    }


class ApolloCompanyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, company_name: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            "https://api.apollo.io/api/v1/mixed_companies/search",
            data=json.dumps({"q_organization_name": company_name, "page": 1, "per_page": 10}).encode(),
            method="POST",
            headers={"X-Api-Key": self.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        return list(payload.get("organizations") or payload.get("accounts") or [])

    def find_exact(self, company_name: str) -> dict[str, str]:
        expected = normalize_company_name(company_name)
        matches: dict[str, dict[str, str]] = {}
        for organization in self.search(company_name):
            if normalize_company_name(str(organization.get("name", ""))) != expected:
                continue
            website = str(organization.get("website_url") or organization.get("website") or "").strip()
            domain = domain_from_url(str(organization.get("primary_domain") or organization.get("domain") or website))
            if domain:
                matches[domain] = {
                    "company_domain": domain,
                    "company_website": website or f"https://{domain}",
                    "domain_source": "apollo_exact_company",
                    "domain_status": "resolved",
                }
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            return {"domain_status": "ambiguous", "domain_source": "apollo_exact_company"}
        return {"domain_status": "unresolved", "domain_source": "apollo_exact_company"}


def enrich_company(
    company_name: str,
    company_website: str,
    job_description: str,
    company_linkedin_url: str = "",
    apollo: ApolloCompanyClient | None = None,
    domain_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "company_linkedin_url": str(company_linkedin_url or "").strip(),
        **compensation_details(job_description),
    }
    domain = domain_from_url(company_website)
    if domain:
        result.update({
            "company_domain": domain,
            "domain_source": "company_website",
            "domain_status": "resolved",
        })
        return result
    override_domain = (domain_overrides or {}).get(normalize_company_name(company_name), "")
    if override_domain:
        result.update({
            "company_domain": override_domain,
            "domain_source": "manual_verified_backfill",
            "domain_status": "resolved",
        })
        return result
    if apollo is not None and company_name.strip():
        try:
            result.update(apollo.find_exact(company_name))
        except Exception as exc:
            result.update({
                "company_domain": "",
                "domain_source": "apollo_exact_company",
                "domain_status": "retryable_error",
                "domain_error": f"{type(exc).__name__}: {exc}"[:500],
            })
        return result
    result.update({"company_domain": "", "domain_source": "", "domain_status": "unresolved"})
    return result
