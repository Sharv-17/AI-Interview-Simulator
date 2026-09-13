"""Pydantic models for interview requests and responses.

These models are the validation boundary for the interview API. They
define what a client can send us and what shape we promise to send back.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class DifficultyLevel(str, Enum):
    """Allowed difficulty levels for an interview."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class InterviewStatus(str, Enum):
    """Allowed lifecycle states for an interview session."""

    ACTIVE = "active"
    COMPLETED = "completed"


class InterviewStartRequest(BaseModel):
    """Payload required to start a new interview."""

    topic: str = Field(..., description="Interview topic, e.g. 'Python'")
    difficulty: DifficultyLevel
    question_count: int = Field(
        ..., ge=1, le=20, description="Number of questions in the interview (1-20)"
    )

    @field_validator("topic")
    @classmethod
    def topic_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("topic must not be empty")
        return value.strip()


class InterviewResponse(BaseModel):
    """Shape of an interview session returned to the client."""

    interview_id: str
    topic: str
    difficulty: DifficultyLevel
    question_count: int
    current_question: int
    status: InterviewStatus