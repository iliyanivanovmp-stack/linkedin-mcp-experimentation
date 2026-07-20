from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "common"))
from lead_sheet import append_leads  # noqa: E402


def fetch(domain: str, timeout: int) -> tuple[int, str]:
    request = urllib.request.Request(
        f"https://{domain}", headers={"User-Agent": "Mozilla/5.0 SignalRadar/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(500000).decode("utf-8", "ignore")
        return response.status, (body + " " + str(dict(response.headers))).lower()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "exports" / "technology_signals.csv")
    parser.add_argument("--lead-sheet", type=Path, default=Path(__file__).parents[1] / "exports" / "pipeline_leads.csv")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    rows = []
    for domain in config["domains"]:
        status, haystack = fetch(domain, int(config["timeout_seconds"]))
        detected = [
            name
            for name, needles in config["technologies"].items()
            if any(needle.lower() in haystack for needle in needles)
        ]
        rows.append(
            {
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "domain": domain,
                "homepage_status": status,
                "technologies": ", ".join(detected),
                "integration_opportunity": (
                    "Check APIs, webhooks, native integrations, n8n, and Zapier "
                    "between the detected tools. Do not claim they are disconnected."
                ),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    exists = args.output.exists() and args.output.stat().st_size
    with args.output.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
    lead_sheet_result = append_leads(
        args.lead_sheet,
        [
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
            if row["technologies"]
        ],
    )
    print(json.dumps({
        "checked": len(rows),
        "output": str(args.output),
        "lead_sheet": str(args.lead_sheet),
        "lead_sheet_result": lead_sheet_result,
        "rows": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
