"""Competency state (theta) estimation and update.

This module implements ONLY theta — the estimated competency state —
per the research architecture:

    theta -> H(theta) -> IDI -> DifficultyFit -> QScore

Shannon entropy H(theta), IDI, DifficultyFit, and the final QScore are
NOT implemented here or anywhere else in the codebase yet. Nothing in
this module ranks, selects, or adjusts question difficulty — it only
tracks an estimate of how well the candidate appears to be doing on
each competency, based on evaluated answers.

Update formula (fixed research design constant — do not change alpha):

    theta_new = (1 - alpha) * theta_old + alpha * S

    theta_old = previous competency estimate
    S         = normalized answer score, in [0,1] (overall_score / 10)
    alpha     = EMA_ALPHA = 0.15

theta always starts at THETA_INITIAL = 0.5 (neutral) the first time a
competency is encountered, and is clamped to [0,1] on every update.

Competency state belongs to a single interview session — see
CompetencyStateStore below, one instance of which is owned by each
InterviewSession. It is never shared globally across interviews.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from app.schemas.competency import (
    EMA_ALPHA,
    THETA_INITIAL,
    THETA_MAX,
    THETA_MIN,
    CompetencyState,
    CompetencyUpdate,
)
from app.schemas.question import Question

_FALLBACK_COMPETENCY_ID = "unspecified"


def resolve_competency_id(question: Question) -> str:
    """Pick which competency label to update for this question.

    Preference order: explicit competency -> subtopic -> topic -> a
    safe fallback label. This never raises — a question with no usable
    label at all is tracked under a fallback bucket rather than
    crashing the interview.
    """
    for candidate in (question.competency, question.subtopic, question.topic):
        if candidate and candidate.strip():
            return candidate.strip()
    return _FALLBACK_COMPETENCY_ID


def normalize_score(overall_score: float) -> float:
    """Convert a 0-10 overall_score into a normalized score in [0,1]."""
    normalized = overall_score / 10.0
    return max(0.0, min(1.0, normalized))


def apply_ema(theta_old: float, normalized_score: float, alpha: float = EMA_ALPHA) -> float:
    """theta_new = (1 - alpha) * theta_old + alpha * normalized_score, clamped to [0,1]."""
    theta_new = (1 - alpha) * theta_old + alpha * normalized_score
    return max(THETA_MIN, min(THETA_MAX, theta_new))


class CompetencyStateStore:
    """Holds one interview's estimated competency state, keyed by competency ID.

    Competencies are initialized lazily: nothing exists until the first
    answer touching that competency is evaluated, at which point it
    starts at THETA_INITIAL = 0.5.
    """

    def __init__(self) -> None:
        self._states: Dict[str, CompetencyState] = {}

    def _get_or_create(self, competency_id: str) -> CompetencyState:
        if competency_id not in self._states:
            self._states[competency_id] = CompetencyState(
                competency_id=competency_id,
                theta=THETA_INITIAL,
                questions_attempted=0,
                last_score=None,
                last_updated=datetime.now(timezone.utc),
            )
        return self._states[competency_id]

    def update_from_answer(self, question: Question, overall_score: float) -> CompetencyUpdate:
        """Update the competency associated with `question` from one evaluated answer."""
        competency_id = resolve_competency_id(question)
        state = self._get_or_create(competency_id)

        normalized_score = normalize_score(overall_score)
        previous_theta = state.theta
        new_theta = apply_ema(previous_theta, normalized_score)

        state.theta = new_theta
        state.questions_attempted += 1
        state.last_score = normalized_score
        state.last_updated = datetime.now(timezone.utc)

        return CompetencyUpdate(
            competency=competency_id,
            previous_theta=previous_theta,
            normalized_score=normalized_score,
            new_theta=new_theta,
            questions_attempted=state.questions_attempted,
        )

    def get(self, competency_id: str) -> Optional[CompetencyState]:
        """Return the current state for one competency, or None if untouched."""
        return self._states.get(competency_id)

    def get_all(self) -> Dict[str, CompetencyState]:
        """Return every competency state tracked so far in this interview."""
        return dict(self._states)