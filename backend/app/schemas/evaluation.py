"""Pydantic models for answer evaluation results.

ConceptualEvaluation and CodingEvaluation share a small common shape
(question_id, question_type, overall_score, feedback, strengths,
weaknesses) via EvaluationBase, with type-specific fields added in each
subclass. This lets the Interview Engine and API layer work with either
result generically wherever they only need the common fields.
"""

from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator
from app.schemas.competency import CompetencyUpdate
from app.schemas.question import QuestionType
from app.schemas.integrity import IntegrityEvent, SubmissionReason, TimingMetadata
from app.schemas.interview import NextAction
from app import config

SCORE_MIN = 0
SCORE_MAX = 10


class AnswerSource(str, Enum):
    """How the submitted answer text was produced (client-reported metadata)."""

    TEXT = "text"
    VOICE = "voice"


class EvaluationStatus(str, Enum):
    """State of the evaluation of one recorded answer.

    completed: scored. pending: not scored yet (evaluator unavailable; retry).
    failed: the evaluator gave unusable output; retry allowed until retries run out.
    No score and no competency update exist unless the status is `completed`.
    """

    COMPLETED = "completed"
    PENDING = "pending"
    FAILED = "failed"


class ExecutionStatus(str, Enum):
    """Outcome of attempting to evaluate a coding answer."""

    COMPLETED = "completed"
    SKIPPED = "skipped"  # no test cases configured for this question yet
    ERROR = "error"


class EvaluationBase(BaseModel):
    """Fields common to every evaluation result, regardless of question type."""

    question_id: str
    question_type: QuestionType
    overall_score: float = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    max_score: float = SCORE_MAX
    feedback: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    evaluator: Optional[str] = Field(
        default=None, description="Who produced this score, e.g. 'anthropic:<model>' or 'mock'."
    )
    evaluation_status: "EvaluationStatus" = EvaluationStatus.COMPLETED


class ConceptualEvaluation(EvaluationBase):
    """Structured evaluation for a conceptual answer.

    overall_score is the arithmetic mean of the five criterion scores
    below, rounded to 1 decimal place. This aggregation is computed in
    app/services/conceptual_evaluator.py — it is never taken directly
    from the LLM's own opinion of "the overall score".
    """

    question_type: QuestionType = QuestionType.CONCEPTUAL
    technical_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    relevance_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    completeness_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    clarity_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    conceptual_understanding_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    correct_concepts: List[str] = Field(default_factory=list)
    missing_concepts: List[str] = Field(default_factory=list)
    incorrect_concepts: List[str] = Field(default_factory=list)
    # Reviewer-only: kept on the object and stored, but never serialized into a
    # candidate-facing response (it can echo the rubric).
    reasoning_summary: Optional[str] = Field(default=None, exclude=True)


class CodingEvaluation(EvaluationBase):
    """Structured evaluation for a coding answer.

    overall_score = (tests_passed / tests_total) * 10, computed in
    app/services/coding_evaluator.py. When tests_total is 0 (no test
    cases configured for this question), overall_score is 0 and
    execution_status is "skipped" — see that module's docstring.
    """

    question_type: QuestionType = QuestionType.CODING
    tests_total: int = Field(..., ge=0)
    tests_passed: int = Field(..., ge=0)
    tests_failed: int = Field(..., ge=0)
    execution_status: ExecutionStatus

    @model_validator(mode="after")
    def _passed_and_failed_must_sum_to_total(self) -> "CodingEvaluation":
        if self.tests_passed + self.tests_failed != self.tests_total:
            raise ValueError("tests_passed + tests_failed must equal tests_total")
        return self


class ApiError(BaseModel):
    """A machine-readable error: a stable `code` plus a safe human `message`."""

    code: str
    message: str


class AnswerSubmitRequest(BaseModel):
    """Payload for submitting a candidate's answer to the current question."""

    question_id: str = Field(..., max_length=64, description="Must match the interview's current question")
    answer_text: str = Field(
        ...,
        max_length=config.MAX_ANSWER_CHARS,
        description="The answer text, or the source code for a coding question.",
    )
    answer_source: AnswerSource = Field(
        default=AnswerSource.TEXT,
        description="'voice' if the text came from a reviewed voice transcript. Metadata only.",
    )
    language: Optional[str] = Field(
        default=None,
        max_length=32,
        description="Programming language, for coding questions only (e.g. 'python').",
    )
    submission_reason: SubmissionReason = Field(
        default=SubmissionReason.CANDIDATE_SUBMITTED,
        description="Why this answer is being submitted. Metadata only: the backend "
        "independently determines timing from its own clock; see TimingMetadata.",
    )
    integrity_events: List[IntegrityEvent] = Field(
        default_factory=list,
        max_length=config.MAX_INTEGRITY_EVENTS_PER_REQUEST,
        description="Client-reported copy/paste/tab/focus events for the current question, if any.",
    )

    @field_validator("question_id", "answer_text")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()


class RetryEvaluationRequest(BaseModel):
    question_id: str = Field(..., max_length=64)


class AnswerSubmitResponse(BaseModel):
    """Result of submitting (or re-evaluating) an answer.

    The answer is ALWAYS saved once accepted. `evaluation_status` says whether it has
    been scored:
      completed -> `evaluation` and `competency_update` are present (HTTP 200).
      pending / failed -> both are null, nothing was scored and competency is
      unchanged (HTTP 202); call POST /interview/{id}/answer/retry-evaluation while
      `retry_allowed` is true.
    """

    interview_id: str
    question_id: str
    answer_id: Optional[str] = None
    evaluation_status: EvaluationStatus = EvaluationStatus.COMPLETED
    evaluation: Optional[Union[ConceptualEvaluation, CodingEvaluation]] = None
    competency_update: Optional[CompetencyUpdate] = None
    timing: TimingMetadata
    answer_source: AnswerSource = AnswerSource.TEXT
    retry_allowed: bool = False
    evaluation_error: Optional[ApiError] = None
    next_action: NextAction = NextAction.NONE
