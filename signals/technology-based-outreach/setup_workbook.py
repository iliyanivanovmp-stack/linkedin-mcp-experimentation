from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


from extract_contacts import CONTACT_COLUMNS, load_env_file  # noqa: E402


COMPANY_COLUMNS = [
    "company_name", "company_domain", "company_linkedin_url", "company_size",
    "country", "industry", "mode", "requested_technologies",
    "matched_technologies", "all_technologies", "selected_outreach_tools",
    "automation_example_1", "automation_example_2", "automation_example_3",
    "outreach_angle", "match_method", "confidence", "sources",
    "stale_domain_warning", "created_at", "status", "technologies", "opener",
    "automation_opportunity_1", "automation_opportunity_2",
    "automation_opportunity_3", "icebreaker", "source_url", "do_not_sequence",
    "outreach_context_generated_at", "contacts_status", "contacts_generated_at",
    "contacts_found_count", "contacts_ready_count", "contacts_needs_email_count",
    "contacts_duplicates_skipped", "contacts_error",
]


def client() -> gspread.Client:
    service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if service_json:
        credentials = Credentials.from_service_account_info(json.loads(service_json), scopes=scopes)
        return gspread.authorize(credentials)
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not credentials_path:
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON")
    return gspread.service_account(filename=credentials_path)


def initialize(spreadsheet_id: str) -> dict[str, object]:
    spreadsheet = client().open_by_key(spreadsheet_id)
    tabs = {worksheet.title: worksheet for worksheet in spreadsheet.worksheets()}
    for title, headers, rows in (
        ("Companies", COMPANY_COLUMNS, 1000),
        ("Contacts", CONTACT_COLUMNS, 3000),
    ):
        worksheet = tabs.get(title)
        if worksheet is None:
            worksheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=max(40, len(headers)))
        current_headers = worksheet.row_values(1)
        missing = [header for header in headers if header not in current_headers]
        final_headers = [*current_headers, *missing] if current_headers else headers
        if len(final_headers) > worksheet.col_count:
            worksheet.add_cols(len(final_headers) - worksheet.col_count)
        worksheet.update(range_name="A1", values=[final_headers])
        worksheet.freeze(rows=1)
        worksheet.set_basic_filter(f"A1:{gspread.utils.rowcol_to_a1(1, len(final_headers))}")
        worksheet.format(f"A1:{gspread.utils.rowcol_to_a1(1, len(final_headers))}", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0},
            "horizontalAlignment": "CENTER",
        })
    return {
        "spreadsheet_id": spreadsheet.id,
        "spreadsheet_url": spreadsheet.url,
        "tabs": [worksheet.title for worksheet in spreadsheet.worksheets()],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spreadsheet_id")
    args = parser.parse_args()
    try:
        load_env_file()
        result = initialize(args.spreadsheet_id)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        sys.exit(1)
    print(json.dumps({"status": "success", **result}, indent=2))


if __name__ == "__main__":
    main()
