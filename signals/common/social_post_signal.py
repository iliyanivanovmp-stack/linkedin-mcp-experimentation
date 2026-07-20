"""Reusable conservative social-post signal runner.

Production search is delegated to a configured HTTP endpoint. The endpoint must
return either {"posts": [...]} or a JSON list of normalized posts.
Only posts passing every configured rule are appended to the signal sheet.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIELDS = [
    "signal_type",
    "detected_at",
    "person_name",
    "person_linkedin_url",
    "current_role",
    "company_name",
    "company_domain",
    "company_linkedin_url",
    "evidence_text",
    "source_url",
    "signal_date",
    "keyword",
    "confidence",
    "limitations",
]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def build_search_query(config: dict[str, Any]) -> str:
    phrases = config.get("search_phrases") or []
    tools = config.get("tools") or []
    if phrases and tools:
        if config.get("primary_search_term"):
            tool_group = " OR ".join(tool.strip() for tool in tools)
            return f'{config["primary_search_term"].strip()} ({tool_group})'
        if config.get("group_boolean_terms"):
            phrase_group = " OR ".join(f'"{phrase.strip()}"' for phrase in phrases)
            tool_group = " OR ".join(tool.strip() for tool in tools)
            return f"({phrase_group}) AND ({tool_group})"
        alternatives = [
            f'"{phrase.strip()} {tool.strip()}"'
            for tool in tools
            for phrase in phrases
            if phrase.strip() and tool.strip()
        ]
        if not alternatives:
            raise ValueError("search_phrases and tools cannot contain only blank values")
        return f"({' OR '.join(alternatives)})"
    return normalize(config.get("keyword"))


def fetch_posts(config: dict[str, Any]) -> list[dict[str, Any]]:
    endpoint = os.getenv("SOCIAL_POST_SEARCH_URL", "").strip()
    token = os.getenv("SOCIAL_POST_SEARCH_TOKEN", "").strip()
    if not endpoint:
        raise RuntimeError(
            "Set SOCIAL_POST_SEARCH_URL to the configured cloud social-post "
            "search endpoint, or pass --input-json for an offline/provider test."
        )
    body = json.dumps(
        {
            "keyword": build_search_query(config),
            "date_posted": config.get("date_posted", "past-month"),
            "sort_by": config.get("sort_by", "top-match"),
            "limit": int(config.get("limit", 10)),
            "exact_keyword_match": bool(config.get("exact_keyword_match", False)),
            "filters": config.get("search_filters", {}),
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode())
    return payload.get("posts", payload) if isinstance(payload, dict) else payload


def normalize(value: str | None) -> str:
    return (value or "").strip()


def first_employer(post: dict[str, Any]) -> dict[str, Any]:
    employers = post.get("person_details", {}).get("current_employers") or []
    return employers[0] if employers else {}


def is_valid(post: dict[str, Any], config: dict[str, Any]) -> tuple[bool, list[str]]:
    text = normalize(post.get("text"))
    lower = text.casefold()
    reasons: list[str] = []
    person = post.get("person_details") or {}
    employer = first_employer(post)
    location = normalize(person.get("person_location")).casefold()
    title = normalize(employer.get("employee_title")).casefold()
    company_size = normalize(
        (post.get("company_details") or {}).get("company_size")
    )

    if config.get("require_person", True) and post.get("actor_type") != "person":
        reasons.append("not a person-authored post")
    if config.get("first_person_required") and not any(
        phrase in lower for phrase in config.get("first_person_phrases", [])
    ):
        reasons.append("not first-person evidence")
    if config.get("required_text_any") and not any(
        phrase.casefold() in lower for phrase in config["required_text_any"]
    ):
        reasons.append("required evidence phrase missing")
    if config.get("required_tool_any") and not any(
        tool.casefold() in lower for tool in config["required_tool_any"]
    ):
        reasons.append("configured tool missing")
    if any(phrase.casefold() in lower for phrase in config.get("exclude_text_any", [])):
        reasons.append("seller or promotional language")
    if config.get("allowed_location_terms") and not any(
        term.casefold() in location for term in config["allowed_location_terms"]
    ):
        reasons.append("outside target geography")
    if config.get("excluded_location_terms") and any(
        term.casefold() in location for term in config["excluded_location_terms"]
    ):
        reasons.append("excluded geography")
    if config.get("allowed_title_terms") and not any(
        term.casefold() in title for term in config["allowed_title_terms"]
    ):
        reasons.append("wrong role")
    if config.get("excluded_title_terms") and any(
        term.casefold() in title for term in config["excluded_title_terms"]
    ):
        reasons.append("excluded seller role")
    if config.get("allowed_company_sizes") and company_size and company_size not in config["allowed_company_sizes"]:
        reasons.append("wrong company size")
    return not reasons, reasons


def append_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_urls: set[tuple[str, str]] = set()
    if path.exists() and path.stat().st_size:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            existing_urls = {
                (row.get("signal_type", ""), row.get("source_url", ""))
                for row in csv.DictReader(handle)
            }
    fresh = [
        row
        for row in rows
        if (row["signal_type"], row["source_url"]) not in existing_urls
    ]
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(fresh)


def run(config_path: Path, output: Path, input_json: Path | None) -> dict[str, Any]:
    config = load_json(config_path)
    search_query = build_search_query(config)
    payload = load_json(input_json) if input_json else fetch_posts(config)
    posts = payload.get("posts", payload) if isinstance(payload, dict) else payload
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    detected_at = datetime.now(timezone.utc).isoformat()

    for post in posts:
        valid, reasons = is_valid(post, config)
        if not valid:
            rejected.append({"source_url": post.get("share_url", ""), "reasons": reasons})
            continue
        person = post.get("person_details") or {}
        company = post.get("company_details") or {}
        employer = first_employer(post)
        accepted.append(
            {
                "signal_type": config["signal_type"],
                "detected_at": detected_at,
                "person_name": normalize(person.get("person_name") or post.get("actor_name")),
                "person_linkedin_url": normalize(person.get("person_linkedin_flagship_profile_url")),
                "current_role": normalize(employer.get("employee_title")),
                "company_name": normalize(employer.get("employer_name") or company.get("company_name")),
                "company_domain": normalize(company.get("company_domain")),
                "company_linkedin_url": normalize(company.get("company_linkedin_url")),
                "evidence_text": normalize(post.get("text")),
                "source_url": normalize(post.get("share_url")),
                "signal_date": normalize(post.get("date_posted")),
                "keyword": search_query,
                "confidence": config.get("default_confidence", "medium"),
                "limitations": config.get("limitations", ""),
            }
        )
        if len(accepted) >= int(config.get("max_accepted", 1)):
            break

    append_rows(output, accepted)
    return {
        "signal_type": config["signal_type"],
        "search_query": search_query,
        "posts_checked": len(posts),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "output": str(output),
        "rejections": rejected,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-json", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output, args.input_json), indent=2))


if __name__ == "__main__":
    main()
