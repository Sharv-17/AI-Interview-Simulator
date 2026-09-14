"""Custom exceptions for the answer-evaluation flow.

Kept separate from evaluator implementations so the API layer can
import just the exception types without pulling in evaluator/LLM
dependencies.
"""


class InterviewNotActiveError(Exception):
    """Raised when an answer is submitted for a non-active interview."""


class QuestionNotCurrentError(Exception):
    """Raised when the submitted question_id is not the interview's current question."""


class UnsupportedQuestionTypeError(Exception):
    """Raised when a question has a type no evaluator handles."""

    def __init__(self, question_type: str) -> None:
        self.question_type = question_type
        super().__init__(f"Unsupported question type: {question_type}")


class EvaluationError(Exception):
    """Raised when an evaluator (LLM or coding) fails or returns malformed output."""