"""Pydantic models for question timing and interview-integrity indicators.

IMPORTANT ARCHITECTURE LIMITATION: the backend cannot independently observe a
browser's countdown, clipboard, tab switches, or window focus. The frontend is
responsible for displaying the countdown and for detecting and reporting these
events; this module defines what the backend accepts and how it validates it. It
never collects clipboard contents.

Integrity events are INDICATORS for later human review. They are never used to
reject an answer, change a score or label anyone a cheater. Server-side
indicators (late/duplicate/unassigned attempts, implausibly fast typing) are kept
separate from scoring in the same way.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SubmissionReason(str, Enum):
    """Why this answer is being submitted, as reported by the client.

    This is metadata only. The backend independently determines timing from its
    own server-side clock (see app/services/timer_service.py) and never trusts
    this value as proof that a timeout occurred.
    """

    CANDIDATE_SUBMITTED = "candidate_submitted"
    TIMEOUT = "timeout"


class IntegrityEventType(str, Enum):
    """Events a client may report. Clients cannot report server-side indicator types."""

    COPY = "copy"
    PASTE = "paste"
    TAB_SWITCH = "tab_switch"
    FOCUS_LOSS = "focus_loss"
    FOCUS_GAIN = "focus_gain"


class ServerIntegrityEventType(str, Enum):
    """Indicators the server records itself, from its own observations."""

    LATE_SUBMISSION_REJECTED = "late_submission_rejected"
    DUPLICATE_SUBMISSION = "duplicate_submission"
    UNASSIGNED_QUESTION_ATTEMPT = "unassigned_question_attempt"
    FAST_SUBMISSION = "fast_submission"


class IntegrityEvent(BaseModel):
    """One client-reported event for the current question.

    Deliberately small and fully validated: no free-form metadata, no clipboard
    content. `occurred_at` is the CLIENT's clock and is stored as reported but is
    never trusted for any timing decision; the server records its own receive time.
    """

    event_type: IntegrityEventType
    occurred_at: Optional[datetime] = Field(
        default=None,
        description="Client-reported time the event occurred, if provided. Not trusted for timing decisions.",
    )
    source: Optional[str] = Field(default=None, max_length=64, description="Optional context, e.g. 'answer_box'")
    duration_ms: Optional[int] = Field(
        default=None, ge=0, le=86_400_000, description="For focus_loss/tab_switch: how long the page was away."
    )


class IntegrityEventsRequest(BaseModel):
    """A batch of client-reported events (frontend sends these as they happen)."""

    question_id: Optional[str] = Field(
        default=None, max_length=64, description="Must be the current question; defaults to it."
    )
    events: List[IntegrityEvent] = Field(..., min_length=1, max_length=50)


class IntegrityEventsResponse(BaseModel):
    interview_id: str
    question_id: str
    recorded: int


class IntegrityRecord(BaseModel):
    """A stored indicator, as shown to reviewers."""

    event_type: str
    source: str  # "client" | "server"
    question_id: Optional[str] = None
    answer_id: Optional[str] = None
    client_occurred_at: Optional[datetime] = None
    received_at: datetime
    duration_ms: Optional[int] = None
    detail: dict = Field(default_factory=dict)


class TimingMetadata(BaseModel):
    """Server-computed timing metadata for one answered question.

    question_started_at and submitted_at are both server-side UTC timestamps.
    question_started_at is recorded once, when the question was assigned, and is
    never reset. `timed_out` means the answer arrived after the nominal
    time limit (so it used part of the grace period); answers after
    limit + grace are rejected and never reach this model.
    """

    question_started_at: datetime
    submitted_at: datetime
    time_limit_seconds: int
    grace_seconds: int = 0
    elapsed_seconds: float = Field(..., ge=0.0)
    timed_out: bool
    submission_reason: SubmissionReason
    integrity_events: List[IntegrityEvent] = Field(default_factory=list)
