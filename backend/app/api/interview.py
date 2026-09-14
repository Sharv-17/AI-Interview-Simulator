"""HTTP layer for interview endpoints.

This module only handles request/response plumbing: it validates input
via Pydantic, delegates to the Interview Engine, and returns the result.
No session/business logic lives here.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.evaluation import AnswerSubmitRequest, AnswerSubmitResponse
from app.schemas.interview import InterviewResponse, InterviewStartRequest
from app.services.evaluation_errors import (
    EvaluationError,
    InterviewNotActiveError,
    QuestionNotCurrentError,
    UnsupportedQuestionTypeError,
)
from app.services.interview_engine import interview_engine

router = APIRouter(prefix="/interview", tags=["interview"])


@router.post("/start", response_model=InterviewResponse, status_code=201)
def start_interview(request: InterviewStartRequest) -> InterviewResponse:
    """Start a new interview session and return it."""
    session = interview_engine.create_interview(
        topic=request.topic,
        difficulty=request.difficulty,
        question_count=request.question_count,
    )
    return session.to_response()


@router.get("/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: str) -> InterviewResponse:
    """Retrieve an existing interview session by ID."""
    session = interview_engine.get_interview(interview_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    return session.to_response()


@router.post("/{interview_id}/answer", response_model=AnswerSubmitResponse)
def submit_answer(interview_id: str, request: AnswerSubmitRequest) -> AnswerSubmitResponse:
    """Submit a candidate's answer to the interview's current question."""
    session = interview_engine.get_interview(interview_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    try:
        evaluation = session.submit_answer(request.question_id, request.answer_text)
    except InterviewNotActiveError:
        raise HTTPException(status_code=409, detail="Interview is not active")
    except QuestionNotCurrentError:
        raise HTTPException(
            status_code=400,
            detail="This question is not the interview's current question",
        )
    except UnsupportedQuestionTypeError:
        raise HTTPException(status_code=400, detail="Unsupported question type")
    except EvaluationError:
        raise HTTPException(status_code=502, detail="Answer evaluation failed")

    return AnswerSubmitResponse(
        interview_id=session.interview_id,
        question_id=request.question_id,
        evaluation=evaluation,
    )