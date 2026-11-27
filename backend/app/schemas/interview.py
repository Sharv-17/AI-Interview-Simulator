"""Pydantic models for interview requests and responses.

These models are the validation boundary for the interview API. They
define what a client can send us and what shape we promise to send back.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

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


class QuestionState(str, Enum):
    """Where the CURRENT question is in its life cycle."""

    ACTIVE = "active"  # waiting for the candidate's answer
    EVALUATION_PENDING = "evaluation_pending"  # answer saved, evaluator unavailable: retry
    EVALUATION_FAILED = "evaluation_failed"  # answer saved, evaluator output unusable: retry
    EVALUATED = "evaluated"  # scored; competency updated
    TIMED_OUT = "timed_out"  # deadline passed without an accepted answer


class NextAction(str, Enum):
    """What the frontend should do next."""

    ANSWER = "answer"
    RETRY_EVALUATION = "retry_evaluation"
    ADVANCE = "advance"  # call POST /interview/{id}/next
    COMPLETED = "completed"
    NONE = "none"  # no question could be assigned (e.g. unknown topic)


class InterviewStartRequest(BaseModel):
    """Payload required to start a new interview."""

    candidate_id: Optional[str] = Field(
        default=None, max_length=64, description="Existing candidate; an anonymous one is created if omitted."
    )
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
    current_question_id: Optional[str] = None
    status: InterviewStatus
    candidate_id: Optional[str] = None
    question_state: Optional[QuestionState] = None
    next_action: NextAction = NextAction.NONE
    question_started_at: Optional[datetime] = None
    question_time_limit_seconds: Optional[int] = Field(
        default=None, description="Nominal time limit for the current question (its estimated time)."
    )
    grace_seconds: Optional[int] = Field(default=None, description="Extra seconds an answer is still accepted.")
    deadline_at: Optional[datetime] = Field(
        default=None, description="Server deadline: started + limit + grace. Later answers are rejected (409)."
    )
    seconds_remaining: Optional[float] = Field(
        default=None, description="Seconds left of the nominal limit (>= 0), for a countdown display."
    )