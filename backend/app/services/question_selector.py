"""Question selection: cold-start baseline + adaptive QScore ranking.

Answers "which question should we ask next?" (question_repository.py only
answers "what questions exist?").

Eligibility (always applied)
----------------------------
A candidate question must (1) match the interview's topic, (2) not already
have been asked, and (3) be servable (Question.is_servable: review status
`needs_manual_review` / `requires_coding_evaluation` are never asked).

Two modes
---------
* COLD START -- no competency history yet (the first question of an
  interview). Uses the interview's requested difficulty via `baseline_score`.
  Deterministic and independent of theta.
* ADAPTIVE -- once at least one answer has updated a competency, every
  candidate is ranked by QScore (see app/services/adaptive_metrics.py and
  docs/MATHEMATICAL_SPEC.md):

      theta  -> H(theta) -> IDI -> DifficultyFit -> QScore
      QScore = 0.5 * IDI(theta) + 0.5 * DifficultyFit(theta, d)

  theta is the candidate's estimated competency for the question's
  competency (the documented prior 0.5 if that competency has no history).
  The requested interview difficulty is NOT used in this mode: difficulty
  follows theta.

Determinism and tie-breaking
----------------------------
No randomness anywhere. Ranking is QScore descending, then question_id
ascending, so the result does not depend on the order candidates arrive in.

Anti-streak guard
-----------------
If the last STREAK_LIMIT questions asked all had the same difficulty, and
candidates of a different difficulty exist, only those are considered. This
guarantees the selector never asks more than STREAK_LIMIT questions of one
difficulty in a row while an alternative exists. STREAK_LIMIT is an
implementation assumption (a simple exploration constraint), not a research
result. If no alternative exists the guard does nothing (never a dead end).

Safe fallbacks
--------------
* A competency state with an invalid theta (NaN, outside [0,1], not a number)
  is ignored and the prior is used; a warning is logged.
* If no candidate can be scored (e.g. an unknown difficulty label), the
  baseline ordering is used rather than returning nothing.
"""

import logging
import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence

from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question
from app.services.adaptive_metrics import rank_by_qscore, score_candidate
from app.services.competency_state import resolve_competency_id
from app.services.question_scorer import baseline_score

logger = logging.getLogger(__name__)

# Never ask more than this many same-difficulty questions in a row while a
# different difficulty is available. Implementation assumption; see module docstring.
STREAK_LIMIT = 3


@dataclass(frozen=True)
class ScoredCandidate:
    """Every number behind one candidate's QScore (for transparency and tests)."""

    question_id: str
    competency_id: str
    has_history: bool
    theta: float
    entropy: float
    idi: float
    difficulty_value: Optional[float]
    difficulty_fit: Optional[float]
    qscore: Optional[float]


def _usable_state(competency_id: str, state: Any) -> Any:
    """Return the state if its theta is a valid number in [0, 1], else None."""
    if state is None:
        return None
    theta = getattr(state, "theta", None)
    valid = (
        isinstance(theta, (int, float))
        and not isinstance(theta, bool)
        and math.isfinite(theta)
        and 0.0 <= theta <= 1.0
    )
    if not valid:
        logger.warning("Ignoring invalid competency state for %r; using the prior theta.", competency_id)
        return None
    return state


def score_candidates(
    candidates: Sequence[Question],
    competency_states: Optional[Mapping[str, Any]] = None,
) -> List[ScoredCandidate]:
    """Compute theta -> H -> IDI -> DifficultyFit -> QScore for each candidate.

    Read-only: never modifies competency state. Output order matches input order.
    """
    states = competency_states or {}
    scored: List[ScoredCandidate] = []
    for question in candidates:
        competency_id = resolve_competency_id(question)
        state = _usable_state(competency_id, states.get(competency_id))
        result = score_candidate(question.difficulty, state)
        scored.append(
            ScoredCandidate(
                question_id=question.question_id,
                competency_id=competency_id,
                has_history=state is not None,
                theta=result.theta,
                entropy=result.entropy,
                idi=result.idi,
                difficulty_value=result.difficulty_value,
                difficulty_fit=result.difficulty_fit,
                qscore=result.qscore,
            )
        )
    return scored


def _recent_streak_difficulty(asked_question_ids: Sequence[str]) -> Optional[DifficultyLevel]:
    """The difficulty shared by the last STREAK_LIMIT asked questions, if they all match."""
    recent = list(asked_question_ids)[-STREAK_LIMIT:]
    if len(recent) < STREAK_LIMIT:
        return None
    difficulties = []
    for question_id in recent:
        question = question_repository.get_by_id(question_id)
        if question is None:
            return None
        difficulties.append(question.difficulty)
    return difficulties[0] if len(set(difficulties)) == 1 else None


def _baseline_choice(candidates: Sequence[Question], topic: str, difficulty: DifficultyLevel) -> Question:
    """Cold-start choice: best baseline_score (topic + requested difficulty); ties keep bank order."""
    ranked = sorted(candidates, key=lambda q: baseline_score(q, topic, difficulty), reverse=True)
    return ranked[0]


def select_next_question(
    topic: str,
    difficulty: DifficultyLevel,
    asked_question_ids: Optional[Sequence[str]] = None,
    competency_states: Optional[Mapping[str, Any]] = None,
) -> Optional[Question]:
    """Select the next question for a candidate, or None if none is available.

    `asked_question_ids` must be in the order the questions were asked.
    `competency_states` maps competency_id -> state (anything with `.theta`);
    when empty or None the selector is in cold-start mode.
    """
    asked_list = list(asked_question_ids or [])
    asked = set(asked_list)

    candidates = [
        question
        for question in question_repository.get_by_topic(topic)
        if question.question_id not in asked and question.is_servable
    ]
    if not candidates:
        return None

    if not competency_states:
        return _baseline_choice(candidates, topic, difficulty)

    streak_difficulty = _recent_streak_difficulty(asked_list)
    if streak_difficulty is not None:
        alternatives = [q for q in candidates if q.difficulty != streak_difficulty]
        if alternatives:
            candidates = alternatives

    scored = score_candidates(candidates, competency_states)
    ranked_ids = rank_by_qscore([(item.question_id, item.qscore) for item in scored])
    if not ranked_ids:
        return _baseline_choice(candidates, topic, difficulty)

    by_id = {question.question_id: question for question in candidates}
    return by_id[ranked_ids[0]]