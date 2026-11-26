"""Mapping of domain/service exceptions to HTTP errors.

Error bodies are `{"detail": ...}`. Errors that existed before Phase 2-5 keep their
original plain-string detail so existing clients are unaffected; newer errors use
`{"detail": {"code": "...", "message": "..."}}`. Raw exception text, stack traces and
provider output are never returned.
"""

from typing import Optional

from fastapi import HTTPException

from app.services.auth_errors import AuthError
from app.services.evaluation_errors import (
    AnswerAlreadySubmittedError,
    AnswerNotFoundError,
    CandidateNotFoundError,
    EvaluationPendingError,
    EvaluationRetriesExhaustedError,
    InterviewBusyError,
    InterviewNotActiveError,
    InterviewNotFoundError,
    QuestionDeadlinePassedError,
    QuestionNotAnsweredError,
    QuestionNotCurrentError,
    UnsupportedQuestionTypeError,
)


def coded(status: int, code: str, message: str, headers: Optional[dict] = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


def http_error_for(exc: Exception) -> Optional[HTTPException]:
    """Return the HTTPException for a known domain error, or None for unknown ones."""
    if isinstance(exc, AuthError):
        # Authentication errors carry their own status, code and safe message.
        return coded(exc.status_code, exc.code, exc.message, exc.headers)
    if isinstance(exc, InterviewNotFoundError):
        return HTTPException(status_code=404, detail="Interview not found")
    if isinstance(exc, CandidateNotFoundError):
        return HTTPException(status_code=404, detail="Candidate not found")
    if isinstance(exc, InterviewNotActiveError):
        return HTTPException(status_code=409, detail="Interview is not active")
    if isinstance(exc, AnswerAlreadySubmittedError):
        return HTTPException(status_code=409, detail="This question has already been answered")
    if isinstance(exc, QuestionNotCurrentError):
        return HTTPException(status_code=400, detail="This question is not the interview's current question")
    if isinstance(exc, QuestionNotAnsweredError):
        return HTTPException(status_code=409, detail="The current question must be answered before moving on")
    if isinstance(exc, UnsupportedQuestionTypeError):
        return HTTPException(status_code=400, detail="Unsupported question type")
    if isinstance(exc, QuestionDeadlinePassedError):
        return coded(409, "question_deadline_passed", "The time for this question has run out. Move on to the next question.")
    if isinstance(exc, EvaluationPendingError):
        return coded(409, "evaluation_pending", "Your answer has not been scored yet. Retry the evaluation first.")
    if isinstance(exc, AnswerNotFoundError):
        return coded(409, "no_answer_recorded", "No answer has been recorded for this question.")
    if isinstance(exc, EvaluationRetriesExhaustedError):
        return coded(409, "evaluation_retries_exhausted", "This answer has used all of its evaluation retries.")
    if isinstance(exc, InterviewBusyError):
        return coded(409, "interview_busy", "Another request for this interview is in progress. Try again.", {"Retry-After": "1"})
    return None
