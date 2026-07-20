from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AuditStatus = Literal[
    "queued",
    "discovery_complete",
    "awaiting_required_input",
    "submitted",
    "monitoring",
    "opportunity_detected",
    "no_gap_detected",
    "manual_review",
    "audit_failed",
    "do_not_contact",
    "outreach_ready",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormField(StrictModel):
    selector: str
    name: str = ""
    label: str = ""
    field_type: str = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)


class FunnelCandidate(StrictModel):
    page_url: str
    entry_type: Literal["form", "popup", "iframe", "booking", "unknown"]
    offer_text: str = ""
    submit_selector: str = ""
    fields: list[FormField] = Field(default_factory=list)
    captcha_detected: bool = False
    payment_detected: bool = False
    sensitive_detected: bool = False
    screenshot_path: str = ""
    form_fingerprint: str = ""
    reveal_cta_text: str = ""
    reveal_cta_href: str = ""
    discovery_rank: int = 0


class FieldValue(StrictModel):
    field: str
    value: str


class SubmissionDecision(StrictModel):
    action: Literal["submit", "manual_review", "skip"]
    reason: str
    field_values: list[FieldValue] = Field(default_factory=list)
    is_required_lead_magnet_booking: bool = False


class EmailAssessment(StrictModel):
    message_type: Literal[
        "confirmation",
        "delivery",
        "follow_up",
        "meeting_reminder",
        "no_show_recovery",
        "calendar_not_booked_follow_up",
        "cancellation",
        "unrelated",
    ]
    promised_asset_delivered: bool = False
    requires_action_from_lead: bool = False
    meeting_reminder_timing: Literal["24h_before", "1h_before", "other", "none"] = "none"
    no_show_recovery_step: Literal["15m_after", "24h_after", "3d_after", "other", "none"] = "none"
    response_time_quality: Literal["instant", "timely", "slow", "unknown"] = "unknown"
    broken_link_evidence: list[str] = Field(default_factory=list)
    copy_weaknesses: list[str] = Field(default_factory=list)
    cancellation_url: str = ""
    scheduled_start: str = ""
    evidence_summary: str = ""


class GapAssessment(StrictModel):
    result: Literal[
        "opportunity_detected", "no_gap_detected", "manual_review", "monitoring"
    ]
    checklist_passed: list[str] = Field(default_factory=list)
    checklist_failed: list[str] = Field(default_factory=list)
    checklist_unknown: list[str] = Field(default_factory=list)
    gap_types: list[str] = Field(default_factory=list)
    gap_reason: str = ""
    outreach_reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
