from __future__ import annotations

import base64
import json
import os
import re
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
_HEADER_CACHE: dict[tuple[str, str], list[str]] = {}


def merged_sheet_headers(
    actual: list[str], expected: list[str], changes: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Return the live schema plus requested missing output columns."""
    requested = set(changes)
    missing = [header for header in expected if header in requested and header not in actual]
    missing.extend(sorted(requested - set(actual) - set(missing)))
    return [*actual, *missing], missing


def column_letters(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _ensure_column_capacity(
    service, spreadsheet_id: str, sheet_name: str, required_columns: int
) -> None:
    metadata = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title,gridProperties(columnCount)))",
        )
        .execute()
    )
    properties = next(
        (
            sheet.get("properties", {})
            for sheet in metadata.get("sheets", [])
            if sheet.get("properties", {}).get("title") == sheet_name
        ),
        None,
    )
    if properties is None:
        raise ValueError(f"Unknown sheet: {sheet_name!r}")
    current = int(properties.get("gridProperties", {}).get("columnCount", 0) or 0)
    if required_columns <= current:
        return
    (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "appendDimension": {
                            "sheetId": properties["sheetId"],
                            "dimension": "COLUMNS",
                            "length": required_columns - current,
                        }
                    }
                ]
            },
        )
        .execute()
    )


def credentials() -> Credentials:
    payload = json.loads(os.environ["GOOGLE_OAUTH_JSON"])
    # Existing refresh tokens must be refreshed with the scope set originally
    # granted in their authorized-user payload. Passing a newly reduced subset
    # causes Google's token endpoint to reject the refresh as invalid_scope.
    # New authorizations use the least-privilege SCOPES declared above.
    return Credentials.from_authorized_user_info(payload)


def sheet_service():
    return build("sheets", "v4", credentials=credentials(), cache_discovery=False)


def gmail_service():
    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)


def read_sheet_rows(spreadsheet_id: str, sheet_name: str) -> list[dict[str, str]]:
    response = (
        sheet_service()
        .spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:AZ")
        .execute()
    )
    values = response.get("values", [])
    if not values:
        return []
    headers = values[0]
    return [
        {
            **{header: row[index] if index < len(row) else "" for index, header in enumerate(headers)},
            "sheet_row": str(row_number),
        }
        for row_number, row in enumerate(values[1:], start=2)
        if any(row)
    ]


def update_sheet_row(
    spreadsheet_id: str,
    sheet_name: str,
    row_number: int,
    headers: list[str],
    changes: dict[str, Any],
) -> None:
    expected_headers = headers
    cache_key = (spreadsheet_id, sheet_name)
    actual_headers = _HEADER_CACHE.get(cache_key)
    if actual_headers is None:
        response = (
            sheet_service()
            .spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!1:1")
            .execute()
        )
        actual_headers = (response.get("values") or [headers])[0]
        _HEADER_CACHE[cache_key] = actual_headers
    headers, missing_headers = merged_sheet_headers(
        list(actual_headers), expected_headers, changes
    )
    _HEADER_CACHE[cache_key] = headers
    service = sheet_service()
    if missing_headers:
        _ensure_column_capacity(service, spreadsheet_id, sheet_name, len(headers))
    cells = [
        {
            "range": f"'{sheet_name}'!{column_letters(headers.index(header) + 1)}1",
            "values": [[header]],
        }
        for header in missing_headers
    ]
    for header, value in changes.items():
        column = headers.index(header)
        letters = column_letters(column + 1)
        cells.append({"range": f"'{sheet_name}'!{letters}{row_number}", "values": [[value]]})
    if not cells:
        return
    (
        service
        .spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": cells},
        )
        .execute()
    )


def _decode_body(payload: dict[str, Any]) -> str:
    body = payload.get("body", {}).get("data")
    if body:
        return base64.urlsafe_b64decode(body + "==").decode("utf-8", "ignore")
    parts = payload.get("parts", [])
    plain_parts = [_decode_body(part) for part in parts if part.get("mimeType") == "text/plain"]
    if any(plain_parts):
        return "\n".join(part for part in plain_parts if part)
    html_parts = [_decode_body(part) for part in parts if part.get("mimeType") == "text/html"]
    if any(html_parts):
        return "\n".join(part for part in html_parts if part)
    return "\n".join(filter(None, (_decode_body(part) for part in parts))) if parts else ""


def list_audit_messages(alias_email: str, newer_than_days: int = 11) -> list[dict[str, Any]]:
    service = gmail_service()
    query = f"to:{alias_email} newer_than:{newer_than_days}d"
    items = []
    page_token = None
    while len(items) < 500:
        listing = service.users().messages().list(
            userId="me", q=query, maxResults=min(100, 500 - len(items)), pageToken=page_token
        ).execute()
        items.extend(listing.get("messages", []))
        page_token = listing.get("nextPageToken")
        if not page_token:
            break
    messages = []
    for item in items:
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        headers = {
            header["name"].casefold(): header["value"]
            for header in raw.get("payload", {}).get("headers", [])
        }
        body = _decode_body(raw.get("payload", {}))
        mime_type = raw.get("payload", {}).get("mimeType", "")
        body_text = BeautifulSoup(body, "html.parser").get_text(" ", strip=True) if "html" in mime_type or "<" in body else body
        messages.append(
            {
                "message_id": raw["id"],
                "thread_id": raw.get("threadId", ""),
                "received_at": (
                    parsedate_to_datetime(headers["date"]).isoformat()
                    if headers.get("date")
                    else ""
                ),
                "sender": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "body_text": body_text,
                "links": re.findall(r"https?://[^\s\"'<>]+", body),
            }
        )
    return messages
