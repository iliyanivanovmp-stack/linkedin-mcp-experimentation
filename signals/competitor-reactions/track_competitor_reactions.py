"""Track new people reacting to recent LinkedIn posts from competitors.

This script is read-only. It opens existing reaction lists but never reacts,
comments, follows, connects, or sends messages.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
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
class ReactionSignal:
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
        description="Export new reactors from recent competitor LinkedIn posts."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--shared-sheet", type=Path, default=DEFAULT_SHARED_SHEET)
    parser.add_argument("--lead-sheet", type=Path, default=DEFAULT_LEAD_SHEET)
    parser.add_argument(
        "--profile-url",
        action="append",
        dest="profile_urls",
        help="Override config profiles. Repeat for multiple competitors.",
    )
    parser.add_argument("--reset-state", action="store_true")
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
    return {
        "m": number / 1440,
        "h": number / 24,
        "d": float(number),
        "w": float(number * 7),
        "mo": float(number * 30),
        "yr": float(number * 365),
    }[match.group(2)]


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
    headline = " ".join(
        line
        for line in lines[1:]
        if not line.lower().startswith("view ")
        and not re.fullmatch(r"[•·]?\s*(?:1st|2nd|3rd\+?)", line)
        and "degree connection" not in line.lower()
    )
    return name, headline


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
    path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "profile_urls": sorted(seen),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def append_csv(path: Path, rows: list[ReactionSignal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


async def show_more_reactions(dialog: Any, max_clicks: int) -> None:
    for _ in range(max_clicks):
        buttons = dialog.locator("button").filter(
            has_text=re.compile(r"^Show more results$", re.IGNORECASE)
        )
        if await buttons.count() == 0 or not await buttons.first.is_visible():
            return
        await buttons.first.click(timeout=3000)
        await asyncio.sleep(1.5)


async def source_post_url(container: Any, dialog: Any, activity_url: str) -> str:
    permalink = container.locator(
        "a[href*='/feed/update/'], a[href*='/posts/']"
    )
    if await permalink.count():
        href = await permalink.first.get_attribute("href")
        if href:
            parsed = urlparse(href)
            return f"https://www.linkedin.com{parsed.path}"

    html = await dialog.evaluate("(node) => node.outerHTML")
    match = re.search(r"urn:li:(ugcPost|activity|share):(\d+)", html)
    if match:
        return (
            "https://www.linkedin.com/feed/update/"
            f"urn:li:{match.group(1)}:{match.group(2)}/"
        )
    return activity_url


async def scan_profile(
    page: Any, competitor_profile_url: str, config: dict[str, Any]
) -> list[ReactionSignal]:
    activity_url = recent_activity_url(competitor_profile_url)
    await page.goto(activity_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    slug = profile_slug(competitor_profile_url)
    competitor_name = slug
    competitor_links = page.locator(f"main a[href*='/in/{slug}']")
    actor_texts = [
        (await competitor_links.nth(i).inner_text()).strip()
        for i in range(await competitor_links.count())
    ]
    actor_texts = [text for text in actor_texts if text]
    if actor_texts:
        competitor_name = parse_actor_text(max(actor_texts, key=len))[0]

    reaction_buttons = page.locator("main button[aria-label$='reactions' i]")
    button_count = min(
        await reaction_buttons.count(), int(config["max_posts_per_profile"])
    )
    detected_at = datetime.now(timezone.utc).isoformat()
    rows: list[ReactionSignal] = []

    for index in range(button_count):
        button = reaction_buttons.nth(index)
        container = button.locator(
            "xpath=ancestor::div[contains(@class, 'fie-impression-container')][1]"
        )
        if await container.count() == 0:
            container = button.locator(
                "xpath=ancestor::div[contains(@class, 'feed-shared-update-v2')][1]"
            )
        if await container.count() == 0:
            continue

        post_text = await container.inner_text()
        post_age = extract_relative_age(post_text)
        post_days = age_in_days(post_age)
        if post_days is not None and post_days > int(config["lookback_days"]):
            continue

        await button.click(timeout=3000)
        await page.wait_for_timeout(1500)
        all_dialogs = page.locator("[role='dialog'], dialog")
        reaction_dialog = None
        for dialog_index in range(await all_dialogs.count()):
            candidate = all_dialogs.nth(dialog_index)
            preview = (await candidate.inner_text()).strip()
            if preview.startswith("Dialog content start.\nReactions"):
                reaction_dialog = candidate
                break
        if reaction_dialog is None:
            continue
        dialog = reaction_dialog
        await show_more_reactions(dialog, int(config["max_show_more_clicks"]))
        post_url = await source_post_url(container, dialog, activity_url)

        profile_links = dialog.locator("a[href*='/in/']")
        best_by_url: dict[str, str] = {}
        for profile_index in range(await profile_links.count()):
            link = profile_links.nth(profile_index)
            href = await link.get_attribute("href")
            if not href:
                continue
            normalized = normalize_profile_url(href)
            text = (await link.inner_text()).strip()
            if len(text) > len(best_by_url.get(normalized, "")):
                best_by_url[normalized] = text

        for reactor_url, actor_text in list(best_by_url.items())[
            : int(config["max_reactions_per_post"])
        ]:
            if reactor_url == normalize_profile_url(competitor_profile_url):
                continue
            name, headline = parse_actor_text(actor_text)
            rows.append(
                ReactionSignal(
                    signal_type="competitor_reaction",
                    detected_at=detected_at,
                    competitor_name=competitor_name,
                    competitor_profile_url=normalize_profile_url(
                        competitor_profile_url
                    ),
                    source_post_url=post_url,
                    source_post_age=post_age,
                    commenter_name=name,
                    commenter_headline=headline,
                    commenter_linkedin_url=reactor_url,
                    comment_age="",
                    comment_text="",
                    reaction_type="any",
                )
            )

        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        await asyncio.sleep(float(config["delay_between_posts_seconds"]))

    return rows


async def run(args: argparse.Namespace) -> Path:
    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]]
    from linkedin_mcp_server.drivers.browser import close_browser, get_or_create_browser

    try:
        config = load_config(args.config)
        profiles = args.profile_urls or config["competitor_profiles"]
        seen = load_seen(args.state, args.reset_state)
        seen.update(load_shared_seen(args.shared_sheet))
        seen_names = load_shared_seen_names(args.shared_sheet)
        run_seen: set[str] = set()
        run_seen_names: set[str] = set()
        new_rows: list[ReactionSignal] = []

        browser = await get_or_create_browser()
        page = browser.page
        try:
            for profile_url in profiles:
                for row in await scan_profile(page, profile_url, config):
                    key = normalize_profile_url(row.commenter_linkedin_url)
                    name_key = row.commenter_name.strip().casefold()
                    if (
                        key in seen
                        or key in run_seen
                        or name_key in seen_names
                        or name_key in run_seen_names
                    ):
                        continue
                    run_seen.add(key)
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
                    "evidence": f"Reacted to {row.competitor_name}'s LinkedIn post.",
                    "metadata_json": {
                        "competitor_name": row.competitor_name,
                        "competitor_profile_url": row.competitor_profile_url,
                        "source_post_age": row.source_post_age,
                        "reaction_type": row.reaction_type,
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
                    "profiles_scanned": len(profiles),
                    "new_reactors": len(new_rows),
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
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
