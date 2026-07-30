from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from extract_contacts import CsvSheet, GoogleWorkbook, Sheet, load_config, load_env_file  # noqa: E402


DEFAULT_CONFIG = Path(__file__).with_name("config.json")
CONTEXT_COLUMNS = [
    "status",
    "technologies",
    "opener",
    "automation_opportunity_1",
    "automation_opportunity_2",
    "automation_opportunity_3",
    "outreach_angle",
    "icebreaker",
    "pain_observation",
    "fabricated_result",
    "contrarian_hook",
    "outreach_context_generated_at",
]


def parse_tools(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            values = [str(item.get("name", "") if isinstance(item, dict) else item) for item in parsed]
        else:
            values = [text]
    except json.JSONDecodeError:
        values = re.split(r"[,;|]", text)
    output = []
    seen = set()
    for value in values:
        clean = re.sub(r"\s+", " ", value).strip()
        if clean and clean.casefold() not in seen:
            seen.add(clean.casefold())
            output.append(clean)
    return output


def selected_tools(row: dict[str, str]) -> list[str]:
    for key in ("selected_outreach_tools", "matched_technologies", "technologies", "all_technologies"):
        tools = parse_tools(row.get(key, ""))
        if tools:
            return tools[:3]
    return []


def join_tools(tools: list[str]) -> str:
    if len(tools) == 1:
        return tools[0]
    if len(tools) == 2:
        return f"{tools[0]} and {tools[1]}"
    return f"{', '.join(tools[:-1])}, and {tools[-1]}"


TEAM_TYPE_SIGNALS: list[tuple[set[str], str]] = [
    ({"affise", "tune", "impact", "partnerstack", "cake", "everflow", "hasoffers"}, "partner marketing team"),
    ({"salesforce", "hubspot", "pipedrive", "close", "zoho", "copper"}, "sales team"),
    ({"shopify", "woocommerce", "klaviyo", "gorgias", "bigcommerce", "magento"}, "e-commerce team"),
    ({"tableau", "looker", "powerbi", "metabase", "domo"}, "ops team"),
    ({"jira", "linear", "github", "gitlab", "asana", "monday"}, "engineering team"),
    ({"greenhouse", "lever", "workday", "bamboohr", "lever"}, "recruiting team"),
    ({"mailchimp", "activecampaign", "marketo", "sendgrid", "brevo"}, "marketing team"),
]


def infer_team_type(tools: list[str]) -> str:
    tool_lower = {t.casefold() for t in tools}
    for signals, team in TEAM_TYPE_SIGNALS:
        if tool_lower & signals:
            return team
    return "operations team"


def pain_observation_text(tools: list[str]) -> str:
    names = join_tools(tools)
    return (
        f"When a team is running {names} without a connection layer, "
        "someone is manually moving data between them. Usually 3 to 5 hours a week."
    )


def fabricated_result_text(tools: list[str]) -> str:
    team = infer_team_type(tools)
    first = tools[0]
    second = tools[1] if len(tools) > 1 else tools[0]
    return (
        f"We connected {first} and {second} for a {team} last month. "
        "They went from pulling reports manually every week to having them auto-generated overnight."
    )


def contrarian_hook_text(tools: list[str]) -> str:
    names = join_tools(tools)
    return (
        f"Most companies running {names} already have some version of these connected. "
        "Usually through Zapier, a manual export, or a sheet someone built two years ago that no one fully trusts."
    )


def automation_examples(tools: list[str]) -> list[str]:
    names = {tool.casefold(): tool for tool in tools}
    if "slack" in names and "clickup" in names:
        return [
            "Send new ClickUp leads to Slack with the owner and next action included.",
            "Turn approved Slack actions into assigned ClickUp tasks automatically.",
            "Post ClickUp priority and status changes to the right Slack channel instantly.",
        ]

    joined = join_tools(tools)
    first = tools[0]
    second = tools[1] if len(tools) > 1 else tools[0]
    third = tools[2] if len(tools) > 2 else second
    return [
        f"Route qualified activity from {first} into {second} with ownership and next-step context.",
        f"Trigger timely team alerts when important records change across {joined}.",
        f"Keep customer and pipeline updates aligned between {first} and {third} automatically.",
    ]


def generated_context(row: dict[str, str]) -> dict[str, str]:
    tools = selected_tools(row)
    if not tools:
        return {}
    names = join_tools(tools)
    generated_examples = automation_examples(tools)
    examples = [
        str(row.get(f"automation_example_{index}", "") or "").strip()
        or generated_examples[index - 1]
        for index in range(1, 4)
    ]
    return {
        "technologies": ", ".join(tools),
        "opener": f"Saw your team is using {names}.",
        "automation_opportunity_1": examples[0],
        "automation_opportunity_2": examples[1],
        "automation_opportunity_3": examples[2],
        "outreach_angle": f"connect {names} so alerts, actions, and updates stay in one workflow.",
        "icebreaker": f"Saw your team is using {names}.",
        "pain_observation": pain_observation_text(tools),
        "fabricated_result": fabricated_result_text(tools),
        "contrarian_hook": contrarian_hook_text(tools),
    }


def truthy(value: str) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def prepare_context(
    sheet: Sheet,
    config: dict[str, Any],
    dry_run: bool,
    limit: int | None,
    force: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        sheet.ensure_columns(CONTEXT_COLUMNS)
    allowed_confidences = {
        str(value).casefold() for value in config.get("qualified_confidences", ["high", "medium"])
    }
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {"dry_run": dry_run, "rows_seen": 0, "qualified": 0, "updated": 0, "skipped": 0}
    for row in sheet.rows():
        if limit is not None and summary["updated"] >= limit:
            break
        summary["rows_seen"] += 1
        if truthy(row.data.get("do_not_sequence", "")) or truthy(row.data.get("do_not_contact", "")):
            summary["skipped"] += 1
            continue
        confidence = str(row.data.get("confidence", "") or "").strip().casefold()
        if confidence not in allowed_confidences:
            summary["skipped"] += 1
            continue
        context = generated_context(row.data)
        if not context:
            summary["skipped"] += 1
            continue
        summary["qualified"] += 1
        updates = {
            key: value
            for key, value in context.items()
            if force or not str(row.data.get(key, "") or "").strip()
        }
        current_status = str(row.data.get("status", "") or "").strip().casefold()
        if current_status in {"", "queued", "opportunity_detected"}:
            updates["status"] = "outreach_ready"
        if updates:
            updates["outreach_context_generated_at"] = generated_at
            if not dry_run:
                sheet.update_row(row.number, updates)
            summary["updated"] += 1
        else:
            summary["skipped"] += 1
    return summary


def open_sheet(config: dict[str, Any], companies_csv: Path | None) -> Sheet:
    if companies_csv:
        return CsvSheet(companies_csv)
    workbook = GoogleWorkbook(str(config["spreadsheet_id"]))
    return workbook.worksheet(str(config["companies_worksheet"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--companies-csv", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        load_env_file()
        config = load_config(args.config)
        result = prepare_context(open_sheet(config, args.companies_csv), config, args.dry_run, args.limit, args.force)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
