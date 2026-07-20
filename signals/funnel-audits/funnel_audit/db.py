from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS audits (
  audit_id TEXT PRIMARY KEY,
  sheet_row INTEGER,
  company_name TEXT NOT NULL,
  website_url TEXT NOT NULL,
  normalized_domain TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  submitted_at TEXT,
  monitor_until TEXT,
  last_checked_at TEXT,
  next_check_at TEXT,
  opportunity_status TEXT DEFAULT 'pending',
  gap_types TEXT DEFAULT '[]',
  gap_reason TEXT DEFAULT '',
  outreach_reason TEXT DEFAULT '',
  do_not_sequence INTEGER DEFAULT 1,
  followup_count INTEGER DEFAULT 0,
  cancellation_url TEXT DEFAULT '',
  cancellation_due_at TEXT DEFAULT '',
  UNIQUE(normalized_domain, audit_id)
);
CREATE INDEX IF NOT EXISTS idx_audits_status_next
ON audits(status, next_check_at);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audit_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(audit_id) REFERENCES audits(audit_id)
);
CREATE TABLE IF NOT EXISTS emails (
  message_id TEXT PRIMARY KEY,
  audit_id TEXT NOT NULL,
  thread_id TEXT,
  received_at TEXT,
  sender TEXT,
  subject TEXT,
  body_text TEXT,
  links_json TEXT DEFAULT '[]',
  assessment_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS inbound_messages (
  message_id TEXT PRIMARY KEY,
  thread_id TEXT,
  received_at TEXT,
  sender TEXT,
  subject TEXT,
  body_text TEXT,
  links_json TEXT DEFAULT '[]',
  audit_id TEXT,
  attribution_status TEXT NOT NULL DEFAULT 'unassigned',
  attribution_reason TEXT DEFAULT '',
  first_seen_at TEXT NOT NULL,
  FOREIGN KEY(audit_id) REFERENCES audits(audit_id)
);
CREATE INDEX IF NOT EXISTS idx_inbound_attribution
ON inbound_messages(attribution_status, received_at);
CREATE TABLE IF NOT EXISTS scheduler_leases (
  lease_name TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
"""

AUDIT_COLUMNS = {
    "sheet_row", "company_name", "website_url", "normalized_domain", "status",
    "created_at", "submitted_at", "monitor_until", "last_checked_at",
    "next_check_at", "opportunity_status", "gap_types", "gap_reason",
    "outreach_reason", "do_not_sequence", "followup_count", "cancellation_url",
    "cancellation_due_at",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def upsert_audit(self, row: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO audits (
                  audit_id, sheet_row, company_name, website_url,
                  normalized_domain, status, created_at, next_check_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(audit_id) DO UPDATE SET
                  sheet_row=excluded.sheet_row,
                  company_name=excluded.company_name,
                  website_url=excluded.website_url,
                  status=excluded.status,
                  next_check_at=excluded.next_check_at
                """,
                (
                    row["audit_id"],
                    row.get("sheet_row"),
                    row["company_name"],
                    row["website_url"],
                    row["normalized_domain"],
                    row.get("status", "queued"),
                    row.get("created_at", utcnow()),
                    row.get("next_check_at", utcnow()),
                ),
            )

    def update_audit(self, audit_id: str, **changes: Any) -> None:
        if not changes:
            return
        unknown = set(changes) - AUDIT_COLUMNS
        if unknown:
            raise ValueError(f"Unsupported audit columns: {sorted(unknown)}")
        columns = ", ".join(f"{key}=?" for key in changes)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE audits SET {columns} WHERE audit_id=?",
                (*changes.values(), audit_id),
            )

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM audits WHERE audit_id=?", (audit_id,)
            ).fetchone()
            return dict(row) if row else None

    def due_audits(self, statuses: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM audits
                WHERE status IN ({placeholders})
                  AND (next_check_at IS NULL OR next_check_at <= ?)
                ORDER BY created_at
                LIMIT ?
                """,
                (*statuses, utcnow(), limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_event(self, audit_id: str, event_type: str, payload: Any) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events(audit_id, event_type, created_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (audit_id, event_type, utcnow(), json.dumps(payload, default=str)),
            )
            return int(cursor.lastrowid)

    def count_events_since(self, event_type: str, since: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM events
                WHERE event_type=? AND created_at>=?
                """,
                (event_type, since),
            ).fetchone()
            return int(row["total"])

    def active_domain_exists(self, domain: str, excluding_audit_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM audits
                WHERE normalized_domain=?
                  AND audit_id<>?
                  AND status IN (
                    'queued', 'discovery_complete', 'awaiting_required_input',
                    'submitted', 'monitoring', 'opportunity_detected'
                  )
                LIMIT 1
                """,
                (domain, excluding_audit_id),
            ).fetchone()
            return row is not None

    def events(self, audit_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE audit_id=? ORDER BY id", (audit_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def save_email(self, payload: dict[str, Any]) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO emails(
                  message_id, audit_id, thread_id, received_at, sender,
                  subject, body_text, links_json, assessment_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["message_id"],
                    payload["audit_id"],
                    payload.get("thread_id", ""),
                    payload.get("received_at", ""),
                    payload.get("sender", ""),
                    payload.get("subject", ""),
                    payload.get("body_text", ""),
                    json.dumps(payload.get("links", [])),
                    json.dumps(payload.get("assessment", {})),
                ),
            )
            return cursor.rowcount > 0

    def save_inbound_message(self, payload: dict[str, Any]) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO inbound_messages(
                  message_id, thread_id, received_at, sender, subject,
                  body_text, links_json, first_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["message_id"], payload.get("thread_id", ""),
                    payload.get("received_at", ""), payload.get("sender", ""),
                    payload.get("subject", ""), payload.get("body_text", ""),
                    json.dumps(payload.get("links", [])), utcnow(),
                ),
            )
            return cursor.rowcount > 0

    def unassigned_messages(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM inbound_messages
                WHERE attribution_status='unassigned'
                ORDER BY received_at, first_seen_at
                """
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["links"] = json.loads(item.pop("links_json") or "[]")
            output.append(item)
        return output

    def assign_inbound_message(
        self, message_id: str, audit_id: str | None, status: str, reason: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE inbound_messages
                SET audit_id=?, attribution_status=?, attribution_reason=?
                WHERE message_id=?
                """,
                (audit_id, status, reason, message_id),
            )

    def inbound_attribution_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT attribution_status, COUNT(*) AS total FROM inbound_messages GROUP BY attribution_status"
            ).fetchall()
        return {str(row["attribution_status"]): int(row["total"]) for row in rows}

    def acquire_lease(self, name: str, owner: str, expires_at: str) -> bool:
        now = utcnow()
        with self.connect() as connection:
            connection.execute("DELETE FROM scheduler_leases WHERE expires_at<=?", (now,))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO scheduler_leases(lease_name, owner, expires_at) VALUES (?, ?, ?)",
                (name, owner, expires_at),
            )
            return cursor.rowcount > 0

    def release_lease(self, name: str, owner: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM scheduler_leases WHERE lease_name=? AND owner=?", (name, owner)
            )
