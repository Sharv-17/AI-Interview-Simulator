"""HTTP layer for browsing the question bank.

This is a read-only view over the question bank itself, useful for
debugging/testing the retrieval layer directly. It does NOT select a
question for an active interview — that stays the Interview Engine's
responsibility (app/services/interview_engine.py), which calls the
selector internally. Keeping these separate avoids two different
places being able to decide "what question is next".
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.schemas.question import QuestionPublic

router = APIRouter(prefix="/questions", tags=["questions"])


@router.get("", response_model=List[QuestionPublic])
def list_questions(
    topic: Optional[str] = Query(default=None, description="Filter by topic, e.g. 'Python'"),
    difficulty: Optional[DifficultyLevel] = Query(default=None, description="Filter by difficulty"),
) -> List[QuestionPublic]:
    """List questions in the bank, optionally filtered by topic and/or difficulty.

    Returns QuestionPublic, which omits the answer key (reference_answer,
    expected_concepts, evaluation_criteria).
    """
    if topic and difficulty:
        questions = question_repository.get_by_topic_and_difficulty(topic, difficulty)
    elif topic:
        questions = question_repository.get_by_topic(topic)
    elif difficulty:
        questions = question_repository.get_by_difficulty(difficulty)
    else:
        questions = question_repository.get_all()
    return [QuestionPublic.model_validate(q, from_attributes=True) for q in questions]


@router.get("/{question_id}", response_model=QuestionPublic)
def get_question(question_id: str) -> QuestionPublic:
    """Return one question for display to a candidate.

    Uses QuestionPublic, which omits the answer key.
    """
    question = question_repository.get_by_id(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return QuestionPublic.model_validate(question, from_attributes=True)