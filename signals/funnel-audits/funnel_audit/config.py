from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    spreadsheet_id: str = "1UD1tPrjXy8Hr3l5tAcLALHqa30IJ-AZeO0f4_DbGYAM"
    sheet_name: str = "Website Pipelines"
    database_path: str = "/data/funnel-audit.db"
    evidence_dir: str = "/data/evidence"
    monitoring_days: int = 10
    daily_audit_limit: int = 10
    audit_name: str = os.getenv("AUDIT_NAME", "Iliyan Ivanov")
    audit_email: str = os.getenv("AUDIT_EMAIL", "iliyan.i@aiessentials.us")
    audit_phone: str = os.getenv("AUDIT_PHONE", "+359889609200")
    audit_title: str = os.getenv("AUDIT_TITLE", "Founder")
    audit_company: str = os.getenv("AUDIT_COMPANY", "AIessentials")
    live_submissions: bool = os.getenv("LIVE_SUBMISSIONS", "false").lower() == "true"
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    composio_user_id: str = os.getenv(
        "COMPOSIO_USER_ID", "funnel-audit-system"
    )
    browser_task_timeout_seconds: int = int(
        os.getenv("BROWSER_TASK_TIMEOUT_SECONDS", "300")
    )


SETTINGS = Settings()
