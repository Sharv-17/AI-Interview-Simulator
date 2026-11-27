"""Custom exceptions for the answer-evaluation and interview flows.

Two families:

* DomainRejection -- a request the interview rules refuse (wrong question,
  duplicate, past the deadline...). The domain may have recorded an integrity
  indicator or a "timed out" state before raising, so the unit of work commits
  those deliberate changes even though the request itself is rejected.
* EvaluationError -- the evaluator could not produce a score. Carries a stable
  `code`, whether it is `retryable`, and the answer state it leaves behind
  (`pending` = try again later; `failed` = the evaluator gave unusable output).
  It NEVER carries a score: no evaluator failure may produce a fabricated one.
"""

from typing import Optional


class DomainRejection(Exception):
    """A request refused by the interview rules (see module docstring)."""


class InterviewNotActiveError(DomainRejection):
    """Raised when an answer is submitted for a non-active interview."""


class QuestionNotCurrentError(DomainRejection):
    """Raised when the submitted question_id is not the interview's current question."""


class AnswerAlreadySubmittedError(DomainRejection):
    """Raised when the current question has already been answered."""


class QuestionNotAnsweredError(DomainRejection):
    """Raised when moving on before the current question has been answered."""


class QuestionDeadlinePassedError(DomainRejection):
    """Raised when a question's answer deadline (time limit + grace) has passed."""


class EvaluationPendingError(DomainRejection):
    """Raised when moving on while the current answer's evaluation is unresolved."""


class AnswerNotFoundError(DomainRejection):
    """Raised when evaluation is requested for a question with no recorded answer."""


class EvaluationRetriesExhaustedError(DomainRejection):
    """Raised when an answer has used up its evaluation retries."""


class UnsupportedQuestionTypeError(Exception):
    """Raised when a question has a type no evaluator handles."""

    def __init__(self, question_type: str) -> None:
        self.question_type = question_type
        super().__init__(f"Unsupported question type: {question_type}")


class EvaluationError(Exception):
    """An evaluator could not produce a result (never carries a score)."""

    code = "evaluation_failed"
    status = "failed"  # answer state left behind: "pending" | "failed"
    retryable = True
    default_message = "Answer evaluation failed."

    def __init__(self, message: Optional[str] = None, code: Optional[str] = None) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        if code:
            self.code = code


class EvaluationUnavailableError(EvaluationError):
    """The evaluator is not usable right now (not configured, down, rate limited, timed out)."""

    code = "evaluator_unavailable"
    status = "pending"
    default_message = "The answer evaluator is not available right now. Your answer is saved; try again shortly."


class EvaluationFailedError(EvaluationError):
    """The evaluator responded but its output was unusable, or it rejected the request."""

    code = "evaluation_failed"
    status = "failed"
    default_message = "The answer could not be evaluated. Your answer is saved; you can retry."


class InterviewBusyError(Exception):
    """Another request is already changing this interview (try again)."""


class InterviewNotFoundError(Exception):
    """No such interview."""


class CandidateNotFoundError(Exception):
    """No such candidate."""
