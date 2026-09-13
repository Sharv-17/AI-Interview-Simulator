"""HTTP layer for interview endpoints.

This module only handles request/response plumbing: it validates input
via Pydantic, delegates to the Interview Engine, and returns the result.
No session/business logic lives here.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.interview import InterviewResponse, InterviewStartRequest
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