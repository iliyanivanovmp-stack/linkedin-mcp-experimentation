"""Detect companies posting AI automation contract/freelance jobs on LinkedIn."""

from __future__ import annotations

import argparse
import asyncio
import html as html_module
import json
import os
import random
import re
import sys
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from enrichment import (
    ApolloCompanyClient,
    ENRICHMENT_FIELDS,
    LemlistCompanyClient,
    enrich_company,
    load_domain_overrides,
)
from linkedin_mcp_client import LinkedInMCPClient, LinkedInMCPExtractor

ROOT = Path(__file__).resolve().parent
SIGNALS = ROOT.parent

DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_STATE = ROOT / "state" / "seen_job_ids.json"
CREDENTIALS = SIGNALS.parent / "credentials.json"

SHEET_FIELDS = [
    "detected_at",
    "company_name",
    "company_website",
    "job_title",
    "job_description",
    "job_url",
    "poster_linkedin_url",
    "job_id",
    "relevance_score",
    "relevance_signals",
    "review_status",
    "fit_rating",
    "rejection_reason",
    "applied",
    "response",
    "interview",
    "won",
    *ENRICHMENT_FIELDS,
]

LEGACY_SHEET_FIELDS = [
    "detected_at",
    "company_name",
    "company_website",
    "job_title",
    "short_description",
    "job_url",
    "poster_linkedin_url",
]

DESCRIPTION_COLUMN_WIDTH_PX = 420
DATA_ROW_HEIGHT_PX = 24


# ── text helpers ──────────────────────────────────────────────────────────────

def clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def job_identity(text: str) -> tuple[str, str]:
    """Return (company_name, job_title) from the first two lines of job posting text."""
    lines = clean_lines(text)
    return (lines[0] if lines else "", lines[1] if len(lines) > 1 else "")


def job_description(text: str) -> str:
    """Return the full job description body."""
    # Find the "About the job" marker and take everything after it
    marker = "About the job"
    idx = text.find(marker)
    body = text[idx + len(marker):].strip() if idx != -1 else ""

    # Fall back to lines after company/title if marker is absent
    if not body:
        lines = clean_lines(text)
        body = " ".join(lines[2:]) if len(lines) > 2 else ""

    lines = clean_lines(body)
    return "\n".join(lines).strip()


def html_fragment_to_text(fragment: str) -> str:
    """Convert a LinkedIn HTML fragment to readable text while preserving breaks."""
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", fragment)
    text = re.sub(r"(?i)</\s*(p|div|li|ul|ol|h[1-6]|section|strong)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    lines = clean_lines(text)
    return "\n".join(lines).strip()


class _DescriptionParser(HTMLParser):
    """Collect text from LinkedIn's description container without regex nesting bugs."""

    TARGET_CLASSES = {"show-more-less-html__markup", "description__text"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if not self.depth and classes.intersection(self.TARGET_CLASSES):
            self.depth = 1
            return
        if self.depth:
            self.depth += 1
            if tag in {"br", "p", "div", "li", "ul", "ol", "section", "h1", "h2", "h3"}:
                self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth and tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            if tag in {"p", "div", "li", "ul", "ol", "section", "h1", "h2", "h3"}:
                self.parts.append("\n")
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(clean_lines("".join(self.parts)))


def description_from_guest_html(raw: str) -> str:
    parser = _DescriptionParser()
    parser.feed(raw)
    return parser.text()


# ── relevance ────────────────────────────────────────────────────────────────

def _matching_patterns(
    text: str,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return configured weighted rules matching text, once per rule."""
    return [
        rule for rule in rules
        if re.search(str(rule.get("pattern", "")), text, re.IGNORECASE)
    ]


def evaluate_job(
    job_title: str,
    description: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one job against the candidate-derived relevance profile."""
    relevance = config.get("relevance", {})
    title = clean_lines(job_title)[0] if clean_lines(job_title) else ""
    full_text = f"{title}\n{description}"

    remote_policy = config.get("remote_policy", {})
    if remote_policy.get("required", False):
        for rule in remote_policy.get("hard_exclude_rules", []):
            pattern = str(rule.get("pattern", ""))
            if pattern and re.search(pattern, full_text, re.IGNORECASE):
                label = str(rule.get("label") or pattern)
                return {
                    "accepted": False,
                    "score": 0,
                    "positive_signals": [],
                    "negative_signals": [label],
                    "rejection_reason": f"not fully remote: {label}",
                }

    work_authorization_policy = config.get("work_authorization_policy", {})
    if work_authorization_policy.get("required", False):
        for rule in work_authorization_policy.get("hard_exclude_rules", []):
            pattern = str(rule.get("pattern", ""))
            if pattern and re.search(pattern, full_text, re.IGNORECASE):
                label = str(rule.get("label") or pattern)
                return {
                    "accepted": False,
                    "score": 0,
                    "positive_signals": [],
                    "negative_signals": [label],
                    "rejection_reason": f"work authorization incompatible: {label}",
                }

    location_policy = config.get("location_eligibility_policy", {})
    if location_policy.get("required", False):
        for rule in location_policy.get("hard_exclude_rules", []):
            pattern = str(rule.get("pattern", ""))
            if pattern and re.search(pattern, full_text, re.IGNORECASE):
                label = str(rule.get("label") or pattern)
                return {
                    "accepted": False,
                    "score": 0,
                    "positive_signals": [],
                    "negative_signals": [label],
                    "rejection_reason": f"location incompatible: {label}",
                }

    for pattern in relevance.get("hard_exclude_title_patterns", []):
        if re.search(pattern, title, re.IGNORECASE):
            return {
                "accepted": False,
                "score": 0,
                "positive_signals": [],
                "rejection_reason": f"excluded title pattern: {pattern}",
            }

    for term in config.get("exclude_title_terms", []):
        if str(term).casefold() in title.casefold():
            return {
                "accepted": False,
                "score": 0,
                "positive_signals": [],
                "rejection_reason": f"excluded title term: {term}",
            }

    for pattern in relevance.get("hard_exclude_job_patterns", []):
        if re.search(pattern, full_text, re.IGNORECASE):
            return {
                "accepted": False,
                "score": 0,
                "positive_signals": [],
                "rejection_reason": f"excluded job pattern: {pattern}",
            }

    for term in config.get("exclude_job_terms", []):
        if str(term).casefold() in full_text.casefold():
            return {
                "accepted": False,
                "score": 0,
                "positive_signals": [],
                "rejection_reason": f"excluded job term: {term}",
            }

    trainer = relevance.get("trainer", {})
    trainer_pattern = trainer.get("title_pattern", "")
    if trainer_pattern and re.search(trainer_pattern, title, re.IGNORECASE):
        for pattern in trainer.get("excluded_domain_patterns", []):
            if re.search(pattern, full_text, re.IGNORECASE):
                return {
                    "accepted": False,
                    "score": 0,
                    "positive_signals": [],
                    "rejection_reason": f"AI trainer domain mismatch: {pattern}",
                }
        allowed = [
            pattern for pattern in trainer.get("allowed_domain_patterns", [])
            if re.search(pattern, full_text, re.IGNORECASE)
        ]
        if not allowed:
            return {
                "accepted": False,
                "score": 0,
                "positive_signals": [],
                "rejection_reason": "AI trainer role has no candidate-aligned expertise domain",
            }

    title_matches = _matching_patterns(
        title, relevance.get("positive_title_rules", []),
    )
    job_matches = _matching_patterns(
        full_text, relevance.get("positive_job_rules", []),
    )
    negative_matches = _matching_patterns(
        full_text, relevance.get("negative_job_rules", []),
    )
    score = sum(
        int(rule.get("weight", 0))
        for rule in title_matches + job_matches + negative_matches
    )
    positive_signals = [
        str(rule.get("label") or rule.get("pattern"))
        for rule in title_matches + job_matches
    ]
    if remote_policy.get("required", False):
        positive_signals.append("LinkedIn remote-only filter")
    negative_signals = [
        str(rule.get("label") or rule.get("pattern")) for rule in negative_matches
    ]

    if relevance.get("require_positive_title", False) and not title_matches:
        return {
            "accepted": False,
            "score": score,
            "positive_signals": positive_signals,
            "negative_signals": negative_signals,
            "rejection_reason": "no candidate-aligned role family in title",
        }

    minimum_score = int(relevance.get("minimum_score", 0))
    if score < minimum_score:
        return {
            "accepted": False,
            "score": score,
            "positive_signals": positive_signals,
            "negative_signals": negative_signals,
            "rejection_reason": f"relevance score {score} below minimum {minimum_score}",
        }

    return {
        "accepted": True,
        "score": score,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "rejection_reason": "",
    }


def validate_config(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Validate regexes and the executable contract with the candidate profile."""
    if not config.get("search_queries"):
        raise ValueError("config.search_queries must contain at least one query")
    locations = config.get("locations")
    if (
        not isinstance(locations, list)
        or not locations
        or any(not isinstance(location, str) or not location.strip() for location in locations)
    ):
        raise ValueError("config.locations must contain at least one non-empty location")
    relevance = config.get("relevance")
    if not isinstance(relevance, dict):
        raise ValueError("config.relevance must be an object")

    remote_policy = config.get("remote_policy")
    if not isinstance(remote_policy, dict) or not remote_policy.get("required", False):
        raise ValueError("config.remote_policy.required must be true")
    configured_work_types = {
        value.strip().casefold()
        for value in str(config.get("work_type", "")).split(",")
        if value.strip()
    }
    if configured_work_types != {"remote"}:
        raise ValueError(
            "config.work_type must be exactly 'remote' while remote-only policy is required"
        )
    for rule in remote_policy.get("hard_exclude_rules", []):
        if not isinstance(rule, dict) or not rule.get("pattern"):
            raise ValueError(f"Invalid rule in remote_policy.hard_exclude_rules: {rule!r}")
        re.compile(str(rule["pattern"]), re.IGNORECASE)

    work_authorization_policy = config.get("work_authorization_policy")
    if (
        not isinstance(work_authorization_policy, dict)
        or not work_authorization_policy.get("required", False)
    ):
        raise ValueError("config.work_authorization_policy.required must be true")
    for rule in work_authorization_policy.get("hard_exclude_rules", []):
        if not isinstance(rule, dict) or not rule.get("pattern"):
            raise ValueError(
                "Invalid rule in work_authorization_policy.hard_exclude_rules: "
                f"{rule!r}"
            )
        re.compile(str(rule["pattern"]), re.IGNORECASE)

    location_policy = config.get("location_eligibility_policy")
    if (
        not isinstance(location_policy, dict)
        or not location_policy.get("required", False)
    ):
        raise ValueError("config.location_eligibility_policy.required must be true")
    for rule in location_policy.get("hard_exclude_rules", []):
        if not isinstance(rule, dict) or not rule.get("pattern"):
            raise ValueError(
                "Invalid rule in location_eligibility_policy.hard_exclude_rules: "
                f"{rule!r}"
            )
        re.compile(str(rule["pattern"]), re.IGNORECASE)

    regex_groups = (
        "hard_exclude_title_patterns", "hard_exclude_job_patterns",
    )
    for group in regex_groups:
        for pattern in relevance.get(group, []):
            re.compile(str(pattern), re.IGNORECASE)
    for group in ("positive_title_rules", "positive_job_rules", "negative_job_rules"):
        for rule in relevance.get(group, []):
            if not isinstance(rule, dict) or not rule.get("pattern"):
                raise ValueError(f"Invalid rule in relevance.{group}: {rule!r}")
            re.compile(str(rule["pattern"]), re.IGNORECASE)
            int(rule.get("weight", 0))
    trainer = relevance.get("trainer", {})
    for pattern in (
        [trainer.get("title_pattern", "")]
        + trainer.get("allowed_domain_patterns", [])
        + trainer.get("excluded_domain_patterns", [])
    ):
        if pattern:
            re.compile(str(pattern), re.IGNORECASE)

    profile_path = config_path.parent / str(relevance.get("source_profile", ""))
    if not profile_path.is_file():
        raise FileNotFoundError(f"Relevance source profile not found: {profile_path}")
    profile_text = profile_path.read_text()
    schema_match = re.search(r"(?m)^schema_version:\s*(\d+)\s*$", profile_text)
    updated_match = re.search(r'(?m)^updated:\s*["\']?([^"\'\n]+)', profile_text)
    profile = {
        "schema_version": int(schema_match.group(1)) if schema_match else None,
        "updated": updated_match.group(1).strip() if updated_match else "",
    }
    if profile["schema_version"] != 1:
        raise ValueError(f"Unsupported candidate profile schema: {profile_path}")

    uncovered = []
    for example in relevance.get("profile_coverage_examples", []):
        result = evaluate_job(str(example.get("title", "")), str(example.get("description", "")), config)
        if not result["accepted"]:
            uncovered.append({"title": example.get("title"), "reason": result["rejection_reason"]})
    if uncovered:
        raise ValueError(f"Candidate profile coverage examples rejected by config: {uncovered}")
    return profile


# ── LinkedIn data helpers ─────────────────────────────────────────────────────

def normalize_linkedin_url(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("/"):
        value = f"https://www.linkedin.com{value}"
    return value.rstrip("/") + "/" if value else ""


def company_slug_from_details(details: dict[str, Any]) -> tuple[str, str]:
    """Return (company_linkedin_url, slug) from job detail references."""
    for ref in details.get("references", {}).get("job_posting", []):
        if ref.get("kind") != "company":
            continue
        url = normalize_linkedin_url(str(ref.get("url", "")))
        match = re.search(r"/company/([^/?#]+)", url)
        return url, match.group(1) if match else ""
    return "", ""


def poster_url_from_details(details: dict[str, Any]) -> str:
    for ref in details.get("references", {}).get("job_posting", []):
        if ref.get("kind") == "person":
            return normalize_linkedin_url(str(ref.get("url", "")))
    return ""


async def poster_url_from_loaded_page(page: Any) -> str:
    """Read the contact from the job page already loaded by scrape_job()."""
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


def poster_url_from_guest_html(raw: str) -> str:
    """Extract the hiring-team member profile when the public job card exposes it."""
    # Scope profile matching to recruiter markup so unrelated /in/ links from
    # navigation and recommendations are not attributed to the job.
    card_patterns = (
        r'<(?:section|div)[^>]*class="[^"]*(?:hirer-card|hiring-team|message-the-recruiter)[^"]*"[^>]*>(.*?)</(?:section|div)>',
        r'(?:(?:Meet|Contact|Message)\s+the\s+hiring\s+team|Who you can reach out to)(.{0,4000})',
    )
    for card_pattern in card_patterns:
        card = re.search(card_pattern, raw, re.DOTALL | re.IGNORECASE)
        if not card:
            continue
        profile = re.search(
            r'href=["\']((?:https://(?:www\.)?linkedin\.com)?/in/[^"\'?#]+)',
            card.group(1),
            re.IGNORECASE,
        )
        if profile:
            return normalize_linkedin_url(html_module.unescape(profile.group(1)))
    return ""


def website_from_company(company: dict[str, Any]) -> str:
    for ref in company.get("references", {}).get("about", []):
        if ref.get("kind") == "external":
            return str(ref.get("url", "")).strip()
    return ""


def company_slug_from_url(url: str) -> str:
    match = re.search(r"/company/([^/?#]+)", normalize_linkedin_url(url))
    return match.group(1) if match else ""


def unwrap_linkedin_redirect(url: str) -> str:
    import urllib.parse

    if "linkedin.com/redir/redirect" not in url:
        return url.strip()
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    target = query.get("url", [""])[0]
    return urllib.parse.unquote(target).strip()


async def website_from_public_company_page(company_url: str) -> str:
    """Fetch a public LinkedIn company page and extract the external website."""
    if not company_url:
        return ""

    slug = company_slug_from_url(company_url)
    if not slug:
        return ""

    url = f"https://www.linkedin.com/company/{slug}"
    try:
        raw = await asyncio.to_thread(_http_get, url)
    except Exception:
        return ""

    raw = html_module.unescape(raw)
    patterns = [
        r'data-tracking-control-name="about_website"[^>]*href="([^"]+)"',
        r'data-test-id="about-us__website".*?<a[^>]+href="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if match:
            return unwrap_linkedin_redirect(match.group(1))
    return ""


# ── state ─────────────────────────────────────────────────────────────────────

def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Deduplication state is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("job_ids", []), list):
        raise RuntimeError(f"Deduplication state has an invalid schema: {path}")
    return {str(jid) for jid in payload.get("job_ids", [])}


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "job_ids": sorted(seen),
    }, indent=2)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


# ── Google Sheets ─────────────────────────────────────────────────────────────

def filter_new_sheet_rows(
    rows: list[dict[str, Any]],
    header: list[str],
    sheet_values: list[list[str]],
) -> tuple[list[dict[str, Any]], int]:
    """Remove rows already delivered to the Sheet or repeated in this batch."""
    job_id_index = header.index("job_id") if "job_id" in header else None
    job_url_index = header.index("job_url") if "job_url" in header else None
    existing_ids: set[str] = set()
    existing_urls: set[str] = set()

    for values in sheet_values[1:]:
        if job_id_index is not None and job_id_index < len(values):
            job_id = values[job_id_index].strip()
            if job_id:
                existing_ids.add(job_id)
        if job_url_index is not None and job_url_index < len(values):
            job_url = values[job_url_index].strip()
            if job_url:
                existing_urls.add(job_url)

    new_rows: list[dict[str, Any]] = []
    duplicates_skipped = 0
    for row in rows:
        job_id = str(row.get("job_id", "")).strip()
        job_url = str(row.get("job_url", "")).strip()
        if (job_id and job_id in existing_ids) or (job_url and job_url in existing_urls):
            duplicates_skipped += 1
            continue
        if job_id:
            existing_ids.add(job_id)
        if job_url:
            existing_urls.add(job_url)
        new_rows.append(row)

    return new_rows, duplicates_skipped


def write_rows_to_canonical_columns(
    ws: Any,
    rows: list[dict[str, Any]],
    header: list[str],
    start_row: int,
) -> None:
    """Write rows into the header's A-based columns without table auto-detection."""
    if not rows:
        return
    end_row = start_row + len(rows) - 1
    end_column = _column_letter(len(header))
    ws.update(
        values=[[str(row.get(field, "")) for field in header] for row in rows],
        range_name=f"A{start_row}:{end_column}{end_row}",
        value_input_option="RAW",
    )


def append_to_sheet(rows: list[dict[str, Any]], creds_path: Path) -> dict[str, Any]:
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    gc = gspread.authorize(creds)

    sheet_id = os.environ.get("AUTOMATION_JOBS_SHEET_ID", "")
    if sheet_id:
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
    else:
        sh = gc.create("Automation Job Opportunities")
        ws = sh.sheet1
        ws.append_row(SHEET_FIELDS)
        print(f"[sheet_created] Set AUTOMATION_JOBS_SHEET_ID={sh.id}", file=sys.stderr)

    sheet_values = ws.get_all_values()
    header = sheet_values[0] if sheet_values else []
    if not header:
        ws.append_row(SHEET_FIELDS)
        header = SHEET_FIELDS[:]
    elif header[:len(LEGACY_SHEET_FIELDS)] == LEGACY_SHEET_FIELDS:
        ws.update("A1:G1", [SHEET_FIELDS[:len(LEGACY_SHEET_FIELDS)]])
        header = SHEET_FIELDS[:len(LEGACY_SHEET_FIELDS)]

    populated_width = max((len(row) for row in sheet_values), default=len(header))
    if len(header) < populated_width:
        placeholder_fields = [
            f"legacy_unlabeled_{index}"
            for index in range(len(header) + 1, populated_width + 1)
        ]
        start = len(header) + 1
        ws.update(
            f"{_column_letter(start)}1:{_column_letter(populated_width)}1",
            [placeholder_fields],
        )
        header.extend(placeholder_fields)

    missing_fields = [field for field in SHEET_FIELDS if field not in header]
    if missing_fields:
        start = len(header) + 1
        end = len(header) + len(missing_fields)
        ws.update(f"{_column_letter(start)}1:{_column_letter(end)}1", [missing_fields])
        header.extend(missing_fields)

    new_rows, duplicates_skipped = filter_new_sheet_rows(rows, header, sheet_values)
    if new_rows:
        write_rows_to_canonical_columns(
            ws,
            new_rows,
            header,
            start_row=len(sheet_values) + 1,
        )

    try:
        format_sheet_layout(ws)
    except Exception as exc:
        print(f"[sheet_format_warning] {exc}", file=sys.stderr)

    return {
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sh.id}",
        "rows_written": len(new_rows),
        "duplicates_skipped": duplicates_skipped,
    }


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def format_sheet_layout(ws: Any) -> None:
    """Keep full descriptions present without expanding every row vertically."""
    header = ws.row_values(1)
    if "job_description" not in header:
        return

    description_col = header.index("job_description")
    data_row_count = len(ws.get_all_values())
    requests: list[dict[str, Any]] = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,
                    "endRowIndex": ws.row_count,
                    "startColumnIndex": description_col,
                    "endColumnIndex": description_col + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "wrapStrategy": "CLIP",
                        "verticalAlignment": "TOP",
                    }
                },
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": description_col,
                    "endIndex": description_col + 1,
                },
                "properties": {"pixelSize": DESCRIPTION_COLUMN_WIDTH_PX},
                "fields": "pixelSize",
            }
        },
    ]

    if data_row_count > 1:
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": data_row_count,
                },
                "properties": {"pixelSize": DATA_ROW_HEIGHT_PX},
                "fields": "pixelSize",
            }
        })

    ws.spreadsheet.batch_update({"requests": requests})


# ── Slack ─────────────────────────────────────────────────────────────────────

def send_slack(webhook_url: str, new_count: int, sheet_url: str) -> None:
    import urllib.request

    if new_count > 0:
        text = (
            f":robot_face: *Automation Job Signal* — {new_count} new job"
            f"{'s' if new_count != 1 else ''} found today."
        )
        if sheet_url:
            text += f"\n:link: <{sheet_url}|View Google Sheet>"
    else:
        text = ":robot_face: *Automation Job Signal* — No new jobs found today."

    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)


# ── Guest API helpers (no auth required) ─────────────────────────────────────

_DATE_POSTED_MAP = {
    "past_24_hours": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
}
_SORT_BY_MAP = {"date": "DD", "relevance": "R"}
_JOB_TYPE_MAP = {
    "full_time": "F", "part_time": "P", "contract": "C", "temporary": "T",
    "internship": "I", "volunteer": "V", "other": "O",
}
_WORK_TYPE_MAP = {"onsite": "1", "remote": "2", "hybrid": "3"}
_PAGE_SIZE = 25
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _http_get(url: str) -> str:
    import time
    import urllib.error
    import urllib.request

    attempts = 4
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == attempts - 1:
                raise
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            try:
                delay = min(60.0, max(1.0, float(retry_after)))
            except ValueError:
                delay = min(60.0, 5.0 * (2 ** attempt) + random.uniform(0, 2))
            print(
                f"LinkedIn HTTP {exc.code}; retrying in {delay:.1f}s "
                f"(attempt {attempt + 2}/{attempts})",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError("HTTP retry loop exited unexpectedly")


async def wait_between_searches(config: dict[str, Any], query_index: int) -> None:
    """Pause before every search after the first to avoid back-to-back requests."""
    if query_index == 0:
        return
    minimum = int(config.get("inter_search_delay_min_seconds", 0))
    maximum = int(config.get("inter_search_delay_max_seconds", minimum))
    maximum = max(minimum, maximum)
    override = os.environ.get("INTER_SEARCH_DELAY_SECONDS")
    delay = float(override) if override is not None else random.uniform(minimum, maximum)
    if delay > 0:
        print(f"Waiting {delay:.0f}s before search {query_index + 1}", file=sys.stderr)
        await asyncio.sleep(delay)


def configured_search_targets(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Expand every expertise lane across every explicitly targeted location."""
    return [
        (str(query), str(location))
        for query in config.get("search_queries", [])
        for location in config.get("locations", [])
    ]


def interleave_job_groups(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Round-robin query results so each search lane contributes to the final ten."""
    combined: list[dict[str, Any]] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                combined.append(group[index])
    return combined


# ── LinkedIn collection ───────────────────────────────────────────────────────

async def collect(config: dict[str, Any]) -> dict[str, Any]:
    candidate_groups: list[list[dict[str, Any]]] = []
    jobs: list[dict[str, Any]] = []
    inspected: set[str] = set()
    searches = []
    evaluations: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    max_jobs = int(config.get("max_jobs_per_run", 10))
    fetch_limit = max_jobs * int(config.get("candidate_fetch_multiplier", 3))
    client = LinkedInMCPClient()

    try:
        extractor = LinkedInMCPExtractor(client)

        for search_index, (query, location) in enumerate(configured_search_targets(config)):
            await wait_between_searches(config, search_index)
            search = await extractor.search_jobs(
                query,
                location=location,
                max_pages=int(config.get("max_pages", 1)),
                date_posted=config.get("date_posted"),
                job_type=config.get("job_type"),
                work_type=config.get("work_type"),
                sort_by=config.get("sort_by", "date"),
            )
            searches.append({
                "query": query,
                "location": location,
                "url": search.get("url", ""),
                "jobs_found": len(search.get("job_ids", [])),
            })
            candidate_groups.append([
                {
                    "job_id": str(job_id),
                    "search_lane": search_index + 1,
                    "search_location": location,
                }
                for job_id in search.get("job_ids", [])
            ])

        # Search every configured lane first, then inspect a single globally
        # bounded, round-robin candidate queue. The old implementation applied
        # fetch_limit to every lane and could make hundreds of browser calls,
        # causing the scheduled Modal function to hit its 20-minute timeout.
        for candidate in interleave_job_groups(candidate_groups):
            job_id = candidate["job_id"]
            if job_id in inspected:
                continue
            if len(inspected) >= fetch_limit:
                break
            inspected.add(job_id)

            try:
                details = await extractor.scrape_job(job_id)
            except Exception as exc:
                failures.append({
                    "job_id": job_id,
                    "stage": "details",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            text = details.get("sections", {}).get("job_posting", "")
            if not text.strip():
                failures.append({
                    "job_id": job_id, "stage": "parse", "error": "missing job posting text",
                })
                continue

            company_name, job_title = job_identity(text)
            # The browser payload includes LinkedIn's workplace/location header
            # before "About the job". Evaluate the full posting so a Hybrid or
            # On-site label cannot be hidden by description-only extraction.
            evaluation = evaluate_job(job_title, text, config)
            evaluations.append({
                "job_id": job_id,
                "job_title": job_title,
                **evaluation,
            })
            if not evaluation["accepted"]:
                continue

            company_linkedin_url, _ = company_slug_from_details(details)
            jobs.append({
                "job_id": job_id,
                "job_url": details.get("url") or f"https://www.linkedin.com/jobs/view/{job_id}/",
                "company_name": company_name,
                # Domain recovery is handled after ranking by the existing
                # Apollo/exact-company enrichment path. Avoiding a second slow
                # LinkedIn company-page call keeps the daily job bounded.
                "company_website": "",
                "company_linkedin_url": company_linkedin_url,
                "job_title": job_title,
                "text": text,
                "poster_linkedin_url": poster_url_from_details(details),
                "relevance_score": evaluation["score"],
                "relevance_signals": evaluation["positive_signals"],
                "negative_signals": evaluation.get("negative_signals", []),
                "search_lane": candidate["search_lane"],
                "search_location": candidate["search_location"],
            })

        parse_failures = sum(1 for failure in failures if failure["stage"] == "parse")
        if inspected and parse_failures == len(inspected):
            raise RuntimeError(
                f"LinkedIn returned {len(inspected)} job IDs but every browser detail parse failed"
            )
        if not inspected:
            raise RuntimeError(
                "Central LinkedIn MCP returned zero job IDs across all configured searches"
            )
        return {
            "searches": searches,
            "jobs_inspected": len(inspected),
            "jobs": jobs,
            "evaluations": evaluations,
            "health": {
                "collector": "central_linkedin_mcp",
                "detail_failures": sum(
                    1 for failure in failures if failure["stage"] in {"details", "parse"}
                ),
                "failures": failures,
            },
        }
    finally:
        client.close()


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="AI automation job signal")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--credentials", type=Path, default=CREDENTIALS)
    parser.add_argument("--reset-state", action="store_true",
                        help="Ignore seen job IDs from previous runs")
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    profile = validate_config(config, args.config)
    source_profile = config.get("relevance", {}).get("source_profile", "")
    result = asyncio.run(collect(config))
    lemlist_key = os.environ.get("LEMLIST_API_KEY", "").strip()
    lemlist = LemlistCompanyClient(lemlist_key) if lemlist_key else None
    apollo_key = os.environ.get("APOLLO_API_KEY", "").strip()
    apollo = ApolloCompanyClient(apollo_key) if apollo_key else None
    domain_overrides = load_domain_overrides()

    historical_seen = load_seen(args.state)
    comparison_seen = set() if args.reset_state else set(historical_seen)
    detected_at = datetime.now(timezone.utc).isoformat()
    max_jobs = int(config.get("max_jobs_per_run", 10))
    rows: list[dict[str, Any]] = []
    duplicates_skipped = 0

    ranked_jobs = sorted(
        result["jobs"],
        key=lambda job: int(job.get("relevance_score", 0)),
        reverse=True,
    )
    selected_jobs: list[dict[str, Any]] = []

    for job in ranked_jobs:
        job_id = job["job_id"]
        if job_id in comparison_seen:
            duplicates_skipped += 1
            continue
        comparison_seen.add(job_id)
        selected_jobs.append({
            "job_id": job_id,
            "job_title": job["job_title"],
            "relevance_score": job.get("relevance_score", 0),
            "relevance_signals": job.get("relevance_signals", []),
            "negative_signals": job.get("negative_signals", []),
            "search_lane": job.get("search_lane"),
        })
        description = job_description(job["text"])
        enrichment = enrich_company(
            job["company_name"],
            job.get("company_website", ""),
            description,
            job.get("company_linkedin_url", ""),
            lemlist=lemlist,
            apollo=apollo,
            domain_overrides=domain_overrides,
        )
        rows.append({
            "detected_at": detected_at,
            "company_name": job["company_name"],
            "company_website": job["company_website"],
            "job_title": job["job_title"],
            "job_description": description,
            "job_url": job["job_url"],
            "poster_linkedin_url": job.get("poster_linkedin_url", ""),
            "job_id": job_id,
            "relevance_score": job.get("relevance_score", 0),
            "relevance_signals": ", ".join(job.get("relevance_signals", [])),
            **enrichment,
        })
        if len(rows) >= max_jobs:
            break

    sheet_url = ""
    sheet_rows_written = 0
    sheet_duplicates_skipped = 0
    delivery_status = "no_new_rows"
    delivered_ids: set[str] = set()
    if rows and args.credentials.exists():
        sheet_delivery = append_to_sheet(rows, args.credentials)
        sheet_url = str(sheet_delivery["sheet_url"])
        sheet_rows_written = int(sheet_delivery["rows_written"])
        sheet_duplicates_skipped = int(sheet_delivery["duplicates_skipped"])
        delivered_ids = {str(row["job_id"]) for row in rows}
        save_seen(args.state, historical_seen | delivered_ids)
        delivery_status = "delivered"
    elif rows:
        delivery_status = "preview_not_delivered"
    else:
        save_seen(args.state, historical_seen)

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    slack_status = "not_configured"
    if webhook_url and delivery_status != "preview_not_delivered":
        try:
            send_slack(webhook_url, len(rows), sheet_url)
            slack_status = "sent"
        except Exception as exc:
            slack_status = f"failed: {type(exc).__name__}: {exc}"
            print(f"[slack_warning] {slack_status}", file=sys.stderr)

    print(json.dumps({
        "status": "success" if delivery_status != "preview_not_delivered" else "preview",
        "delivery_status": delivery_status,
        "slack_status": slack_status,
        "searches": result["searches"],
        "jobs_inspected": result["jobs_inspected"],
        "new_jobs": len(rows),
        "duplicates_skipped": duplicates_skipped,
        "sheet_rows_written": sheet_rows_written,
        "sheet_duplicates_skipped": sheet_duplicates_skipped,
        "health": result.get("health", {}),
        "relevance": {
            "source_profile": source_profile,
            "profile_updated": profile.get("updated"),
            "minimum_score": config.get("relevance", {}).get("minimum_score", 0),
            "accepted_candidates": sum(
                1 for item in result.get("evaluations", []) if item["accepted"]
            ),
            "rejected_candidates": sum(
                1 for item in result.get("evaluations", []) if not item["accepted"]
            ),
            "selected": selected_jobs,
            "rejected": [
                {
                    "job_id": item["job_id"],
                    "job_title": item["job_title"],
                    "score": item["score"],
                    "reason": item["rejection_reason"],
                }
                for item in result.get("evaluations", []) if not item["accepted"]
            ],
        },
        "sheet_url": sheet_url,
        "rows": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
