from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from urllib.parse import urlparse

from .ai import assess_email, assess_gap, decide_submission
from .browser import discover, submit_candidate
from .composio_browser import (
    cancel_booking as composio_cancel_booking,
    configured as composio_configured,
    submit_booking as composio_submit_booking,
)
from .config import SETTINGS
from .db import Database, utcnow
from .google import list_audit_messages, read_sheet_rows, update_sheet_row


HEADERS = [
    "audit_id", "created_at", "company_name", "website_url", "entry_url",
    "entry_type", "popup_detected", "popup_trigger", "popup_offer",
    "identity_name", "identity_email", "identity_title", "identity_company",
    "status", "submitted_at", "monitor_until", "last_checked_at",
    "next_check_at", "opportunity_status", "gap_types", "gap_reason",
    "outreach_reason", "checklist_passed", "checklist_failed",
    "checklist_unknown", "do_not_sequence", "confirmation_received_at",
    "followup_count", "notes",
]


def normalized_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.casefold().removeprefix("www.")


def audit_alias(audit_id: str) -> str:
    # This custom-domain address forwards into the authorized Gmail inbox but
    # is not a native Gmail mailbox, so plus-addressing is not guaranteed.
    return SETTINGS.audit_email


def audit_tracking_token(audit_id: str) -> str:
    return "FA-" + hashlib.sha256(audit_id.encode()).hexdigest()[:10].upper()


def tracked_audit_name(audit_id: str) -> str:
    return f"{SETTINGS.audit_name} [{audit_tracking_token(audit_id)}]"


def stable_audit_id(domain: str, created_at: str) -> str:
    day = created_at[:10].replace("-", "")
    suffix = hashlib.sha256(f"{domain}:{created_at}".encode()).hexdigest()[:6]
    return f"{domain.replace('.', '-')}-{day}-{suffix}"


def candidate_score(candidate) -> int:
    score = 0
    offer = candidate.offer_text.casefold()
    if candidate.entry_type in {"form", "popup"}:
        score += 20
    if candidate.entry_type == "booking":
        score += 8
    if re_search(r"report|guide|audit|download|newsletter|free", offer):
        score += 25
    if re_search(r"contact|demo|sales", offer):
        score -= 8
    score += min(len(candidate.fields), 8)
    if candidate.captcha_detected or candidate.payment_detected or candidate.sensitive_detected:
        score -= 100
    if candidate.reveal_cta_text:
        score += 4
    return score


def re_search(pattern: str, value: str) -> bool:
    import re

    return bool(re.search(pattern, value, re.I))


def rank_candidates(candidates: list) -> list:
    ranked = sorted(candidates, key=candidate_score, reverse=True)
    for index, candidate in enumerate(ranked, start=1):
        candidate.discovery_rank = index
    return ranked


def ingest_queue(db: Database) -> int:
    rows = read_sheet_rows(SETTINGS.spreadsheet_id, SETTINGS.sheet_name)
    ingested = 0
    for row in rows:
        if row.get("status", "").strip() not in {"", "queued"}:
            continue
        website = row.get("website_url", "").strip()
        if not website:
            continue
        created = row.get("created_at") or utcnow()
        domain = normalized_domain(website)
        audit_id = row.get("audit_id") or stable_audit_id(domain, created)
        if db.active_domain_exists(domain, audit_id):
            update_sheet_row(
                SETTINGS.spreadsheet_id,
                SETTINGS.sheet_name,
                int(row["sheet_row"]),
                HEADERS,
                {
                    "status": "do_not_contact",
                    "do_not_sequence": True,
                    "notes": "Skipped: another active audit already exists for this domain.",
                },
            )
            continue
        db.upsert_audit(
            {
                "audit_id": audit_id,
                "sheet_row": int(row["sheet_row"]),
                "company_name": row.get("company_name") or domain,
                "website_url": website,
                "normalized_domain": domain,
                "status": "queued",
                "created_at": created,
            }
        )
        update_sheet_row(
            SETTINGS.spreadsheet_id,
            SETTINGS.sheet_name,
            int(row["sheet_row"]),
            HEADERS,
            {
                "audit_id": audit_id,
                "created_at": created,
                "identity_name": tracked_audit_name(audit_id),
                "identity_email": audit_alias(audit_id),
                "identity_title": SETTINGS.audit_title,
                "identity_company": SETTINGS.audit_company,
                "status": "queued",
                "do_not_sequence": True,
            },
        )
        ingested += 1
    return ingested


async def process_discovery(db: Database) -> list[dict]:
    results = []
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    remaining = max(
        0,
        SETTINGS.daily_audit_limit
        - db.count_events_since("discovery_complete", today),
    )
    for audit in db.due_audits(("queued",), remaining):
        submission_changes: dict[str, str] = {}
        try:
            candidates = rank_candidates(await discover(
                audit["website_url"], SETTINGS.evidence_dir, audit["audit_id"]
            ))
            db.add_event(
                audit["audit_id"],
                "discovery_complete",
                [candidate.model_dump() for candidate in candidates],
            )
            if not candidates:
                status = "manual_review"
                notes = "No supported public form or funnel entry was discovered."
            else:
                candidate = candidates[0]
                decision = decide_submission(candidate)
                for item in decision.field_values:
                    if item.field.casefold() == "email":
                        item.value = audit_alias(audit["audit_id"])
                    elif item.field.casefold() == "name":
                        item.value = tracked_audit_name(audit["audit_id"])
                db.add_event(audit["audit_id"], "submission_decision", decision.model_dump())
                if decision.action != "submit":
                    status = "manual_review" if decision.action == "manual_review" else "do_not_contact"
                    notes = decision.reason
                elif not SETTINGS.live_submissions:
                    status = "discovery_complete"
                    notes = "Dry run: submission approved but LIVE_SUBMISSIONS is false."
                else:
                    if candidate.entry_type == "booking":
                        if not composio_configured():
                            submission = {
                                "submitted": False,
                                "reason": "COMPOSIO_API_KEY is not configured.",
                            }
                        else:
                            submission = await asyncio.to_thread(
                                composio_submit_booking,
                                candidate,
                                decision,
                            )
                    else:
                        submission = await submit_candidate(
                            candidate,
                            decision,
                            SETTINGS.evidence_dir,
                            audit["audit_id"],
                        )
                    db.add_event(audit["audit_id"], "submission_result", submission)
                    if submission.get("submitted"):
                        now = datetime.now(timezone.utc)
                        status = "monitoring"
                        submission_changes = {
                            "submitted_at": now.isoformat(),
                            "monitor_until": (
                                now + timedelta(days=SETTINGS.monitoring_days)
                            ).isoformat(),
                            "next_check_at": now.isoformat(),
                        }
                        if submission.get("confirmation_url"):
                            submission_changes["cancellation_url"] = submission[
                                "confirmation_url"
                            ]
                        if candidate.entry_type == "booking":
                            scheduled_text = str(submission.get("scheduled_time", "")).strip()
                            try:
                                scheduled = datetime.fromisoformat(
                                    scheduled_text.replace("Z", "+00:00")
                                )
                                submission_changes["cancellation_due_at"] = (
                                    scheduled - timedelta(hours=20)
                                ).isoformat()
                            except ValueError:
                                # Booking dates are chosen at least four days out.
                                # If the provider omitted a machine-readable time,
                                # cancel within 24 hours rather than risk a live meeting.
                                submission_changes["cancellation_due_at"] = (
                                    now + timedelta(hours=24)
                                ).isoformat()
                        db.update_audit(audit["audit_id"], **submission_changes)
                        notes = "Submitted successfully; inbox monitoring started."
                    else:
                        status = "manual_review"
                        notes = submission.get("reason", "Submission adapter unavailable.")
            db.update_audit(audit["audit_id"], status=status)
            update_sheet_row(
                SETTINGS.spreadsheet_id,
                SETTINGS.sheet_name,
                audit["sheet_row"],
                HEADERS,
                {
                    "status": status,
                    "notes": notes,
                    "submitted_at": submission_changes.get("submitted_at", ""),
                    "monitor_until": submission_changes.get("monitor_until", ""),
                    "next_check_at": utcnow(),
                },
            )
            results.append({"audit_id": audit["audit_id"], "status": status})
        except Exception as error:
            db.add_event(audit["audit_id"], "discovery_error", {"error": str(error)})
            configuration_error = (
                "insufficient_quota" in str(error)
                or "OPENAI_API_KEY" in str(error)
            )
            status = "queued" if configuration_error else "audit_failed"
            db.update_audit(
                audit["audit_id"],
                status=status,
                next_check_at=(
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
            )
            results.append(
                {
                    "audit_id": audit["audit_id"],
                    "status": status,
                    "error": "configuration_error" if configuration_error else "audit_error",
                }
            )
    return results


def _message_attribution(message: dict, audits: list[dict]) -> tuple[dict | None, str]:
    sender_address = parseaddr(message.get("sender", ""))[1]
    sender_domain = sender_address.rsplit("@", 1)[-1].casefold() if "@" in sender_address else ""
    haystack = " ".join(
        [message.get("subject", ""), message.get("body_text", ""), *message.get("links", [])]
    ).casefold()
    received_text = message.get("received_at", "")
    try:
        received = datetime.fromisoformat(received_text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        received = None
    scored = []
    for audit in audits:
        submitted_text = audit.get("submitted_at") or audit.get("created_at") or ""
        try:
            submitted = datetime.fromisoformat(submitted_text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            submitted = None
        if received and submitted and received < submitted - timedelta(minutes=5):
            continue
        domain = audit["normalized_domain"].casefold()
        company = (audit.get("company_name") or "").strip().casefold()
        score = 0
        reasons = []
        token = audit_tracking_token(audit["audit_id"]).casefold()
        if token in haystack:
            score += 200
            reasons.append("audit_tracking_token")
        if sender_domain == domain or sender_domain.endswith(f".{domain}"):
            score += 100
            reasons.append("sender_domain")
        if domain and domain in haystack:
            score += 40
            reasons.append("domain_in_message")
        if company and len(company) >= 4 and company in haystack:
            score += 20
            reasons.append("company_in_message")
        if score:
            scored.append((score, audit, reasons))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None, "no_company_correlation"
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, "ambiguous_company_correlation"
    score, audit, reasons = scored[0]
    if score < 40:
        return None, "weak_company_correlation"
    return audit, "+".join(reasons)


def monitor_inbox(db: Database) -> list[dict]:
    processed = []
    audits = db.due_audits(("monitoring", "submitted"), 100)
    if not audits:
        return processed
    for message in list_audit_messages(SETTINGS.audit_email):
        db.save_inbound_message(message)
    for message in db.unassigned_messages():
        audit, reason = _message_attribution(message, audits)
        if audit is None:
            # Ambiguous messages remain available for a later routing pass or
            # operator review; they are never guessed onto an audit.
            continue
        assessment = assess_email(
            message["subject"], message["sender"], message["body_text"], message["links"]
        )
        saved = db.save_email(
            {**message, "audit_id": audit["audit_id"], "assessment": assessment.model_dump()}
        )
        db.assign_inbound_message(message["message_id"], audit["audit_id"], "assigned", reason)
        if saved:
            db.add_event(audit["audit_id"], "email_received", {
                **assessment.model_dump(), "message_id": message["message_id"],
                "attribution_reason": reason,
                "received_at": message.get("received_at", ""),
                "sender": message.get("sender", ""),
                "subject": message.get("subject", ""),
            })
            changes = {
                "last_checked_at": utcnow(),
                "next_check_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            }
            if assessment.cancellation_url:
                changes["cancellation_url"] = assessment.cancellation_url
            if assessment.scheduled_start:
                try:
                    scheduled = datetime.fromisoformat(
                        assessment.scheduled_start.replace("Z", "+00:00")
                    )
                    # Keep the booking long enough to observe the 24-hour reminder,
                    # then cancel with a buffer before the meeting.
                    changes["cancellation_due_at"] = (
                        scheduled - timedelta(hours=20)
                    ).isoformat()
                except ValueError:
                    pass
            db.update_audit(audit["audit_id"], **changes)
            processed.append({"audit_id": audit["audit_id"], "message_id": message["message_id"]})

    checked_at = utcnow()
    for audit in audits:
        db.update_audit(
            audit["audit_id"],
            last_checked_at=checked_at,
            next_check_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        )
    return processed


async def cancel_due_bookings(db: Database) -> list[dict]:
    cancelled = []
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM audits
            WHERE cancellation_url<>''
              AND cancellation_due_at<>''
              AND cancellation_due_at<=?
              AND status IN ('submitted', 'monitoring')
            """,
            (now,),
        ).fetchall()
    for row in rows:
        audit = dict(row)
        if not composio_configured():
            result = {
                "cancelled": False,
                "reason": "COMPOSIO_API_KEY is not configured.",
            }
        else:
            result = await asyncio.to_thread(
                composio_cancel_booking,
                audit["cancellation_url"],
            )
        db.add_event(audit["audit_id"], "booking_cancellation", result)
        if result.get("cancelled"):
            db.update_audit(
                audit["audit_id"],
                cancellation_due_at="",
                cancellation_url="",
            )
        else:
            db.update_audit(
                audit["audit_id"],
                cancellation_due_at=(
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
            )
        cancelled.append({"audit_id": audit["audit_id"], **result})
    return cancelled


def finalize_due(db: Database) -> list[dict]:
    finalized = []
    now = datetime.now(timezone.utc)
    # Finalization is governed by monitor_until, not next_check_at. The inbox
    # cycle intentionally advances next_check_at before this function runs;
    # reusing due_audits here would postpone every expired audit forever.
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM audits
            WHERE status='monitoring'
              AND monitor_until IS NOT NULL
              AND monitor_until<>''
              AND monitor_until<=?
            ORDER BY monitor_until
            LIMIT 100
            """,
            (now.isoformat(),),
        ).fetchall()
    for row in rows:
        audit = dict(row)
        assessment = assess_gap(db.events(audit["audit_id"]))
        status = assessment.result
        if status == "opportunity_detected":
            status = "outreach_ready"
        elif status == "monitoring":
            status = "manual_review"
        update_sheet_row(
            SETTINGS.spreadsheet_id,
            SETTINGS.sheet_name,
            audit["sheet_row"],
            HEADERS,
            {
                "status": status,
                "opportunity_status": "yes" if status == "outreach_ready" else "no",
                "gap_types": ", ".join(assessment.gap_types),
                "gap_reason": assessment.gap_reason,
                "outreach_reason": assessment.outreach_reason,
                "checklist_passed": ", ".join(assessment.checklist_passed),
                "checklist_failed": ", ".join(assessment.checklist_failed),
                "checklist_unknown": ", ".join(assessment.checklist_unknown),
                "do_not_sequence": status != "outreach_ready",
                "last_checked_at": utcnow(),
            },
        )
        # Update durable machine state only after the operator-facing Sheet
        # succeeds. If Sheets fails, the audit remains monitoring and the next
        # cycle retries finalization instead of leaving the two stores split.
        db.update_audit(
            audit["audit_id"],
            status=status,
            opportunity_status="yes" if status == "outreach_ready" else "no",
            gap_types=json.dumps(assessment.gap_types),
            gap_reason=assessment.gap_reason,
            outreach_reason=assessment.outreach_reason,
            do_not_sequence=0 if status == "outreach_ready" else 1,
        )
        finalized.append({"audit_id": audit["audit_id"], "status": status})
    return finalized


def reconcile_terminal_audit_sheet(db: Database, audit_id: str) -> dict:
    audit = db.get_audit(audit_id)
    if not audit:
        raise ValueError(f"Unknown audit: {audit_id}")
    terminal = {
        "outreach_ready", "no_gap_detected", "manual_review", "audit_failed",
        "do_not_contact",
    }
    if audit["status"] not in terminal:
        raise ValueError(f"Audit is not terminal: {audit['status']}")
    try:
        gap_types = ", ".join(json.loads(audit.get("gap_types") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        gap_types = str(audit.get("gap_types") or "")
    update_sheet_row(
        SETTINGS.spreadsheet_id,
        SETTINGS.sheet_name,
        audit["sheet_row"],
        HEADERS,
        {
            "status": audit["status"],
            "opportunity_status": audit.get("opportunity_status") or "no",
            "gap_types": gap_types,
            "gap_reason": audit.get("gap_reason") or "",
            "outreach_reason": audit.get("outreach_reason") or "",
            "checklist_passed": "",
            "checklist_failed": "",
            "checklist_unknown": "",
            "do_not_sequence": bool(audit.get("do_not_sequence", 1)),
            "last_checked_at": utcnow(),
        },
    )
    return {"audit_id": audit_id, "status": audit["status"], "reconciled": True}


def run_discovery_cycle() -> dict:
    missing = [
        name
        for name in ("GOOGLE_OAUTH_JSON", "OPENAI_API_KEY")
        if not os.getenv(name)
        or os.getenv(name, "").startswith("CONFIGURE_")
        or os.getenv(name) == "{}"
    ]
    if missing:
        return {
            "status": "configuration_required",
            "missing": missing,
            "live_submissions": SETTINGS.live_submissions,
        }
    db = Database(SETTINGS.database_path)
    return {
        "ingested": ingest_queue(db),
        "processed": asyncio.run(process_discovery(db)),
        "live_submissions": SETTINGS.live_submissions,
    }


def run_inbox_cycle() -> list[dict] | dict:
    if (
        os.getenv("GOOGLE_OAUTH_JSON") in {None, "{}", "CONFIGURE_ME"}
        or os.getenv("OPENAI_API_KEY") in {None, "CONFIGURE_ME"}
    ):
        return {"status": "configuration_required"}
    db = Database(SETTINGS.database_path)
    processed = monitor_inbox(db)
    return {
        "status": "success",
        "processed": processed,
        "attribution_counts": db.inbound_attribution_counts(),
    }


def run_finalization_cycle() -> list[dict] | dict:
    if os.getenv("OPENAI_API_KEY") in {None, "CONFIGURE_ME"}:
        return {"status": "configuration_required"}
    db = Database(SETTINGS.database_path)
    return {
        "cancellations": asyncio.run(cancel_due_bookings(db)),
        "finalized": finalize_due(db),
    }
