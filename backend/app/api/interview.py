"""HTTP layer for interview endpoints.

This module only handles request/response plumbing: it validates input
via Pydantic, delegates to the Interview Engine, and returns the result.
No session/business logic lives here.
"""

from typing import Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.competency import CompetencyState
from app.schemas.evaluation import AnswerSubmitRequest, AnswerSubmitResponse
from app.schemas.interview import InterviewResponse, InterviewStartRequest
from app.schemas.transcription import TranscriptionResponse
from app.services.audio_validation import read_upload_limited, validate_audio
from app.services.evaluation_errors import (
    AnswerAlreadySubmittedError,
    EvaluationError,
    InterviewNotActiveError,
    QuestionNotAnsweredError,
    QuestionNotCurrentError,
    UnsupportedQuestionTypeError,
)
from app.services.interview_engine import interview_engine
from app.services.transcription_errors import VoiceInputError
from app.services.transcription_service import get_transcription_client, transcribe_audio

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
        evaluation, competency_update, timing = session.submit_answer(
            request.question_id,
            request.answer_text,
            submission_reason=request.submission_reason,
            integrity_events=request.integrity_events,
            answer_source=request.answer_source,
        )
    except InterviewNotActiveError:
        raise HTTPException(status_code=409, detail="Interview is not active")
    except AnswerAlreadySubmittedError:
        raise HTTPException(status_code=409, detail="This question has already been answered")
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
        competency_update=competency_update,
        timing=timing,
        answer_source=request.answer_source,
    )


@router.post("/{interview_id}/transcribe", response_model=TranscriptionResponse)
def transcribe_answer_audio(
    interview_id: str,
    question_id: str = Form(..., min_length=1),
    audio: UploadFile = File(...),
) -> TranscriptionResponse:
    """Turn a recorded spoken answer into text for the candidate to review.

    This endpoint ONLY transcribes. It does not evaluate, store an answer or
    update competency; the reviewed text is submitted separately to
    POST /interview/{id}/answer. Audio is processed in memory/a temporary
    directory and never stored.
    """
    session = interview_engine.get_interview(interview_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    try:
        session.ensure_accepting_answer(question_id)
    except InterviewNotActiveError:
        raise HTTPException(status_code=409, detail="Interview is not active")
    except AnswerAlreadySubmittedError:
        raise HTTPException(status_code=409, detail="This question has already been answered")
    except QuestionNotCurrentError:
        raise HTTPException(
            status_code=400,
            detail="This question is not the interview's current question",
        )

    try:
        audio_bytes = read_upload_limited(audio.file)
        audio_format = validate_audio(audio_bytes)
        result = transcribe_audio(audio_bytes, audio_format, client=get_transcription_client())
    except VoiceInputError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    finally:
        audio.file.close()

    return TranscriptionResponse(
        interview_id=session.interview_id,
        question_id=question_id,
        transcript=result.text,
        duration_seconds=result.duration_seconds,
    )


@router.post("/{interview_id}/next", response_model=InterviewResponse)
def advance_interview(interview_id: str) -> InterviewResponse:
    """Move to the next question, or complete the interview.

    The current question must already be answered.
    """
    session = interview_engine.get_interview(interview_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview not found")

    try:
        session.advance_to_next_question()
    except InterviewNotActiveError:
        raise HTTPException(status_code=409, detail="Interview is not active")
    except QuestionNotAnsweredError:
        raise HTTPException(
            status_code=409,
            detail="The current question must be answered before moving on",
        )
    return session.to_response()


@router.get("/{interview_id}/competency", response_model=Dict[str, CompetencyState])
def get_interview_competency(interview_id: str) -> Dict[str, CompetencyState]:
    """Return this interview's current estimated competency state.

    Read-only: there is no endpoint to set competency state directly.
    Only this interview's own competency state is exposed — competency
    state is never shared across interviews.
    """
    session = interview_engine.get_interview(interview_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    return session.competency_state.get_all()