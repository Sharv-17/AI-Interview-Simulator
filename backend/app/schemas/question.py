"""Pydantic models for the question bank.

Reuses DifficultyLevel from schemas/interview.py so an interview's
difficulty and a question's difficulty are always validated against
the same set of values.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.interview import DifficultyLevel


class QuestionType(str, Enum):
    """Allowed question types.

    conceptual / scenario / system_design / debugging are all free-text answers
    judged against a rubric. coding needs deterministic test execution, which
    does not exist yet (see app/services/coding_evaluator.py).
    """

    CONCEPTUAL = "conceptual"
    CODING = "coding"
    SCENARIO = "scenario"
    SYSTEM_DESIGN = "system_design"
    DEBUGGING = "debugging"


class ReviewStatus(str, Enum):
    """Whether a question is cleared to be asked to a candidate."""

    REVIEWED = "reviewed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    REQUIRES_CODING_EVALUATION = "requires_coding_evaluation"


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
    expected_concepts: List[str] = Field(
        default_factory=list,
        description="Key ideas a good answer covers. Answer key: never shown to candidates.",
    )
    evaluation_criteria: List[str] = Field(
        default_factory=list,
        description="Rubric lines for evaluating an answer. Answer key: never shown to candidates.",
    )
    estimated_time_seconds: Optional[int] = Field(
        default=None,
        gt=0,
        description="Suggested time to answer. Informational only; the server timer is a fixed default.",
    )
    review_status: Optional[ReviewStatus] = None
    source: Optional[str] = None
    legacy_category: Optional[str] = None
    previous_id: Optional[str] = None

    @property
    def is_servable(self) -> bool:
        """True if this question may be asked to a candidate.

        Only questions marked `reviewed` (or with no review status recorded)
        are servable. `needs_manual_review` and `requires_coding_evaluation`
        questions stay in the bank, and can be looked up by ID, but are never
        selected for an interview.
        """
        return self.review_status in (None, ReviewStatus.REVIEWED)

    @field_validator("question_id", "question_text", "topic", "competency")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()


class QuestionPublic(BaseModel):
    """What a candidate may see about a question.

    Deliberately has NO answer key (reference_answer, expected_concepts,
    evaluation_criteria): those must never be sent to the person being interviewed.
    """

    model_config = ConfigDict(from_attributes=True)

    question_id: str
    question_text: str
    topic: str
    subtopic: Optional[str] = None
    difficulty: DifficultyLevel
    question_type: QuestionType
    competency: str
    tags: List[str] = Field(default_factory=list)