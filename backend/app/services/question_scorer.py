"""Baseline candidate-question scoring for Stage 3.3.

IMPORTANT: `baseline_score` is a simple, deterministic heuristic used
only to rank candidates for THIS stage. It is NOT the final research
QScore(question, theta) described in the project's adaptive-selection
model. The final QScore will be derived from theta, H(theta), IDI, and
DifficultyFit once that mathematical model is formally defined — do
not extend this function to anticipate that formula.
"""

from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question

_TOPIC_MATCH_WEIGHT = 2
_DIFFICULTY_MATCH_WEIGHT = 1


def baseline_score(question: Question, topic: str, difficulty: DifficultyLevel) -> int:
    """Score one candidate question for a requested topic/difficulty.

    Higher is better. This only rewards exact topic and difficulty
    matches — it deliberately does not model competency, uncertainty,
    or repetition; those are out of scope for this stage.
    """
    score = 0
    if question.topic.lower() == topic.lower():
        score += _TOPIC_MATCH_WEIGHT
    if question.difficulty == difficulty:
        score += _DIFFICULTY_MATCH_WEIGHT
    return score