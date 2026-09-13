"""HTTP layer for browsing the question bank.

This is a read-only view over the question bank itself, useful for
debugging/testing the retrieval layer directly. It does NOT select a
question for an active interview — that stays the Interview Engine's
responsibility (app/services/interview_engine.py), which calls the
selector internally. Keeping these separate avoids two different
places being able to decide "what question is next".
"""

from typing import List, Optional

from fastapi import APIRouter, Query

from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question

router = APIRouter(prefix="/questions", tags=["questions"])


@router.get("", response_model=List[Question])
def list_questions(
    topic: Optional[str] = Query(default=None, description="Filter by topic, e.g. 'Python'"),
    difficulty: Optional[DifficultyLevel] = Query(default=None, description="Filter by difficulty"),
) -> List[Question]:
    """List questions in the bank, optionally filtered by topic and/or difficulty."""
    if topic and difficulty:
        return question_repository.get_by_topic_and_difficulty(topic, difficulty)
    if topic:
        return question_repository.get_by_topic(topic)
    if difficulty:
        return question_repository.get_by_difficulty(difficulty)
    return question_repository.get_all()