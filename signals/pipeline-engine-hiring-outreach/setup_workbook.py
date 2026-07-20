from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from collect_hiring_signals import FIELDS as LEAD_FIELDS
from extract_contacts import COMPANY_GUARDRAIL_COLUMNS, CONTACT_COLUMNS
from prepare_context import CONTEXT_COLUMNS


DEFAULT_CONFIG = Path(__file__).with_name("config.json")


def client() -> gspread.Client:
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if service_json:
        return gspread.authorize(Credentials.from_service_account_info(json.loads(service_json), scopes=scopes))
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not credentials_path:
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON")
    return gspread.service_account(filename=credentials_path)


def ensure_tab(spreadsheet, title: str, headers: list[str], rows: int) -> dict[str, object]:
    tabs = {worksheet.title: worksheet for worksheet in spreadsheet.worksheets()}
    worksheet = tabs.get(title) or spreadsheet.add_worksheet(title=title, rows=rows, cols=max(26, len(headers)))
    current = worksheet.row_values(1)
    final_headers = list(current)
    for header in headers:
        if header not in final_headers:
            final_headers.append(header)
    if worksheet.col_count < len(final_headers):
        worksheet.add_cols(len(final_headers) - worksheet.col_count)
    worksheet.update(range_name=f"A1:{gspread.utils.rowcol_to_a1(1, len(final_headers))}", values=[final_headers])
    worksheet.freeze(rows=1)
    worksheet.set_basic_filter(f"A1:{gspread.utils.rowcol_to_a1(max(2, worksheet.row_count), len(final_headers))}")
    worksheet.format(f"A1:{gspread.utils.rowcol_to_a1(1, len(final_headers))}", {
        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
        "textFormat": {"bold": True},
    })
    return {"title": title, "sheet_id": worksheet.id, "columns": len(final_headers)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    spreadsheet = client().open_by_key(str(config["spreadsheet_id"]))
    lead_headers = [*LEAD_FIELDS, *CONTEXT_COLUMNS, *COMPANY_GUARDRAIL_COLUMNS]
    result = [
        ensure_tab(spreadsheet, str(config["companies_worksheet"]), lead_headers, 3000),
        ensure_tab(spreadsheet, str(config["contacts_worksheet"]), CONTACT_COLUMNS, 6000),
    ]
    print(json.dumps({"spreadsheet_id": config["spreadsheet_id"], "tabs": result}, indent=2))


if __name__ == "__main__":
    main()
