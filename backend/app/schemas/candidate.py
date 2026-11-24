"""Candidate and history models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.interview import DifficultyLevel, InterviewStatus


class CandidateCreate(BaseModel):
    """Candidates are lightweight records: there is no login in this backend."""

    display_name: Optional[str] = Field(default=None, max_length=120)
    external_id: Optional[str] = Field(default=None, max_length=120, description="Caller's own identifier, unique.")


class CandidateView(BaseModel):
    candidate_id: str
    display_name: Optional[str] = None
    external_id: Optional[str] = None
    created_at: datetime


class InterviewSummary(BaseModel):
    interview_id: str
    candidate_id: Optional[str] = None
    topic: str
    difficulty: DifficultyLevel
    question_count: int
    current_question: int
    status: InterviewStatus
    created_at: datetime
    completed_at: Optional[datetime] = None


class CompetencyHistoryEntry(BaseModel):
    """One competency update (one evaluated answer). EMA, alpha = 0.15."""

    interview_id: str
    competency_id: str
    answer_id: str
    question_id: str
    previous_theta: float
    new_theta: float
    normalized_score: float
    questions_attempted: int
    recorded_at: datetime
