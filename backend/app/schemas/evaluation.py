"""Pydantic models for answer evaluation results.

ConceptualEvaluation and CodingEvaluation share a small common shape
(question_id, question_type, overall_score, feedback, strengths,
weaknesses) via EvaluationBase, with type-specific fields added in each
subclass. This lets the Interview Engine and API layer work with either
result generically wherever they only need the common fields.
"""

from enum import Enum
from typing import List, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.question import QuestionType

SCORE_MIN = 0
SCORE_MAX = 10


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
    feedback: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)


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


class AnswerSubmitRequest(BaseModel):
    """Payload for submitting a candidate's answer to the current question."""

    question_id: str = Field(..., description="Must match the interview's current question")
    answer_text: str

    @field_validator("question_id", "answer_text")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()


class AnswerSubmitResponse(BaseModel):
    """Response returned after a candidate's answer is evaluated."""

    interview_id: str
    question_id: str
    evaluation: Union[ConceptualEvaluation, CodingEvaluation]