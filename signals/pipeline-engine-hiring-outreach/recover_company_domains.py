from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extract_contacts import CsvSheet, GoogleWorkbook, Sheet, domain_from_url, load_config, load_env_file


DEFAULT_CONFIG = Path(__file__).with_name("config.json")
RECOVERY_COLUMNS = [
    "domain_recovery_status",
    "domain_recovery_attempts",
    "domain_recovery_at",
    "domain_recovery_error",
]


class ApolloCompanyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def find(self, company_name: str) -> dict[str, str]:
        request = urllib.request.Request(
            "https://api.apollo.io/api/v1/mixed_companies/search",
            data=json.dumps({"q_organization_name": company_name, "page": 1, "per_page": 5}).encode(),
            method="POST",
            headers={"X-Api-Key": self.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        expected = " ".join(company_name.casefold().split())
        organizations = payload.get("organizations") or payload.get("accounts") or []
        ranked = sorted(
            organizations,
            key=lambda item: 0 if " ".join(str(item.get("name", "")).casefold().split()) == expected else 1,
        )
        for organization in ranked:
            website = str(organization.get("website_url") or organization.get("website") or "").strip()
            domain = str(organization.get("primary_domain") or organization.get("domain") or "").strip()
            domain = domain_from_url(domain or website)
            if domain:
                return {"company_domain": domain, "company_website": website or f"https://{domain}"}
        return {}


def recover_domains(sheet: Sheet, client: ApolloCompanyClient | None, dry_run: bool, limit: int | None) -> dict[str, Any]:
    sheet.ensure_columns(RECOVERY_COLUMNS)
    summary = {"dry_run": dry_run, "rows_seen": 0, "recovered_from_website": 0, "recovered_from_apollo": 0, "unresolved": 0, "failed": 0}
    processed = 0
    for row in sheet.rows():
        data = row.data
        if data.get("status", "").strip().casefold() not in {"opportunity_detected", "needs_company_domain"}:
            continue
        if data.get("company_domain", "").strip():
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        summary["rows_seen"] += 1
        attempts = int(data.get("domain_recovery_attempts", "0") or 0) + 1
        website = data.get("company_website", "").strip()
        recovered = {}
        if website:
            domain = domain_from_url(website)
            if domain:
                recovered = {"company_domain": domain, "company_website": website}
                summary["recovered_from_website"] += 1
        if not recovered and client is not None:
            try:
                recovered = client.find(data.get("company_name", "").strip())
                if recovered:
                    summary["recovered_from_apollo"] += 1
            except Exception as exc:
                summary["failed"] += 1
                if not dry_run:
                    sheet.update_row(row.number, {
                        "domain_recovery_status": "retryable_error",
                        "domain_recovery_attempts": str(attempts),
                        "domain_recovery_at": datetime.now(timezone.utc).isoformat(),
                        "domain_recovery_error": str(exc)[:500],
                    })
                continue
        updates = {
            "domain_recovery_status": "recovered" if recovered else "unresolved",
            "domain_recovery_attempts": str(attempts),
            "domain_recovery_at": datetime.now(timezone.utc).isoformat(),
            "domain_recovery_error": "",
        }
        if recovered:
            updates.update(recovered)
            updates["status"] = "opportunity_detected"
        else:
            summary["unresolved"] += 1
        if not dry_run:
            sheet.update_row(row.number, updates)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_env_file()
    config = load_config(args.config)
    sheet = CsvSheet(args.csv) if args.csv else GoogleWorkbook(str(config["spreadsheet_id"])).worksheet(str(config["companies_worksheet"]))
    api_key = os.environ.get("APOLLO_API_KEY", "").strip()
    client = ApolloCompanyClient(api_key) if api_key and not args.dry_run else None
    print(json.dumps(recover_domains(sheet, client, args.dry_run, args.limit), indent=2))


if __name__ == "__main__":
    main()
