"""Pydantic models for the question bank.

Reuses DifficultyLevel from schemas/interview.py so an interview's
difficulty and a question's difficulty are always validated against
the same set of values.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.interview import DifficultyLevel


class QuestionType(str, Enum):
    """Allowed question types."""

    CONCEPTUAL = "conceptual"
    CODING = "coding"


class Question(BaseModel):
    """A single question bank entry."""

    question_id: str = Field(..., description="Unique identifier, e.g. 'python-001'")
    question_text: str
    topic: str
    subtopic: Optional[str] = None
    difficulty: DifficultyLevel
    question_type: QuestionType
    competency: str
    tags: List[str] = Field(default_factory=list)
    reference_answer: Optional[str] = Field(
        default=None,
        description="Optional model/reference answer for this question. Not used for grading at this stage.",
    )

    @field_validator("question_id", "question_text", "topic", "competency")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()