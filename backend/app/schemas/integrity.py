"""Pydantic models for question timing and copy/paste integrity metadata.

IMPORTANT ARCHITECTURE LIMITATION: the backend cannot independently
observe a browser's countdown, clipboard, tab switches, or window
focus. A future frontend is responsible for displaying the countdown
and for detecting/reporting copy or paste events; this module only
defines what the backend accepts and how it validates that reported
metadata. It never collects clipboard contents.

Integrity events are recorded as an indicator for later human review —
they are never used here to reject an answer or to label a candidate
as cheating.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SubmissionReason(str, Enum):
    """Why this answer is being submitted, as reported by the client.

    This is metadata only. The backend independently determines the
    authoritative `timed_out` flag from its own recorded server-side
    timing (see app/services/timer_service.py) — it never trusts this
    value as proof that a timeout actually occurred.
    """

    CANDIDATE_SUBMITTED = "candidate_submitted"
    TIMEOUT = "timeout"


class IntegrityEventType(str, Enum):
    """Allowed copy/paste integrity event types for this MVP."""

    COPY = "copy"
    PASTE = "paste"


class IntegrityEvent(BaseModel):
    """One client-reported copy/paste event for the current question.

    Deliberately minimal: no clipboard content is ever collected or
    stored — only that an event of this type occurred, and when.
    """

    event_type: IntegrityEventType
    occurred_at: Optional[datetime] = Field(
        default=None,
        description="Client-reported time the event occurred, if provided. Not trusted for timing decisions.",
    )
    source: Optional[str] = Field(default=None, description="Optional client-provided context, e.g. 'answer_box'")


class TimingMetadata(BaseModel):
    """Server-computed timing metadata for one answered question.

    question_started_at and submitted_at are both server-side UTC
    timestamps. question_started_at is recorded once, when the
    question became current, and is never reset — so elapsed_seconds
    only ever grows, and a candidate cannot extend their time by
    submitting more than once. elapsed_seconds and timed_out are both
    computed from these server timestamps, never from anything the
    client reports.
    """

    question_started_at: datetime
    submitted_at: datetime
    time_limit_seconds: int
    elapsed_seconds: float = Field(..., ge=0.0)
    timed_out: bool
    submission_reason: SubmissionReason
    integrity_events: List[IntegrityEvent] = Field(default_factory=list)