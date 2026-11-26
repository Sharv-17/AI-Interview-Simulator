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

Candidate cooldown rotation
---------------------------
Selection is candidate-aware: previously assigned questions of the same topic
(see `encountered`) are rotated out before fresh ones. The priority is:

  1. never-seen questions first (ranked by QScore as above);
  2. when none are left, the least recently assigned questions;
  3. seen questions are never excluded permanently.

`encountered` maps question_id -> most recent assignment time. It only
reorders eligible candidates: servability, anti-streak, requested initial
difficulty and no-repeat-within-interview are all applied first and unchanged.

Tie-breaking and controlled randomisation
-----------------------------------------
QScore depends only on (theta, difficulty), so many questions tie exactly.
Candidates tied on the winning rank key are ordered by question_id (so the
result never depends on repository order) and ONE is chosen with an injectable
random generator (`rng`). Randomness never crosses tiers, difficulties or the
guard above; tests pass a seeded generator for deterministic assertions.

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
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

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


# Default generator for tie-breaking only; tests inject a seeded one.
_RNG = random.Random()

# question_id -> most recent assignment time (any storage backend).
Encountered = Mapping[str, datetime]


def _tie_group(qscores: Mapping[str, Optional[float]], ranked_ids: Sequence[str]) -> List[str]:
    """IDs sharing the best (12-decimal) QScore, sorted so order never depends on the bank."""
    best = round(qscores[ranked_ids[0]], 12)
    return sorted(qid for qid in ranked_ids if round(qscores[qid], 12) == best)


def _baseline_choice(
    candidates: Sequence[Question],
    topic: str,
    difficulty: DifficultyLevel,
    rng: Optional[random.Random] = None,
) -> Question:
    """Cold-start choice: best baseline_score; random among exact ties (id-sorted)."""
    best = max(baseline_score(q, topic, difficulty) for q in candidates)
    tied = sorted(
        (q for q in candidates if baseline_score(q, topic, difficulty) == best),
        key=lambda q: q.question_id,
    )
    return (rng or _RNG).choice(tied)


def _cold_start_choice(
    candidates: Sequence[Question],
    topic: str,
    difficulty: DifficultyLevel,
    encountered: Encountered,
    rng: Optional[random.Random],
) -> Question:
    """First question: the requested difficulty wins, then cooldown, then baseline score."""
    requested = [q for q in candidates if q.difficulty == difficulty]
    pool = requested or list(candidates)
    unseen = [q for q in pool if q.question_id not in encountered]
    if unseen:
        pool = unseen
    else:
        # Everything available has been seen: rotate by least-recent assignment,
        # the same cooldown rule the adaptive tier uses.
        seen = [q for q in pool if q.question_id in encountered]
        if seen:
            oldest = min(encountered[q.question_id] for q in seen)
            pool = [q for q in seen if encountered[q.question_id] == oldest]
    return _baseline_choice(pool, topic, difficulty, rng)


def _adaptive_choice(
    candidates: Sequence[Question],
    competency_states: Mapping[str, Any],
    encountered: Encountered,
    topic: str,
    difficulty: DifficultyLevel,
    rng: Optional[random.Random],
) -> Question:
    """Unseen tier (QScore) first; otherwise least-recently-assigned, then QScore."""
    qscores: Dict[str, Optional[float]] = {
        item.question_id: item.qscore for item in score_candidates(candidates, competency_states)
    }
    by_id = {question.question_id: question for question in candidates}

    def best_in(pool: Sequence[Question]) -> Optional[str]:
        ranked = rank_by_qscore([(q.question_id, qscores[q.question_id]) for q in pool])
        if not ranked:
            return None
        return (rng or _RNG).choice(_tie_group(qscores, ranked))

    unseen = [q for q in candidates if q.question_id not in encountered]
    if unseen:
        chosen_id = best_in(unseen)
    else:
        oldest = min(encountered[q.question_id] for q in candidates)
        chosen_id = best_in([q for q in candidates if encountered[q.question_id] == oldest])
    if chosen_id is None:
        return _baseline_choice(candidates, topic, difficulty, rng)
    return by_id[chosen_id]


def select_next_question(
    topic: str,
    difficulty: DifficultyLevel,
    asked_question_ids: Optional[Sequence[str]] = None,
    competency_states: Optional[Mapping[str, Any]] = None,
    encountered: Optional[Encountered] = None,
    rng: Optional[random.Random] = None,
) -> Optional[Question]:
    """Select the next question for a candidate, or None if none is available.

    `asked_question_ids` must be in the order the questions were asked.
    `competency_states` maps competency_id -> state (anything with `.theta`);
    when empty or None the selector is in cold-start mode.
    `encountered` maps question_id -> most recent assignment time for THIS
    candidate and topic (empty/None for an anonymous or first interview).
    """
    asked_list = list(asked_question_ids or [])
    asked = set(asked_list)
    history = encountered or {}

    candidates = [
        question
        for question in question_repository.get_by_topic(topic)
        if question.question_id not in asked and question.is_servable
    ]
    if not candidates:
        return None

    if not competency_states:
        return _cold_start_choice(candidates, topic, difficulty, history, rng)

    streak_difficulty = _recent_streak_difficulty(asked_list)
    if streak_difficulty is not None:
        alternatives = [q for q in candidates if q.difficulty != streak_difficulty]
        if alternatives:
            candidates = alternatives

    return _adaptive_choice(candidates, competency_states, history, topic, difficulty, rng)