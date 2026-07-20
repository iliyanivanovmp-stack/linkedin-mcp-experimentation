from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
DEFAULT_ENV = ROOT / ".env"
OUTPUT_COLUMNS = [
    "status",
    "lemlist_campaign",
    "lemlist_campaign_id",
    "lemlist_lead_id",
    "plugged_at",
    "lemlist_error",
]


FIELD_ALIASES = {
    "email": ["email", "work_email", "verified_email", "Email"],
    "first_name": ["first_name", "firstName", "First Name"],
    "last_name": ["last_name", "lastName", "Last Name"],
    "person_name": ["person_name", "name", "full_name", "Full Name"],
    "company_name": ["company_name", "companyName", "company", "Company"],
    "company_domain": ["company_domain", "companyDomain", "domain", "Domain"],
    "company_website": ["company_website", "website", "Website"],
    "job_title": ["job_title", "jobTitle", "headline", "title", "Title"],
    "linkedin_url": [
        "person_linkedin_url",
        "linkedin_url",
        "linkedinUrl",
        "LinkedIn URL",
    ],
    "source_url": ["source_url", "job_url", "audit_url", "Source URL"],
    "evidence": ["evidence", "outreach_reason", "signal_evidence"],
    "gap_reason": ["gap_reason", "detected_gap", "gap", "problem_detected"],
    "outreach_reason": ["outreach_reason", "opportunity_reason", "reason"],
    "opener": ["opener", "email_opener", "opening_line"],
    "solution_angle": ["solution_angle", "recommended_solution", "solution", "how_solved"],
    "icebreaker": [
        "icebreaker",
        "personalization",
        "outreach_reason",
        "integration_opportunity",
        "offer_angle",
        "evidence",
    ],
    "phone": ["phone", "Phone"],
    "timezone": ["timezone", "Timezone"],
}

CUSTOM_VARIABLE_ALIASES = {
    "icebreaker": FIELD_ALIASES["icebreaker"],
    "gapReason": FIELD_ALIASES["gap_reason"],
    "outreachReason": FIELD_ALIASES["outreach_reason"],
    "opener": FIELD_ALIASES["opener"],
    "solutionAngle": FIELD_ALIASES["solution_angle"],
    "evidence": FIELD_ALIASES["evidence"],
    "sourceUrl": FIELD_ALIASES["source_url"],
    "auditCompanyKey": ["audit_company_key"],
    "detectedAt": ["detected_at"],
    "companyWebsite": FIELD_ALIASES["company_website"],
    "companyDomain": FIELD_ALIASES["company_domain"],
    "jobTitle": FIELD_ALIASES["job_title"],
}

DEFAULT_LEMLIST_VARIABLES = {
    "email",
    "firstName",
    "lastName",
    "picture",
    "phone",
    "linkedinUrl",
    "companyName",
    "companyDomain",
    "icebreaker",
    "jobTitle",
    "timezone",
}


class Sheet(Protocol):
    headers: list[str]

    def rows(self) -> list["SheetRow"]:
        ...

    def ensure_columns(self, columns: list[str]) -> None:
        ...

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        ...


@dataclass
class SheetRow:
    number: int
    data: dict[str, str]


class CsvSheet:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.headers: list[str] = []
        self._rows: list[dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.headers = []
            self._rows = []
            return
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            self.headers = list(reader.fieldnames or [])
            self._rows = [
                {header: row.get(header, "") for header in self.headers}
                for row in reader
            ]

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(
                {header: row.get(header, "") for header in self.headers}
                for row in self._rows
            )

    def rows(self) -> list[SheetRow]:
        return [
            SheetRow(number=index + 2, data=dict(row))
            for index, row in enumerate(self._rows)
        ]

    def ensure_columns(self, columns: list[str]) -> None:
        changed = False
        for column in columns:
            if column not in self.headers:
                self.headers.append(column)
                changed = True
        if changed:
            for row in self._rows:
                for column in columns:
                    row.setdefault(column, "")
            self._write()

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        index = row_number - 2
        if index < 0 or index >= len(self._rows):
            raise IndexError(f"CSV row {row_number} is out of range")
        for column in updates:
            if column not in self.headers:
                self.headers.append(column)
        self._rows[index].update(updates)
        self._write()


class GoogleSheet:
    def __init__(self, spreadsheet_id: str, worksheet: str) -> None:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:
            raise RuntimeError(
                "Google Sheets sources require gspread and google-auth"
            ) from exc

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if service_json:
            info = json.loads(service_json)
            credentials = Credentials.from_service_account_info(info, scopes=scopes)
            client = gspread.authorize(credentials)
        else:
            credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if not credentials_path:
                raise RuntimeError(
                    "Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON"
                )
            client = gspread.service_account(filename=credentials_path)

        self.worksheet = client.open_by_key(spreadsheet_id).worksheet(worksheet)
        self.headers = list(self.worksheet.row_values(1))

    def rows(self) -> list[SheetRow]:
        values = self.worksheet.get_all_values()
        if not values:
            return []
        self.headers = list(values[0])
        rows = []
        for index, values_row in enumerate(values[1:], start=2):
            data = {
                header: values_row[column_index] if column_index < len(values_row) else ""
                for column_index, header in enumerate(self.headers)
            }
            rows.append(SheetRow(number=index, data=data))
        return rows

    def ensure_columns(self, columns: list[str]) -> None:
        missing = [column for column in columns if column not in self.headers]
        if not missing:
            return
        start = len(self.headers) + 1
        self.headers.extend(missing)
        current_cols = int(getattr(self.worksheet, "col_count", 0) or 0)
        if current_cols and len(self.headers) > current_cols:
            self.worksheet.add_cols(len(self.headers) - current_cols)
        self.worksheet.update(
            range_name=f"{column_letter(start)}1:{column_letter(len(self.headers))}1",
            values=[missing],
        )

    def update_row(self, row_number: int, updates: dict[str, str]) -> None:
        cells = []
        for column, value in updates.items():
            if column not in self.headers:
                raise ValueError(f"Missing expected column {column}")
            cells.append({
                "range": f"{column_letter(self.headers.index(column) + 1)}{row_number}",
                "values": [[value]],
            })
        if cells:
            self.worksheet.batch_update(cells)


class LemlistClient:
    def __init__(self, api_key: str, query_params: dict[str, Any]) -> None:
        self.api_key = api_key
        self.query_params = query_params

    def create_lead(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in self.query_params.items()
        })
        email = str(payload.get("email", "")).strip()
        if not email:
            raise RuntimeError("Lemlist API lead creation requires an email address")
        encoded_email = urllib.parse.quote(email)
        url = f"https://api.lemlist.com/api/campaigns/{campaign_id}/leads/{encoded_email}"
        if query:
            url = f"{url}?{query}"
        auth = base64.b64encode(f":{self.api_key}".encode()).decode()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
                "User-Agent": "linkedin-mcp-experimentation/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "ignore")
                return json.loads(body) if body else {}
        except Exception as exc:
            raise RuntimeError(read_error(exc)) from exc

    def campaign_id_by_name(self, campaign_name: str) -> str:
        auth = base64.b64encode(f":{self.api_key}".encode()).decode()
        request = urllib.request.Request(
            "https://api.lemlist.com/api/campaigns?limit=100",
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": "linkedin-mcp-experimentation/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8", "ignore"))
        except Exception as exc:
            raise RuntimeError(read_error(exc)) from exc
        campaigns = body if isinstance(body, list) else body.get("campaigns") or body.get("data") or []
        return campaign_id_from_items(campaigns, campaign_name)

    def add_custom_variables(self, lead_id: str, variables: dict[str, str]) -> dict[str, Any]:
        if not variables:
            return {"ok": True, "skipped": True}
        updated = []
        errors = []
        for name, value in variables.items():
            single_variable = {name: value}
            try:
                self._lead_variables_request("PATCH", lead_id, single_variable)
                updated.append(name)
                continue
            except RuntimeError as patch_error:
                try:
                    self._lead_variables_request("POST", lead_id, single_variable)
                    updated.append(name)
                    continue
                except RuntimeError as post_error:
                    if "already exist" in str(post_error):
                        try:
                            self._lead_variables_request("PATCH", lead_id, single_variable)
                            updated.append(name)
                            continue
                        except RuntimeError as retry_error:
                            errors.append(f"{name}: {retry_error}")
                            continue
                    errors.append(f"{name}: patch={patch_error}; post={post_error}")
        if errors:
            raise RuntimeError("; ".join(errors)[:1000])
        return {"ok": True, "updated": updated}

    def _lead_variables_request(self, method: str, lead_id: str, variables: dict[str, str]) -> dict[str, Any]:
        auth = base64.b64encode(f":{self.api_key}".encode()).decode()
        request = urllib.request.Request(
            f"https://api.lemlist.com/api/leads/{urllib.parse.quote(lead_id)}/variables",
            data=json.dumps(variables).encode(),
            method=method,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
                "User-Agent": "linkedin-mcp-experimentation/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "ignore")
                return json.loads(body) if body else {}
        except Exception as exc:
            raise RuntimeError(read_error(exc)) from exc


def column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def read_error(exc: Exception) -> str:
    if hasattr(exc, "read"):
        try:
            body = exc.read().decode("utf-8", "ignore")
            return f"{exc}: {body}"[:1000]
        except Exception:
            pass
    return str(exc)[:1000]


def campaign_id_from_items(campaigns: list[dict[str, Any]], campaign_name: str) -> str:
    expected = campaign_name.strip().casefold()
    matches = [
        str(item.get("_id") or item.get("id") or "")
        for item in campaigns
        if str(item.get("name", "") or "").strip().casefold() == expected
    ]
    matches = [value for value in matches if value]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Lemlist campaigns match exact name: {campaign_name}")
    return matches[0] if matches else ""


def is_cross_campaign_duplicate(error: str) -> bool:
    return "already in other campaign" in error.casefold()


def first_value(row: dict[str, str], aliases: list[str]) -> str:
    for key in aliases:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    lower_map = {key.casefold(): value for key, value in row.items()}
    for key in aliases:
        value = str(lower_map.get(key.casefold(), "") or "").strip()
        if value:
            return value
    return ""


def split_name(row: dict[str, str]) -> tuple[str, str]:
    first = first_value(row, FIELD_ALIASES["first_name"])
    last = first_value(row, FIELD_ALIASES["last_name"])
    if first or last:
        return first, last
    full = first_value(row, FIELD_ALIASES["person_name"])
    parts = full.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def lead_identity(row: dict[str, str]) -> str:
    email = first_value(row, FIELD_ALIASES["email"]).casefold()
    if email:
        return f"email:{email}"
    linkedin = first_value(row, FIELD_ALIASES["linkedin_url"]).rstrip("/").casefold()
    if linkedin:
        return f"linkedin:{linkedin}"
    return ""


def row_matches_campaign(row: dict[str, str], campaign_name: str) -> bool:
    row_campaign = str(row.get("lemlist_campaign", "") or "").strip()
    if not row_campaign:
        return True
    return row_campaign.casefold() == campaign_name.casefold()


def variable_aliases(source: dict[str, Any] | None = None) -> dict[str, list[str]]:
    configured = (source or {}).get("custom_variables")
    if not configured:
        return CUSTOM_VARIABLE_ALIASES
    aliases: dict[str, list[str]] = {}
    for variable_name, fields in configured.items():
        if isinstance(fields, str):
            aliases[str(variable_name)] = [fields]
        else:
            aliases[str(variable_name)] = [str(field) for field in fields]
    return aliases


def custom_variables(
    row: dict[str, str],
    aliases: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    variables = {}
    for variable_name, field_aliases in (aliases or CUSTOM_VARIABLE_ALIASES).items():
        value = first_value(row, field_aliases)
        if value:
            variables[variable_name] = value
    return variables


def custom_variables_for_lemlist(
    row: dict[str, str],
    aliases: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    return {
        key: value
        for key, value in custom_variables(row, aliases).items()
        if key not in DEFAULT_LEMLIST_VARIABLES
    }


def standard_lead_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in DEFAULT_LEMLIST_VARIABLES
    }


def build_payload(
    row: dict[str, str],
    default_timezone: str,
    aliases: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    first_name, last_name = split_name(row)
    email = first_value(row, FIELD_ALIASES["email"])
    linkedin = first_value(row, FIELD_ALIASES["linkedin_url"])
    company_name = first_value(row, FIELD_ALIASES["company_name"])
    company_domain = first_value(row, FIELD_ALIASES["company_domain"])
    company_website = first_value(row, FIELD_ALIASES["company_website"])
    source = first_value(row, FIELD_ALIASES["source_url"]) or first_value(row, FIELD_ALIASES["evidence"])
    icebreaker = first_value(row, FIELD_ALIASES["icebreaker"])

    missing = []
    if not (first_name or last_name):
        missing.append("person name")
    if not company_name:
        missing.append("company name")
    if not (company_domain or company_website):
        missing.append("company domain or website")
    if not email:
        missing.append("email")
    if not source:
        missing.append("source URL or evidence")
    if not icebreaker:
        missing.append("icebreaker/personalization")

    payload = {
        "firstName": first_name,
        "lastName": last_name,
        "email": email,
        "companyName": company_name,
        "companyDomain": company_domain or domain_from_url(company_website),
        "jobTitle": first_value(row, FIELD_ALIASES["job_title"]),
        "linkedinUrl": linkedin,
        "phone": first_value(row, FIELD_ALIASES["phone"]),
        "timezone": first_value(row, FIELD_ALIASES["timezone"]) or default_timezone,
        "icebreaker": icebreaker,
    }
    payload.update(custom_variables(row, aliases))
    return {key: value for key, value in payload.items() if value}, missing


def local_date(value: str, timezone_name: str) -> str:
    if not value.strip():
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (ValueError, TypeError, KeyError):
        return ""


def plugged_today(
    rows: list[SheetRow],
    campaign_name: str,
    timezone_name: str,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(timezone.utc)
    today = current.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    return sum(
        1
        for row in rows
        if row.data.get("status", "").strip().casefold() == "plugged"
        and row_matches_campaign(row.data, campaign_name)
        and local_date(str(row.data.get("plugged_at", "") or ""), timezone_name) == today
    )


def campaign_names_for_daily_limit_group(
    config: dict[str, Any],
    source: dict[str, Any],
    current_campaign_name: str,
) -> set[str]:
    group = str(source.get("daily_limit_group", "") or "").strip()
    if not group:
        return {current_campaign_name}
    names = set()
    for candidate in config.get("sources", []):
        if str(candidate.get("daily_limit_group", "") or "").strip() != group:
            continue
        campaign = config.get("campaigns", {}).get(candidate.get("campaign_key"), {})
        name = str(campaign.get("name", "") or "").strip()
        if name:
            names.add(name)
    return names or {current_campaign_name}


def plugged_today_for_campaigns(
    rows: list[SheetRow],
    campaign_names: set[str],
    timezone_name: str,
    now: datetime | None = None,
) -> int:
    return sum(plugged_today(rows, name, timezone_name, now) for name in campaign_names)


def domain_from_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.casefold().removeprefix("www.")


def load_env_file(path: Path = DEFAULT_ENV) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def open_sheet(source: dict[str, Any]) -> Sheet:
    source_type = source.get("type")
    if source_type == "csv":
        return CsvSheet(ROOT / str(source["path"]))
    if source_type == "google_sheet":
        return GoogleSheet(str(source["spreadsheet_id"]), str(source["worksheet"]))
    raise ValueError(f"Unsupported source type: {source_type}")


def process(
    config: dict[str, Any],
    dry_run: bool,
    limit: int | None,
    source_keys: set[str] | None = None,
) -> dict[str, Any]:
    load_env_file()
    api_key = os.environ.get(str(config.get("lemlist_api_key_env", "LEMLIST_API_KEY")), "")
    client = (
        None
        if dry_run or not api_key
        else LemlistClient(api_key, config.get("query_params", {}))
    )

    processed_keys: set[tuple[str, str]] = set()
    summary = {
        "dry_run": dry_run,
        "sources": [],
        "ready": 0,
        "plugged": 0,
        "failed": 0,
        "duplicates": 0,
    }

    for source in config["sources"]:
        if source_keys and source["key"] not in source_keys:
            continue
        campaign = config["campaigns"][source["campaign_key"]]
        campaign_name = campaign["name"]
        campaign_id = campaign.get("campaign_id", "")
        if not campaign_id and client is not None:
            campaign_id = client.campaign_id_by_name(campaign_name)
        aliases = variable_aliases(source)
        timezone_name = str(source.get("timezone") or config.get("default_timezone", "America/New_York"))
        source_result = {
            "source": source["key"],
            "campaign": campaign_name,
            "rows_seen": 0,
            "ready": 0,
            "plugged": 0,
            "failed": 0,
            "duplicates": 0,
        }
        try:
            sheet = open_sheet(source)
            if not dry_run:
                sheet.ensure_columns(OUTPUT_COLUMNS)
            rows = sheet.rows()
            source_result["rows_seen"] = len(rows)
        except Exception as exc:
            source_result["error"] = read_error(exc)
            summary["sources"].append(source_result)
            continue

        daily_limit = int(source.get("daily_limit", 0) or 0)
        daily_campaign_names = campaign_names_for_daily_limit_group(config, source, campaign_name)
        already_plugged_today = plugged_today_for_campaigns(rows, daily_campaign_names, timezone_name)
        daily_remaining = max(0, daily_limit - already_plugged_today) if daily_limit else None
        source_result["daily_limit"] = daily_limit or None
        source_result["plugged_today"] = already_plugged_today
        source_result["daily_remaining_before_run"] = daily_remaining
        source_result["daily_limit_campaigns"] = sorted(daily_campaign_names)

        existing_plugged = {
            (campaign_name, identity)
            for row in rows
            if row.data.get("status", "").strip().casefold() == "plugged"
            if (identity := lead_identity(row.data))
        }

        for row in rows:
            if limit is not None and summary["ready"] >= limit:
                break
            if daily_remaining is not None and source_result["ready"] >= daily_remaining:
                break
            status = row.data.get("status", "").strip()
            if status:
                continue
            if not row_matches_campaign(row.data, campaign_name):
                continue

            summary["ready"] += 1
            source_result["ready"] += 1
            payload, missing = build_payload(
                row.data,
                timezone_name,
                aliases,
            )
            identity = lead_identity(row.data)
            dedupe_key = (campaign_name, identity)

            base_update = {
                "lemlist_campaign": campaign_name,
                "lemlist_campaign_id": campaign_id,
                "lemlist_error": "",
            }

            if missing:
                mark_failed(sheet, row.number, base_update, f"Missing: {', '.join(missing)}", dry_run)
                summary["failed"] += 1
                source_result["failed"] += 1
                continue
            if dedupe_key in existing_plugged or dedupe_key in processed_keys:
                update = {
                    **base_update,
                    "status": "plugged",
                    "plugged_at": now_iso(),
                    "lemlist_error": "duplicate: already plugged for this campaign",
                }
                if not dry_run:
                    sheet.update_row(row.number, update)
                summary["duplicates"] += 1
                source_result["duplicates"] += 1
                continue
            if not campaign_id and not dry_run:
                mark_failed(sheet, row.number, base_update, "Missing Lemlist campaign ID", dry_run)
                summary["failed"] += 1
                source_result["failed"] += 1
                continue
            if client is None and not dry_run:
                mark_failed(sheet, row.number, base_update, "Missing LEMLIST_API_KEY", dry_run)
                summary["failed"] += 1
                source_result["failed"] += 1
                continue

            try:
                result = {"_id": "dry-run"} if dry_run else client.create_lead(campaign_id, standard_lead_payload(payload))  # type: ignore[union-attr]
                lead_id = str(result.get("_id", ""))
                if not dry_run and lead_id:
                    client.add_custom_variables(
                        lead_id,
                        custom_variables_for_lemlist(row.data, aliases),
                    )  # type: ignore[union-attr]
                update = {
                    **base_update,
                    "status": "plugged",
                    "lemlist_lead_id": lead_id,
                    "plugged_at": now_iso(),
                    "lemlist_error": "",
                }
                if not dry_run:
                    sheet.update_row(row.number, update)
                processed_keys.add(dedupe_key)
                summary["plugged"] += 1
                source_result["plugged"] += 1
            except Exception as exc:
                error = read_error(exc)
                if is_cross_campaign_duplicate(error):
                    if not dry_run:
                        sheet.update_row(row.number, {
                            **base_update,
                            "status": "skipped_existing_campaign",
                            "lemlist_error": error,
                        })
                    summary["duplicates"] += 1
                    source_result["duplicates"] += 1
                else:
                    mark_failed(sheet, row.number, base_update, error, dry_run)
                    summary["failed"] += 1
                    source_result["failed"] += 1

        summary["sources"].append(source_result)
    return summary


def mark_failed(
    sheet: Sheet,
    row_number: int,
    base_update: dict[str, str],
    error: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    sheet.update_row(row_number, {
        **base_update,
        "status": "failed",
        "lemlist_error": error[:1000],
    })


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--source", action="append", dest="sources")
    args = parser.parse_args()
    try:
        result = process(
            load_config(args.config),
            args.dry_run,
            args.limit,
            source_keys=set(args.sources or []),
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": read_error(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
