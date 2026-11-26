"""Reviewer-facing interview report.

Contains answers, scores, timing and integrity indicators. It NEVER contains the
reference answer or the rubric (expected concepts / evaluation criteria).

Reports of account-owned interviews require that account's session (see
app/api/auth_deps.py). A deployment must also consider this endpoint
(and the candidate history endpoints) behind access control.
"""

from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from app.schemas.candidate import InterviewSummary
from app.schemas.competency import CompetencyState, CompetencyUpdate
from app.schemas.evaluation import CodingEvaluation, ConceptualEvaluation, EvaluationStatus
from app.schemas.integrity import IntegrityRecord


class QuestionReport(BaseModel):
    sequence: int
    question_id: str
    question_text: Optional[str] = None
    topic: Optional[str] = None
    difficulty: Optional[str] = None
    question_type: Optional[str] = None
    state: str
    assigned_at: datetime
    closed_at: Optional[datetime] = None
    time_limit_seconds: int
    grace_seconds: int


class AnswerReport(BaseModel):
    answer_id: str
    question_id: str
    answer_text: str
    answer_source: str
    submission_reason: str
    language: Optional[str] = None
    submitted_at: datetime
    elapsed_seconds: float
    time_limit_seconds: int
    grace_seconds: int
    timed_out: bool
    evaluation_status: EvaluationStatus
    evaluation_attempts: int = 0
    evaluation_error: Optional[str] = None
    evaluator: Optional[str] = None
    evaluation: Optional[Union[ConceptualEvaluation, CodingEvaluation]] = None
    reasoning_summary: Optional[str] = Field(default=None, description="Reviewer-only explanation of the scores.")
    competency_update: Optional[CompetencyUpdate] = None


class InterviewReport(BaseModel):
    interview: InterviewSummary
    questions: List[QuestionReport]
    answers: List[AnswerReport]
    competency: Dict[str, CompetencyState]
    integrity_events: List[IntegrityRecord]
    integrity_summary: Dict[str, int] = Field(
        default_factory=dict, description="Counts per event type. Indicators for review, not proof of misconduct."
    )
