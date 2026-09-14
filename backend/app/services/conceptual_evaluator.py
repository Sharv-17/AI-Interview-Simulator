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
from app.services.llm_client import LLMClient, get_llm_client


def evaluate_conceptual_answer(
    question: Question,
    answer_text: str,
    llm_client: Optional[LLMClient] = None,
) -> ConceptualEvaluation:
    """Evaluate a candidate's answer to a conceptual question."""
    client = llm_client or get_llm_client()

    try:
        raw_scores = client.evaluate_conceptual_answer(
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
    )