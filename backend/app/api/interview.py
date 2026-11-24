"""HTTP layer for interview endpoints.

Request/response plumbing only: validate with Pydantic, call InterviewService,
translate domain errors to HTTP (see api/errors.py). No interview rules live here.
"""

from typing import Dict

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.api.errors import http_error_for
from app.schemas.competency import CompetencyState
from app.schemas.evaluation import (
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    EvaluationStatus,
    RetryEvaluationRequest,
)
from app.schemas.integrity import IntegrityEventsRequest, IntegrityEventsResponse
from app.schemas.interview import InterviewResponse, InterviewStartRequest
from app.schemas.report import InterviewReport
from app.schemas.transcription import TranscriptionResponse
from app.services.audio_validation import read_upload_limited, validate_audio
from app.services.interview_service import InterviewService, get_interview_service
from app.services.transcription_errors import VoiceInputError
from app.services.transcription_service import get_transcription_client, transcribe_audio
from fastapi import HTTPException

router = APIRouter(prefix="/interview", tags=["interview"])


def _run(operation):
    """Run a service call, mapping known domain errors to HTTP errors."""
    try:
        return operation()
    except Exception as exc:
        mapped = http_error_for(exc)
        if mapped is None:
            raise
        raise mapped from None


@router.post("/start", response_model=InterviewResponse, status_code=201)
def start_interview(
    request: InterviewStartRequest, service: InterviewService = Depends(get_interview_service)
) -> InterviewResponse:
    """Start a new interview session and return it."""
    return _run(lambda: service.start_interview(request))


@router.get("/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: str, service: InterviewService = Depends(get_interview_service)) -> InterviewResponse:
    """Retrieve an interview: state, current question, deadline and the next action to take."""
    return _run(lambda: service.get_interview(interview_id))


@router.post("/{interview_id}/answer", response_model=AnswerSubmitResponse)
def submit_answer(
    interview_id: str,
    request: AnswerSubmitRequest,
    response: Response,
    service: InterviewService = Depends(get_interview_service),
) -> AnswerSubmitResponse:
    """Submit the answer to the current question.

    200: saved and scored. 202: saved but NOT scored (evaluation pending/failed): no
    score and no competency change; use /answer/retry-evaluation.
    """
    result = _run(lambda: service.submit_answer(interview_id, request))
    if result.evaluation_status != EvaluationStatus.COMPLETED:
        response.status_code = 202
    return result


@router.post("/{interview_id}/answer/retry-evaluation", response_model=AnswerSubmitResponse)
def retry_evaluation(
    interview_id: str,
    request: RetryEvaluationRequest,
    response: Response,
    service: InterviewService = Depends(get_interview_service),
) -> AnswerSubmitResponse:
    """Re-run evaluation for an already-saved answer. Idempotent: an answer that is already
    scored returns its stored result (the evaluator is not called and competency is not updated again)."""
    result = _run(lambda: service.retry_evaluation(interview_id, request.question_id))
    if result.evaluation_status != EvaluationStatus.COMPLETED:
        response.status_code = 202
    return result


@router.post("/{interview_id}/transcribe", response_model=TranscriptionResponse)
def transcribe_answer_audio(
    interview_id: str,
    question_id: str = Form(..., min_length=1),
    audio: UploadFile = File(...),
    service: InterviewService = Depends(get_interview_service),
) -> TranscriptionResponse:
    """Turn a recorded spoken answer into text for the candidate to review.

    Transcribes only: nothing is evaluated, stored as an answer or counted toward
    competency. The same deadline rules as answering apply (recording and
    transcription time count). Audio is processed in memory/a temporary directory
    and never stored.
    """
    _run(lambda: service.ensure_can_answer(interview_id, question_id))

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
        interview_id=interview_id,
        question_id=question_id,
        transcript=result.text,
        duration_seconds=result.duration_seconds,
    )


@router.post("/{interview_id}/next", response_model=InterviewResponse)
def advance_interview(interview_id: str, service: InterviewService = Depends(get_interview_service)) -> InterviewResponse:
    """Move to the next question, or complete the interview.

    The current question must be resolved: scored, timed out, or its evaluation
    permanently failed.
    """
    return _run(lambda: service.advance(interview_id))


@router.post("/{interview_id}/integrity-events", response_model=IntegrityEventsResponse)
def report_integrity_events(
    interview_id: str,
    request: IntegrityEventsRequest,
    service: InterviewService = Depends(get_interview_service),
) -> IntegrityEventsResponse:
    """Record client-reported copy/paste/tab-switch/focus events for the CURRENT question.

    These are indicators for later review, never evidence of misconduct, and they never affect scoring.
    """
    return _run(lambda: service.record_integrity_events(interview_id, request))


@router.get("/{interview_id}/competency", response_model=Dict[str, CompetencyState])
def get_interview_competency(
    interview_id: str, service: InterviewService = Depends(get_interview_service)
) -> Dict[str, CompetencyState]:
    """Return this interview's current estimated competency state (read-only)."""
    return _run(lambda: service.competency(interview_id))


@router.get("/{interview_id}/report", response_model=InterviewReport)
def get_interview_report(
    interview_id: str, service: InterviewService = Depends(get_interview_service)
) -> InterviewReport:
    """Reviewer report: answers, scores, timing, competency and integrity indicators.

    Never contains the reference answer or rubric. NOTE: there is no authentication in
    this backend; protect this endpoint before any real deployment.
    """
    return _run(lambda: service.report(interview_id))
