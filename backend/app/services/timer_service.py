"""Question timing (Stage 3.6): elapsed-time and timeout checks.

Authoritative timing is always computed server-side, from
question_started_at (recorded once, when the question became current)
compared against the current server time — never from a client-
reported timestamp. This is what prevents a candidate from extending
their time by resubmitting: question_started_at is set once per
question and is never reset by additional requests.

The backend cannot observe a browser's own visible countdown; this
module only answers "has the server-side time budget for this
question been exceeded", independent of whatever the client claims via
submission_reason.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.config import DEFAULT_QUESTION_TIME_LIMIT_SECONDS


def elapsed_seconds(question_started_at: datetime, at: datetime) -> float:
    """Seconds between question_started_at and at. Never negative."""
    delta = (at - question_started_at).total_seconds()
    return max(0.0, delta)


def check_timeout(
    question_started_at: datetime,
    time_limit_seconds: int = DEFAULT_QUESTION_TIME_LIMIT_SECONDS,
    at: Optional[datetime] = None,
) -> Tuple[bool, float]:
    """Return (timed_out, elapsed_seconds) as of `at` (defaults to now, UTC).

    `at` is exposed as a parameter specifically so tests can check
    long-elapsed-time behavior with fixed timestamps instead of really
    waiting 90+ seconds.
    """
    if at is None:
        at = datetime.now(timezone.utc)
    elapsed = elapsed_seconds(question_started_at, at)
    return elapsed > time_limit_seconds, elapsed


def deadline(question_started_at: datetime, time_limit_seconds: int, grace_seconds: int = 0) -> datetime:
    """The last instant an answer is accepted: start + time limit + grace period."""
    return question_started_at + timedelta(seconds=time_limit_seconds + grace_seconds)


def is_past_deadline(
    question_started_at: datetime,
    time_limit_seconds: int,
    grace_seconds: int = 0,
    at: Optional[datetime] = None,
) -> bool:
    """True once `at` (default: now, UTC) is later than the answer deadline."""
    if at is None:
        at = datetime.now(timezone.utc)
    return at > deadline(question_started_at, time_limit_seconds, grace_seconds)

