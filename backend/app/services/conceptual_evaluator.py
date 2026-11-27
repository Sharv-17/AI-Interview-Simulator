"""Conceptual-answer evaluation.

Calls an LLMClient (see app/services/llm_client.py) for raw per-criterion
scores, then computes overall_score itself — deterministically, as the
arithmetic mean of the five criterion scores, rounded to 1 decimal
place. This is a documented, explicit aggregation, not something left
to the LLM's own judgment of "the overall score".
"""

from typing import Optional

from app.schemas.evaluation import ConceptualEvaluation
from app.schemas.question import Question, QuestionType
from app.services.evaluation_errors import EvaluationError
from app.services.llm_client import LLMClient
from app.services.rubric_evaluator import RubricEvaluator, get_rubric_evaluator


def evaluate_conceptual_answer(
    question: Question,
    answer_text: str,
    llm_client: Optional[LLMClient] = None,
    rubric_evaluator: Optional[RubricEvaluator] = None,
) -> ConceptualEvaluation:
    """Evaluate a candidate's free-text answer.

    Default (production) path: the rubric evaluator, which uses the configured LLM
    provider and the question's reference answer, expected concepts and criteria
    (app/services/rubric_evaluator.py). If the provider is unavailable this RAISES;
    it never returns a fallback score.

    `llm_client` selects the legacy five-score interface (LLMClient). It is kept so
    existing callers and tests that inject their own client keep working; it knows
    nothing about the question's rubric and is not used by the application.
    """
    if llm_client is None:
        return (rubric_evaluator or get_rubric_evaluator()).evaluate(question, answer_text)

    try:
        raw_scores = llm_client.evaluate_conceptual_answer(
            question_text=question.question_text,
            candidate_answer=answer_text,
            reference_answer=None,
        )
    except Exception as exc:  # any provider failure becomes a clean EvaluationError
        raise EvaluationError("Conceptual evaluation failed") from exc

    criterion_scores = [
        raw_scores.technical_score,
        raw_scores.relevance_score,
        raw_scores.completeness_score,
        raw_scores.clarity_score,
        raw_scores.conceptual_understanding_score,
    ]
    overall_score = round(sum(criterion_scores) / len(criterion_scores), 1)

    return ConceptualEvaluation(
        question_id=question.question_id,
        question_type=QuestionType.CONCEPTUAL,
        technical_score=raw_scores.technical_score,
        relevance_score=raw_scores.relevance_score,
        completeness_score=raw_scores.completeness_score,
        clarity_score=raw_scores.clarity_score,
        conceptual_understanding_score=raw_scores.conceptual_understanding_score,
        overall_score=overall_score,
        feedback=raw_scores.feedback,
        strengths=raw_scores.strengths,
        weaknesses=raw_scores.weaknesses,
        evaluator=f"legacy:{type(llm_client).__name__}",
    )
