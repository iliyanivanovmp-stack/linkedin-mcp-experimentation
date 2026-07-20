"""Track new commenters on recent LinkedIn posts from competitor profiles.

Read-only behavior:
- Opens a competitor's recent activity page.
- Opens existing comment threads.
- Reads visible comments and commenter profile links.
- Never likes, comments, follows, connects, or sends messages.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "common"))
from lead_sheet import append_leads  # noqa: E402

DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_STATE = ROOT / "state" / "exported_profiles.json"
DEFAULT_SHARED_SHEET = ROOT.parent / "exports" / "competitor_engagement_leads.csv"
DEFAULT_LEAD_SHEET = ROOT.parent / "exports" / "pipeline_leads.csv"

CSV_FIELDS = [
    "signal_type",
    "detected_at",
    "competitor_name",
    "competitor_profile_url",
    "source_post_url",
    "source_post_age",
    "commenter_name",
    "commenter_headline",
    "commenter_linkedin_url",
    "comment_age",
    "comment_text",
    "reaction_type",
]


@dataclass(frozen=True)
class CommenterSignal:
    signal_type: str
    detected_at: str
    competitor_name: str
    competitor_profile_url: str
    source_post_url: str
    source_post_age: str
    commenter_name: str
    commenter_headline: str
    commenter_linkedin_url: str
    comment_age: str
    comment_text: str
    reaction_type: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export new commenters from recent competitor LinkedIn posts."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--shared-sheet",
        type=Path,
        default=DEFAULT_SHARED_SHEET,
        help="Append every new lead to this shared CSV sheet.",
    )
    parser.add_argument("--lead-sheet", type=Path, default=DEFAULT_LEAD_SHEET)
    parser.add_argument(
        "--profile-url",
        action="append",
        dest="profile_urls",
        help="Override config profiles. Repeat for multiple competitors.",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Forget previously exported profiles before this run.",
    )
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_profile_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return f"https://www.linkedin.com{path}"


def profile_slug(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "in":
        raise ValueError(f"Expected a LinkedIn person URL, got: {url}")
    return parts[1]


def recent_activity_url(url: str) -> str:
    return f"https://www.linkedin.com/in/{profile_slug(url)}/recent-activity/all/"


def age_in_days(label: str) -> float | None:
    value = label.strip().lower().replace("edited", "").strip(" •")
    match = re.fullmatch(r"(\d+)\s*(m|h|d|w|mo|yr)", value)
    if not match:
        return None
    number = int(match.group(1))
    unit = match.group(2)
    return {
        "m": number / 1440,
        "h": number / 24,
        "d": float(number),
        "w": float(number * 7),
        "mo": float(number * 30),
        "yr": float(number * 365),
    }[unit]


def extract_relative_age(text: str) -> str:
    for line in text.splitlines()[:12]:
        cleaned = line.strip().replace("Edited", "").strip(" •")
        if re.fullmatch(r"\d+\s*(?:m|h|d|w|mo|yr)", cleaned, re.IGNORECASE):
            return cleaned
    return ""


def parse_actor_text(actor_text: str) -> tuple[str, str]:
    lines = [line.strip() for line in actor_text.splitlines() if line.strip()]
    if not lines:
        return "", ""
    name = lines[0]
    headline_lines = [
        line
        for line in lines[1:]
        if not re.fullmatch(r"•?\s*(?:1st|2nd|3rd\+?)", line)
        and not line.lower().startswith("view ")
    ]
    return name, " ".join(headline_lines)


def parse_comment_text(article_text: str, actor_text: str, age: str) -> str:
    text = article_text
    if actor_text and text.startswith(actor_text):
        text = text[len(actor_text) :]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and age and lines[0] == age:
        lines.pop(0)
    while lines and lines[-1].lower() in {"like", "reply"}:
        lines.pop()
    return "\n".join(lines).strip()


def load_seen(path: Path, reset: bool) -> set[str]:
    if reset or not path.exists():
        return set()
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return {normalize_profile_url(url) for url in payload.get("profile_urls", [])}


def load_shared_seen(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            normalize_profile_url(row["commenter_linkedin_url"])
            for row in csv.DictReader(handle)
            if row.get("commenter_linkedin_url")
        }


def load_shared_seen_names(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["commenter_name"].strip().casefold()
            for row in csv.DictReader(handle)
            if row.get("commenter_name")
        }


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "profile_urls": sorted(seen),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_csv(path: Path, rows: list[CommenterSignal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


async def load_more_comments(container: Any, max_clicks: int) -> None:
    for _ in range(max_clicks):
        buttons = container.locator("button").filter(
            has_text=re.compile(r"^Load more comments$", re.IGNORECASE)
        )
        if await buttons.count() == 0:
            return
        button = buttons.first
        if not await button.is_visible():
            return
        await button.click(timeout=3000)
        await asyncio.sleep(1.5)


async def scan_profile(
    page: Any,
    competitor_profile_url: str,
    config: dict[str, Any],
) -> list[CommenterSignal]:
    activity_url = recent_activity_url(competitor_profile_url)
    await page.goto(activity_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    comment_buttons = page.locator("main button[aria-label*='comments on' i]")
    button_count = min(
        await comment_buttons.count(), int(config["max_posts_per_profile"])
    )
    competitor_name = profile_slug(competitor_profile_url)
    competitor_links = page.locator(
        f"main a[href*='/in/{profile_slug(competitor_profile_url)}']"
    )
    competitor_actor_texts = [
        (await competitor_links.nth(i).inner_text()).strip()
        for i in range(await competitor_links.count())
    ]
    competitor_actor_texts = [text for text in competitor_actor_texts if text]
    if competitor_actor_texts:
        competitor_name = parse_actor_text(max(competitor_actor_texts, key=len))[0]
    signals: list[CommenterSignal] = []
    detected_at = datetime.now(timezone.utc).isoformat()

    for index in range(button_count):
        comment_button = comment_buttons.nth(index)
        container = comment_button.locator(
            "xpath=ancestor::div[contains(@class, 'fie-impression-container')][1]"
        )
        if await container.count() == 0:
            container = comment_button.locator(
                "xpath=ancestor::div[contains(@class, 'feed-shared-update-v2')][1]"
            )
        if await container.count() == 0:
            continue
        post_text = await container.inner_text()
        post_age = extract_relative_age(post_text)
        post_days = age_in_days(post_age)
        if post_days is not None and post_days > int(config["lookback_days"]):
            continue

        existing_comment_ids = set(
            await page.locator("article.comments-comment-entity").evaluate_all(
                "(nodes) => nodes.map(n => n.getAttribute('data-id') || '')"
            )
        )
        await comment_button.click(timeout=3000)
        await page.wait_for_timeout(1500)

        all_comment_articles = page.locator("article.comments-comment-entity")
        first_new_article = None
        for probe_index in range(await all_comment_articles.count()):
            probe = all_comment_articles.nth(probe_index)
            probe_id = await probe.get_attribute("data-id") or ""
            if probe_id not in existing_comment_ids:
                first_new_article = probe
                break

        if first_new_article is None:
            continue

        comments_list = first_new_article.locator(
            "xpath=ancestor::div[contains(@class, 'comments-comments-list')][1]"
        )
        if await comments_list.count():
            await load_more_comments(
                comments_list, int(config["max_load_more_clicks"])
            )
            comment_articles = comments_list.locator(
                "article.comments-comment-entity"
            )
        else:
            comment_articles = all_comment_articles

        comment_count = min(
            await comment_articles.count(), int(config["max_comments_per_post"])
        )

        for comment_index in range(comment_count):
            article = comment_articles.nth(comment_index)
            comment_id = await article.get_attribute("data-id") or ""
            if not await comments_list.count() and comment_id in existing_comment_ids:
                continue
            profile_links = article.locator("a[href*='/in/']")
            if await profile_links.count() == 0:
                continue

            profile_candidates = []
            for profile_index in range(await profile_links.count()):
                candidate = profile_links.nth(profile_index)
                candidate_text = (await candidate.inner_text()).strip()
                candidate_url = await candidate.get_attribute("href")
                if candidate_url:
                    profile_candidates.append(
                        (candidate, candidate_text, candidate_url)
                    )
            if not profile_candidates:
                continue
            profile_link, actor_text, raw_profile_url = max(
                profile_candidates, key=lambda item: len(item[1])
            )
            if not raw_profile_url:
                continue
            commenter_url = normalize_profile_url(raw_profile_url)
            if commenter_url == normalize_profile_url(competitor_profile_url):
                continue

            commenter_name, commenter_headline = parse_actor_text(actor_text)
            article_text = (await article.inner_text()).strip()
            comment_age = extract_relative_age(article_text)
            content = article.locator(
                ".comments-comment-item__main-content, "
                ".comments-comment-item-content-body"
            )
            if await content.count():
                clean_comment_text = (await content.first.inner_text()).strip()
            else:
                clean_comment_text = parse_comment_text(
                    article_text, actor_text, comment_age
                )

            data_id = await article.get_attribute("data-id") or ""
            post_match = re.search(
                r"urn:li:comment:\((ugcPost|activity|share):(\d+),", data_id
            )
            if post_match:
                source_post_url = (
                    "https://www.linkedin.com/feed/update/"
                    f"urn:li:{post_match.group(1)}:{post_match.group(2)}/"
                )
            else:
                source_post_url = activity_url

            signals.append(
                CommenterSignal(
                    signal_type="competitor_commenter",
                    detected_at=detected_at,
                    competitor_name=competitor_name,
                    competitor_profile_url=normalize_profile_url(
                        competitor_profile_url
                    ),
                    source_post_url=source_post_url,
                    source_post_age=post_age,
                    commenter_name=commenter_name,
                    commenter_headline=commenter_headline,
                    commenter_linkedin_url=commenter_url,
                    comment_age=comment_age,
                    comment_text=clean_comment_text,
                    reaction_type="",
                )
            )

        await asyncio.sleep(float(config["delay_between_posts_seconds"]))

    return signals


async def run(args: argparse.Namespace) -> Path:
    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]]
    from linkedin_mcp_server.drivers.browser import close_browser, get_or_create_browser

    try:
        config = load_config(args.config)
        profile_urls = args.profile_urls or config["competitor_profiles"]
        seen = load_seen(args.state, args.reset_state)
        seen.update(load_shared_seen(args.shared_sheet))
        seen_names = load_shared_seen_names(args.shared_sheet)
        run_seen: set[str] = set()
        run_seen_names: set[str] = set()
        new_rows: list[CommenterSignal] = []

        browser = await get_or_create_browser()
        page = browser.page
        try:
            for profile_url in profile_urls:
                rows = await scan_profile(page, profile_url, config)
                for row in rows:
                    profile_key = normalize_profile_url(row.commenter_linkedin_url)
                    name_key = row.commenter_name.strip().casefold()
                    if (
                        profile_key in seen
                        or profile_key in run_seen
                        or name_key in seen_names
                        or name_key in run_seen_names
                    ):
                        continue
                    run_seen.add(profile_key)
                    run_seen_names.add(name_key)
                    new_rows.append(row)
        finally:
            await close_browser()

        append_csv(args.shared_sheet, new_rows)
        lead_sheet_result = append_leads(
            args.lead_sheet,
            [
                {
                    "signal_type": row.signal_type,
                    "detected_at": row.detected_at,
                    "lead_type": "person",
                    "person_name": row.commenter_name,
                    "person_linkedin_url": row.commenter_linkedin_url,
                    "headline": row.commenter_headline,
                    "source_url": row.source_post_url,
                    "evidence": row.comment_text,
                    "metadata_json": {
                        "competitor_name": row.competitor_name,
                        "competitor_profile_url": row.competitor_profile_url,
                        "source_post_age": row.source_post_age,
                        "comment_age": row.comment_age,
                    },
                }
                for row in new_rows
            ],
        )

        seen.update(run_seen)
        save_seen(args.state, seen)
        print(
            json.dumps(
                {
                    "status": "success",
                    "profiles_scanned": len(profile_urls),
                    "new_commenters": len(new_rows),
                    "total_exported_profiles": len(seen),
                    "shared_sheet": str(args.shared_sheet),
                    "lead_sheet": str(args.lead_sheet),
                    "lead_sheet_result": lead_sheet_result,
                    "state_file": str(args.state),
                },
                indent=2,
            )
        )
        return args.shared_sheet
    finally:
        sys.argv = original_argv


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
