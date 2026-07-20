"""Read-only outcome report for the automation-jobs feedback columns."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = ROOT.parent.parent / "credentials.json"
TRUE_VALUES = {"1", "true", "yes", "y", "x"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().casefold() in TRUE_VALUES


def feedback_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rated: list[float] = []
    rejection_reasons: Counter[str] = Counter()
    for row in rows:
        raw_rating = str(row.get("fit_rating", "")).strip()
        if raw_rating:
            try:
                rated.append(float(raw_rating))
            except ValueError:
                pass
        reason = str(row.get("rejection_reason", "")).strip()
        if reason:
            rejection_reasons[reason] += 1

    applied = sum(_truthy(row.get("applied")) for row in rows)
    responses = sum(_truthy(row.get("response")) for row in rows)
    interviews = sum(_truthy(row.get("interview")) for row in rows)
    wins = sum(_truthy(row.get("won")) for row in rows)
    strong_fit = sum(rating >= 4 for rating in rated)

    return {
        "total_jobs": len(rows),
        "rated_jobs": len(rated),
        "strong_fit_jobs": strong_fit,
        "precision_at_4_plus": round(strong_fit / len(rated), 4) if rated else None,
        "average_fit_rating": round(sum(rated) / len(rated), 2) if rated else None,
        "applied": applied,
        "responses": responses,
        "interviews": interviews,
        "won": wins,
        "response_rate": round(responses / applied, 4) if applied else None,
        "interview_rate": round(interviews / applied, 4) if applied else None,
        "win_rate": round(wins / applied, 4) if applied else None,
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_reasons.most_common(10)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only automation-job feedback report")
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--sheet-id", default=os.environ.get("AUTOMATION_JOBS_SHEET_ID", ""))
    args = parser.parse_args()
    if not args.sheet_id:
        raise SystemExit("Set AUTOMATION_JOBS_SHEET_ID or pass --sheet-id")
    if not args.credentials.is_file():
        raise SystemExit(f"Credentials not found: {args.credentials}")

    import gspread
    from google.oauth2.service_account import Credentials

    credentials = Credentials.from_service_account_file(
        str(args.credentials), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    worksheet = gspread.authorize(credentials).open_by_key(args.sheet_id).sheet1
    print(json.dumps(feedback_metrics(worksheet.get_all_records()), indent=2))


if __name__ == "__main__":
    main()
