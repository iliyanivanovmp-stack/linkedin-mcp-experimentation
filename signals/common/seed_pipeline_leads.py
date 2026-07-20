"""Seed the shared pipeline sheet from existing signal export artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from lead_sheet import append_leads


SIGNALS = Path(__file__).parents[1]
EXPORTS = SIGNALS / "exports"
LEAD_SHEET = EXPORTS / "pipeline_leads.csv"


def engagement_rows() -> list[dict]:
    path = EXPORTS / "competitor_engagement_leads.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "signal_type": row["signal_type"],
            "detected_at": row["detected_at"],
            "lead_type": "person",
            "person_name": row["commenter_name"],
            "person_linkedin_url": row["commenter_linkedin_url"],
            "headline": row["commenter_headline"],
            "source_url": row["source_post_url"],
            "evidence": row["comment_text"] or f"Reacted to {row['competitor_name']}'s LinkedIn post.",
            "metadata_json": {
                "competitor_name": row["competitor_name"],
                "competitor_profile_url": row["competitor_profile_url"],
                "source_post_age": row["source_post_age"],
                "comment_age": row["comment_age"],
                "reaction_type": row["reaction_type"],
            },
        }
        for row in rows
    ]


def technology_rows() -> list[dict]:
    path = EXPORTS / "technology_signals.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "signal_type": "technology_integration_opportunity",
            "detected_at": row["detected_at"],
            "lead_type": "company",
            "company_name": row["domain"],
            "company_domain": row["domain"],
            "source_url": f"https://{row['domain']}",
            "evidence": f"Detected technologies: {row['technologies']}",
            "metadata_json": {
                "homepage_status": row["homepage_status"],
                "technologies": row["technologies"],
                "integration_opportunity": row["integration_opportunity"],
            },
        }
        for row in rows
        if row.get("technologies")
    ]


def job_rows() -> list[dict]:
    path = EXPORTS / "job_signals.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    rows = []
    for match in payload.get("matches", []):
        lines = [line.strip() for line in match.get("text", "").splitlines() if line.strip()]
        rows.append(
            {
                "signal_type": "manual_process_job_posting",
                "lead_type": "company",
                "company_name": lines[0] if lines else "",
                "source_url": match.get("url", ""),
                "evidence": ", ".join(match.get("evidence_phrases", [])),
                "metadata_json": {
                    "job_id": match.get("job_id", ""),
                    "job_title": lines[1] if len(lines) > 1 else "",
                    "evidence_phrases": match.get("evidence_phrases", []),
                },
            }
        )
    return rows


def funnel_rows() -> list[dict]:
    path = EXPORTS / "funnel_signals.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "signal_type": "broken_website_funnel",
            "detected_at": row["detected_at"],
            "lead_type": "company",
            "company_name": row["domain"],
            "company_domain": row["domain"],
            "source_url": f"https://{row['domain']}",
            "evidence": row["broken_funnel_pages"],
            "metadata_json": {
                "homepage_status": row["homepage_status"],
                "funnel_pages_checked": row["funnel_pages_checked"],
                "broken_funnel_pages": json.loads(row["broken_funnel_pages"]),
            },
        }
        for row in rows
        if row.get("signal_found", "").casefold() == "true"
    ]


def main() -> None:
    rows = engagement_rows() + technology_rows() + job_rows() + funnel_rows()
    print(json.dumps({"lead_sheet": str(LEAD_SHEET), **append_leads(LEAD_SHEET, rows)}, indent=2))


if __name__ == "__main__":
    main()
