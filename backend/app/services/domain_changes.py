"""Records of what an interview operation changed (an outbox).

The interview domain (InterviewSession) is storage-agnostic. Every state change
it makes is also appended to `session.changes` as one of these records. A
PostgreSQL store turns them into SQL inside one transaction; the in-memory store
simply discards them. This keeps the rules in ONE place and persistence a
separate concern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Union

from app.schemas.competency import CompetencyUpdate
from app.schemas.evaluation import CodingEvaluation, ConceptualEvaluation, EvaluationStatus


@dataclass
class QuestionAssigned:
    question_id: str
    sequence: int
    assigned_at: datetime
    time_limit_seconds: int
    grace_seconds: int


@dataclass
class QuestionTimedOut:
    question_id: str
    at: datetime


@dataclass
class AnswerRecorded:
    answer_id: str
    question_id: str
    answer_text: str
    answer_source: str
    submission_reason: str
    language: Optional[str]
    submitted_at: datetime
    elapsed_seconds: float
    time_limit_seconds: int
    grace_seconds: int
    timed_out: bool


@dataclass
class EvaluationCompleted:
    answer_id: str
    question_id: str
    evaluation: Union[ConceptualEvaluation, CodingEvaluation]
    evaluator: Optional[str]
    competency_id: str
    competency_update: CompetencyUpdate
    last_score: float
    at: datetime
    attempts: int


@dataclass
class EvaluationFailed:
    answer_id: str
    status: EvaluationStatus
    error_code: str
    attempts: int
    at: datetime


@dataclass
class IntegrityLogged:
    event_type: str
    source: str  # "client" | "server"
    received_at: datetime
    question_id: Optional[str] = None
    answer_id: Optional[str] = None
    client_occurred_at: Optional[datetime] = None
    client_source: Optional[str] = None
    duration_ms: Optional[int] = None
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InterviewCompleted:
    at: datetime


Change = Union[
    QuestionAssigned,
    QuestionTimedOut,
    AnswerRecorded,
    EvaluationCompleted,
    EvaluationFailed,
    IntegrityLogged,
    InterviewCompleted,
]
