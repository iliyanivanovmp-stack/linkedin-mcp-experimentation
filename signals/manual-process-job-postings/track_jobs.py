from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "common"))
from lead_sheet import append_leads  # noqa: E402


def job_identity(text: str) -> tuple[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[0] if lines else "", lines[1] if len(lines) > 1 else "")


async def run(config: dict, job_id: str | None = None) -> dict:
    original = sys.argv[:]
    sys.argv = [sys.argv[0]]
    from linkedin_mcp_server.drivers.browser import close_browser, get_or_create_browser
    from linkedin_mcp_server.scraping import LinkedInExtractor
    try:
        browser = await get_or_create_browser()
        extractor = LinkedInExtractor(browser.page)
        search = {"job_ids": [job_id]} if job_id else await extractor.search_jobs(
            config["keywords"],
            location=config["location"],
            max_pages=int(config["max_pages"]),
            date_posted=config["date_posted"],
            sort_by="date",
        )
        matches = []
        for job_id in search.get("job_ids", [])[: int(config["max_job_details"])]:
            details = await extractor.scrape_job(job_id)
            text = details.get("sections", {}).get("job_posting", "")
            evidence = [phrase for phrase in config["evidence_phrases"] if phrase.casefold() in text.casefold()]
            if evidence:
                matches.append({"job_id": job_id, "url": details.get("url", ""), "evidence_phrases": evidence, "text": text})
                break
        return {"jobs_searched": len(search.get("job_ids", [])), "matches": matches}
    finally:
        try:
            await close_browser()
        finally:
            sys.argv = original


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "exports" / "job_signals.json")
    parser.add_argument("--lead-sheet", type=Path, default=Path(__file__).parents[1] / "exports" / "pipeline_leads.csv")
    parser.add_argument("--job-id", help="Inspect one known LinkedIn job ID without running a search.")
    args = parser.parse_args()
    result = asyncio.run(run(json.loads(args.config.read_text()), args.job_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    detected_at = datetime.now(timezone.utc).isoformat()
    lead_rows = []
    for match in result["matches"]:
        company_name, job_title = job_identity(match["text"])
        lead_rows.append(
            {
                "signal_type": "manual_process_job_posting",
                "detected_at": detected_at,
                "lead_type": "company",
                "company_name": company_name,
                "source_url": match["url"],
                "evidence": ", ".join(match["evidence_phrases"]),
                "metadata_json": {
                    "job_id": match["job_id"],
                    "job_title": job_title,
                    "evidence_phrases": match["evidence_phrases"],
                },
            }
        )
    lead_sheet_result = append_leads(args.lead_sheet, lead_rows)
    print(json.dumps({
        "output": str(args.output),
        "lead_sheet": str(args.lead_sheet),
        "lead_sheet_result": lead_sheet_result,
        **result,
    }, indent=2))


if __name__ == "__main__":
    main()
