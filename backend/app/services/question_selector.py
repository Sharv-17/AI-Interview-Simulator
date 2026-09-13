"""Deterministic baseline question selection for Stage 3.3.

Answers: "which question should we choose?" — separate from
question_repository.py, which only answers "what questions exist?".
This split matters because the future adaptive engine will replace
just this module's ranking step, not the repository.

Selection is intentionally simple and deterministic (no randomness) so
behavior is reproducible for testing and research evaluation:

1. Only questions matching the requested topic are considered — the
   selector never silently substitutes an unrelated topic.
2. Already-asked questions (by ID) are excluded.
3. Remaining candidates are ranked by `baseline_score` (topic +
   difficulty match); ties keep the question bank's original order.
4. If no candidate remains, `None` is returned. Callers decide how to
   handle "no question available" — this module never guesses.
"""

from typing import List, Optional

from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question
from app.services.question_scorer import baseline_score


def select_next_question(
    topic: str,
    difficulty: DifficultyLevel,
    asked_question_ids: Optional[List[str]] = None,
) -> Optional[Question]:
    """Select the next question for a candidate, or None if unavailable."""
    asked = set(asked_question_ids or [])

    candidates = [
        question
        for question in question_repository.get_by_topic(topic)
        if question.question_id not in asked
    ]
    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda q: baseline_score(q, topic, difficulty),
        reverse=True,
    )
    return ranked[0]