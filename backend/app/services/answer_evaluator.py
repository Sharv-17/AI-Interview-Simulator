"""Dispatches an answer to the correct evaluator based on question type.

FastAPI Router -> Interview Engine -> here -> conceptual/coding evaluator

This module owns the "which evaluator handles this question type"
decision so neither the API layer nor the Interview Engine needs to
know about conceptual/coding specifics.
"""

from typing import Optional, Union

from app.schemas.evaluation import CodingEvaluation, ConceptualEvaluation
from app.schemas.question import Question, QuestionType
from app.services.coding_evaluator import evaluate_coding_answer, get_test_cases_for_question
from app.services.conceptual_evaluator import evaluate_conceptual_answer
from app.services.evaluation_errors import UnsupportedQuestionTypeError
from app.services.llm_client import LLMClient


# Free-text answers judged against a rubric. scenario / system_design /
# debugging are answered in prose, so they use the same rubric evaluator as
# conceptual questions (the resulting evaluation is still reported as
# "conceptual", i.e. rubric-based). Coding is different: it needs deterministic
# test execution.
_RUBRIC_EVALUATED_TYPES = {
    QuestionType.CONCEPTUAL,
    QuestionType.SCENARIO,
    QuestionType.SYSTEM_DESIGN,
    QuestionType.DEBUGGING,
}


def evaluate_answer(
    question: Question,
    answer_text: str,
    llm_client: Optional[LLMClient] = None,
    language: Optional[str] = None,
) -> Union[ConceptualEvaluation, CodingEvaluation]:
    """Evaluate a candidate's answer using the evaluator for its question type."""
    if question.question_type in _RUBRIC_EVALUATED_TYPES:
        return evaluate_conceptual_answer(question=question, answer_text=answer_text, llm_client=llm_client)

    if question.question_type == QuestionType.CODING:
        test_cases = get_test_cases_for_question(question.question_id)
        return evaluate_coding_answer(question=question, answer_text=answer_text, test_cases=test_cases)

    raise UnsupportedQuestionTypeError(question.question_type)