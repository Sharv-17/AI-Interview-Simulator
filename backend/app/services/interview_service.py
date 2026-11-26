"""Interview service: orchestrates one API operation on top of an InterviewStore.

Every mutating operation runs inside `store.edit(interview_id)`, which gives it
exclusive access to that interview (a database row lock in PostgreSQL). That is
what makes the guarantees below hold even under concurrent requests:

* An answer is recorded once; a second submission is refused (409).
* An answer is evaluated successfully at most once and competency is updated at
  most once per answer: retrying an already-evaluated answer returns the stored
  result and never calls the evaluator again.
* If evaluation fails, the answer stays saved with status pending/failed, with
  NO score and NO competency change, and can be retried (bounded).
"""

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app import config
from app.repositories.question_repository import question_repository
from app.schemas.candidate import CandidateCreate, CandidateView, CompetencyHistoryEntry, InterviewSummary
from app.schemas.competency import CompetencyState
from app.schemas.evaluation import (
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    ApiError,
    EvaluationStatus,
)
from app.schemas.integrity import IntegrityEventsRequest, IntegrityEventsResponse
from app.schemas.interview import InterviewResponse, InterviewStartRequest
from app.schemas.report import InterviewReport
from app.services.answer_evaluator import evaluate_answer
from app.services.evaluation_errors import (
    EvaluationError,
    EvaluationFailedError,
    UnsupportedQuestionTypeError,
)
from app.services.interview_engine import InterviewSession, interview_engine, utcnow
from app.services.interview_store import InterviewStore, MemoryInterviewStore

logger = logging.getLogger(__name__)

_PENDING_MESSAGE = (
    "Your answer is saved but could not be scored yet. "
    "Use POST /interview/{id}/answer/retry-evaluation to try again."
)
_FAILED_MESSAGE = (
    "Your answer is saved but the evaluator could not score it. "
    "Use POST /interview/{id}/answer/retry-evaluation to try again."
)
_EXHAUSTED_MESSAGE = "Your answer is saved but could not be scored after several attempts. You can continue."


class StorageConfigurationError(RuntimeError):
    """Storage is not configured safely (see STORAGE_BACKEND / DATABASE_URL)."""


class InterviewService:
    def __init__(self, store: InterviewStore, clock: Callable[[], datetime] = utcnow) -> None:
        self._store = store
        self._clock = clock

    @property
    def store(self) -> InterviewStore:
        return self._store

    @property
    def backend_name(self) -> str:
        return self._store.backend_name

    def check_ready(self) -> None:
        self._store.check_ready()

    # ----------------------------------------------------------------- interviews

    def start_interview(self, request: InterviewStartRequest) -> InterviewResponse:
        session = self._store.create_interview(
            request.topic, request.difficulty, request.question_count, request.candidate_id
        )
        return session.to_response(self._clock())

    def get_interview(self, interview_id: str) -> InterviewResponse:
        return self._store.read(interview_id).to_response(self._clock())

    def advance(self, interview_id: str) -> InterviewResponse:
        # Only advancing needs the candidate's question history (cooldown rotation).
        with self._store.edit(interview_id, with_history=True) as session:
            session.advance_to_next_question(self._clock())
            return session.to_response(self._clock())

    def ensure_can_answer(self, interview_id: str, question_id: str) -> None:
        """Used before accepting audio: same rules (and deadline) as answering."""
        with self._store.edit(interview_id) as session:
            session.ensure_accepting_answer(question_id, self._clock())

    def competency(self, interview_id: str) -> Dict[str, CompetencyState]:
        return self._store.read(interview_id).competency_state.get_all()

    def report(self, interview_id: str) -> InterviewReport:
        return self._store.report(interview_id)

    # -------------------------------------------------------------------- answers

    def submit_answer(self, interview_id: str, request: AnswerSubmitRequest) -> AnswerSubmitResponse:
        with self._store.edit(interview_id) as session:
            record = session.record_answer(
                request.question_id,
                request.answer_text,
                submission_reason=request.submission_reason,
                integrity_events=request.integrity_events,
                answer_source=request.answer_source,
                language=request.language,
                now=self._clock(),
            )
            self._evaluate(session, record)
            return self._response(session, record)

    def retry_evaluation(self, interview_id: str, question_id: str) -> AnswerSubmitResponse:
        with self._store.edit(interview_id) as session:
            record = session.prepare_evaluation_retry(question_id)
            if record["evaluation_status"] != EvaluationStatus.COMPLETED:
                self._evaluate(session, record)
            # Already evaluated: return the stored result. No evaluator call, no second competency update.
            return self._response(session, record)

    def _evaluate(self, session: InterviewSession, record: Dict[str, Any]) -> None:
        question_id = record["question_id"]
        question = question_repository.get_by_id(question_id)
        if question is None:
            session.mark_evaluation_failed(question_id, EvaluationFailedError(code="question_not_found"), self._clock())
            return
        try:
            evaluation = evaluate_answer(question, record["answer_text"], language=record.get("language"))
        except EvaluationError as error:
            session.mark_evaluation_failed(question_id, error, self._clock())
        except UnsupportedQuestionTypeError:
            session.mark_evaluation_failed(
                question_id, EvaluationFailedError(code="unsupported_question_type"), self._clock()
            )
        except Exception:  # an evaluator bug must not lose the saved answer
            logger.exception("Unexpected evaluator error for question %s", question_id)
            session.mark_evaluation_failed(question_id, EvaluationFailedError(code="evaluator_error"), self._clock())
        else:
            session.apply_evaluation(question, evaluation, self._clock())

    def _response(self, session: InterviewSession, record: Dict[str, Any]) -> AnswerSubmitResponse:
        status = record["evaluation_status"]
        completed = status == EvaluationStatus.COMPLETED
        retries_left = session._retries_left(record)
        error: Optional[ApiError] = None
        if not completed:
            message = _EXHAUSTED_MESSAGE if not retries_left else (_PENDING_MESSAGE if status == EvaluationStatus.PENDING else _FAILED_MESSAGE)
            error = ApiError(code=record["evaluation_error"] or "evaluation_pending", message=message)
        return AnswerSubmitResponse(
            interview_id=session.interview_id,
            question_id=record["question_id"],
            answer_id=record["answer_id"],
            evaluation_status=status,
            evaluation=record["evaluation"] if completed else None,
            competency_update=record["competency_update"] if completed else None,
            timing=record["timing"],
            answer_source=record["answer_source"],
            retry_allowed=(not completed) and retries_left,
            evaluation_error=error,
            next_action=session.next_action(self._clock()),
        )

    # ------------------------------------------------------------------ integrity

    def record_integrity_events(self, interview_id: str, request: IntegrityEventsRequest) -> IntegrityEventsResponse:
        question_id, kept = self._store.record_integrity_events(
            interview_id, request.question_id, request.events, self._clock()
        )
        return IntegrityEventsResponse(interview_id=interview_id, question_id=question_id, recorded=kept)

    # ------------------------------------------------------------------ candidates

    def create_candidate(self, payload: CandidateCreate) -> CandidateView:
        return self._store.create_candidate(payload)

    def get_candidate(self, candidate_id: str) -> CandidateView:
        return self._store.get_candidate(candidate_id)

    def list_interviews(self, candidate_id: str) -> List[InterviewSummary]:
        return self._store.list_interviews(candidate_id)

    def competency_history(self, candidate_id: str) -> List[CompetencyHistoryEntry]:
        return self._store.competency_history(candidate_id)


# --- wiring ---------------------------------------------------------------------

_service: Optional[InterviewService] = None


def build_service_from_config() -> InterviewService:
    """Choose the store from the environment. Never silently falls back to memory."""
    backend = config.STORAGE_BACKEND
    if not backend:
        if config.DATABASE_URL:
            backend = "postgres"
        else:
            raise StorageConfigurationError(
                "No storage configured. Set DATABASE_URL (PostgreSQL), or set STORAGE_BACKEND=memory "
                "for development/testing only (data is lost on restart)."
            )
    if backend == "memory":
        logger.warning("STORAGE_BACKEND=memory: interviews are NOT persisted. Development/testing only.")
        return InterviewService(MemoryInterviewStore(interview_engine))
    if backend == "postgres":
        if not config.DATABASE_URL:
            raise StorageConfigurationError("STORAGE_BACKEND=postgres requires DATABASE_URL.")
        try:
            from app.db.postgres_store import PostgresInterviewStore
        except ModuleNotFoundError as exc:
            if exc.name != "app.db.postgres_store":
                raise
            raise StorageConfigurationError(
                "The PostgreSQL store is not implemented in this build yet (the schema and Alembic migration "
                "exist; app/db/postgres_store.py does not). Use STORAGE_BACKEND=memory for development."
            ) from None

        return InterviewService(PostgresInterviewStore.from_url(config.DATABASE_URL))
    raise StorageConfigurationError(f"Unknown STORAGE_BACKEND {backend!r}. Use 'postgres' or 'memory'.")


def get_interview_service() -> InterviewService:
    global _service
    if _service is None:
        _service = build_service_from_config()
    return _service


def set_interview_service(service: Optional[InterviewService]) -> None:
    """Replace the shared service (tests and application start-up)."""
    global _service
    _service = service
