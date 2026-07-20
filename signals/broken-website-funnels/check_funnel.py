from __future__ import annotations

import argparse
import csv
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / "common"))
from lead_sheet import append_leads  # noqa: E402


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if tag == "a" and data.get("href"):
            self.links.append(data["href"] or "")


def fetch(url: str, timeout: int) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SignalRadar/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.geturl(), response.read(500000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as error:
        return error.code, url, ""
    except Exception:
        return 0, url, ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "exports" / "funnel_signals.csv")
    parser.add_argument("--lead-sheet", type=Path, default=Path(__file__).parents[1] / "exports" / "pipeline_leads.csv")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    findings = []
    for domain in config["domains"]:
        base = f"https://{domain}"
        status, _, body = fetch(base, int(config["timeout_seconds"]))
        parser_html = Links(); parser_html.feed(body)
        linked = []
        for href in parser_html.links:
            url = urljoin(base, href)
            if urlparse(url).netloc != domain:
                continue
            if not any(term in url.lower() for term in config["funnel_terms"]):
                continue
            if url not in linked:
                linked.append(url)
        broken = []
        for url in linked[: int(config["max_linked_pages"])]:
            page_status, final, _ = fetch(url, int(config["timeout_seconds"]))
            if page_status == 0 or page_status >= 400:
                broken.append({"url": url, "status": page_status, "final_url": final})
        findings.append(
            {
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "domain": domain,
                "homepage_status": status,
                "funnel_pages_checked": len(linked),
                "broken_funnel_pages": json.dumps(broken),
                "signal_found": bool(broken),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    exists = args.output.exists() and args.output.stat().st_size
    with args.output.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=findings[0].keys())
        if not exists:
            writer.writeheader()
        writer.writerows(findings)
    lead_sheet_result = append_leads(
        args.lead_sheet,
        [
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
            for row in findings
            if row["signal_found"]
        ],
    )
    print(json.dumps({
        "output": str(args.output),
        "lead_sheet": str(args.lead_sheet),
        "lead_sheet_result": lead_sheet_result,
        "findings": findings,
    }, indent=2))


if __name__ == "__main__":
    main()
