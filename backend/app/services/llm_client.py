"""LLM abstraction for conceptual-answer evaluation.

Stage 3.4 does not integrate a real LLM provider. This module defines
the interface any future provider must implement, plus a deterministic
mock used for tests and local development. Swapping in a real provider
later means writing one class here — nothing in conceptual_evaluator.py
or above needs to change.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.evaluation import SCORE_MAX, SCORE_MIN

# Documents the structured prompt a real provider would eventually be
# sent. Not sent anywhere yet — there is no real provider in Stage 3.4.
CONCEPTUAL_EVALUATION_PROMPT_TEMPLATE = """\
You are evaluating a candidate's answer to a technical interview question.

Question: {question_text}
Reference answer (if available): {reference_answer}
Candidate answer: {candidate_answer}

Score the candidate answer on a 0-10 scale for each of:
- technical_score: technical correctness
- relevance_score: relevance to the question asked
- completeness_score: completeness of the answer
- clarity_score: clarity of explanation
- conceptual_understanding_score: depth of conceptual understanding

Rules:
- Evaluate the candidate's answer; do not rewrite or complete it for them.
- Do not invent facts the candidate did not state.
- Do not score based on writing style alone; technical correctness matters most.
- Do not use the candidate's identity or any personal information.
- Return ONLY structured output matching the required schema — no prose outside it.
"""


class LLMConceptualScores(BaseModel):
    """Raw structured scores an LLM client returns for one conceptual answer.

    Kept separate from ConceptualEvaluation: this holds only what the
    LLM is asked to produce. question_id and overall_score are added
    afterwards by conceptual_evaluator.py, which computes overall_score
    itself rather than trusting the LLM's own aggregation.
    """

    technical_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    relevance_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    completeness_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    clarity_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    conceptual_understanding_score: int = Field(..., ge=SCORE_MIN, le=SCORE_MAX)
    feedback: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)


class LLMClient(ABC):
    """Interface any LLM provider (real or mock) must implement."""

    @abstractmethod
    def evaluate_conceptual_answer(
        self,
        question_text: str,
        candidate_answer: str,
        reference_answer: Optional[str] = None,
    ) -> LLMConceptualScores:
        """Return structured scores for one candidate answer."""
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Deterministic stand-in LLM client for tests and local development.

    THIS IS NOT A REAL EVALUATOR. It does not genuinely understand the
    candidate's answer. It exists purely so the evaluation architecture
    is testable and runnable without an external API key or network
    access. Scoring is a simple deterministic function of answer length
    so tests get stable, reproducible numbers — never randomness, never
    a real network call.
    """

    _MIN_LENGTH_FOR_FULL_CREDIT = 40

    def evaluate_conceptual_answer(
        self,
        question_text: str,
        candidate_answer: str,
        reference_answer: Optional[str] = None,
    ) -> LLMConceptualScores:
        has_substance = len(candidate_answer.strip()) >= self._MIN_LENGTH_FOR_FULL_CREDIT
        score = 8 if has_substance else 3

        return LLMConceptualScores(
            technical_score=score,
            relevance_score=score,
            completeness_score=score,
            clarity_score=score,
            conceptual_understanding_score=score,
            feedback=(
                "Mock evaluation: answer has reasonable substance."
                if has_substance
                else "Mock evaluation: answer is too short to demonstrate understanding."
            ),
            strengths=["Answer provided"] if has_substance else [],
            weaknesses=[] if has_substance else ["Answer is very short"],
        )


def get_llm_client() -> LLMClient:
    """Return the LLM client to use.

    Stage 3.4 always returns the deterministic mock — there is no real
    provider wired in yet. A future stage can make this read
    configuration (e.g. an environment variable) and return a real
    provider instead, without changing any caller.
    """
    return MockLLMClient()