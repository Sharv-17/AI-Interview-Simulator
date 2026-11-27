"""Interview domain (InterviewSession) and the in-memory engine.

InterviewSession holds ALL the interview rules and is storage-agnostic:

* An answer is RECORDED first (record_answer) and EVALUATED second
  (apply_evaluation / mark_evaluation_failed). A recorded answer can never be
  replaced, so a candidate cannot retry with better text, and an evaluation
  failure can never lose or duplicate an answer.
* Competency (theta) is updated ONLY inside apply_evaluation, exactly once per
  answer, and only for a completed evaluation. A pending or failed evaluation
  never touches competency.
* Time: each question gets a limit (its estimated_time_seconds, else the default)
  plus a grace period. The server clock is the only clock that counts. After
  limit + grace the answer is refused and the question is marked timed out.
* Every change is also appended to `self.changes` (see domain_changes.py) so a
  database store can persist it transactionally; the memory store ignores them.

Rejections (DomainRejection) may leave deliberate changes behind, e.g. an
integrity indicator or a "timed out" mark; stores commit those.
"""

import logging
import random
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Set

from app import config
from app.config import DEFAULT_QUESTION_TIME_LIMIT_SECONDS
from app.repositories.question_repository import question_repository  # noqa: F401  (tests patch via this module)
from app.schemas.competency import CompetencyUpdate
from app.schemas.evaluation import AnswerSource, CodingEvaluation, ConceptualEvaluation, EvaluationStatus
from app.schemas.integrity import IntegrityEvent, ServerIntegrityEventType, SubmissionReason, TimingMetadata
from app.schemas.interview import (
    DifficultyLevel,
    InterviewResponse,
    InterviewStatus,
    NextAction,
    QuestionState,
)
from app.schemas.question import Question
from app.services import domain_changes as ch
from app.services.competency_state import CompetencyStateStore
from app.services.evaluation_errors import (
    AnswerAlreadySubmittedError,
    AnswerNotFoundError,
    EvaluationError,
    EvaluationPendingError,
    EvaluationRetriesExhaustedError,
    InterviewNotActiveError,
    QuestionDeadlinePassedError,
    QuestionNotAnsweredError,
    QuestionNotCurrentError,
)
from app.services.question_selector import select_next_question
from app.services.timer_service import check_timeout, deadline as compute_deadline, is_past_deadline

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewSession:
    """One interview. See the module docstring for the rules it enforces."""

    def __init__(
        self,
        topic: str,
        difficulty: DifficultyLevel,
        question_count: int,
        candidate_id: Optional[str] = None,
        now: Optional[datetime] = None,
        encountered: Optional[Mapping[str, datetime]] = None,
        rng: Optional[random.Random] = None,
        select_initial: bool = True,
    ) -> None:
        now = now or utcnow()
        self.interview_id: str = str(uuid.uuid4())
        self.candidate_id: Optional[str] = candidate_id
        self.topic: str = topic
        self.difficulty: DifficultyLevel = difficulty
        self.question_count: int = question_count
        self.current_question: int = 1
        self.status: InterviewStatus = InterviewStatus.ACTIVE
        self.created_at: datetime = now
        self.completed_at: Optional[datetime] = None
        self.asked_question_ids: List[str] = []
        # question_id -> when it was assigned in THIS interview (in-memory history source).
        self.question_assigned_at: Dict[str, datetime] = {}
        # question_id -> most recent assignment in EARLIER interviews (cooldown rotation).
        self.encountered: Dict[str, datetime] = dict(encountered or {})
        self._rng = rng
        self.current_question_id: Optional[str] = None
        self.question_started_at: Optional[datetime] = None
        self.question_time_limit_seconds: Optional[int] = None
        self.question_grace_seconds: int = config.ANSWER_GRACE_SECONDS
        self.answers: List[Dict[str, Any]] = []
        self.answered_question_ids: Set[str] = set()
        self.timed_out_question_ids: Set[str] = set()
        self.integrity_log: List[Dict[str, Any]] = []
        self.integrity_event_count: int = 0
        self.competency_state = CompetencyStateStore()
        self.changes: List[ch.Change] = []

        if select_initial:
            self._select_initial_question(now)

    # ------------------------------------------------------------------ questions

    def _select_initial_question(self, now: datetime) -> None:
        """Pick the first question (cold start). No suitable question is not an error:
        the interview starts with current_question_id None. The selector never
        substitutes an unrelated topic."""
        question = select_next_question(
            topic=self.topic,
            difficulty=self.difficulty,
            asked_question_ids=self.asked_question_ids,
            encountered=self.encountered,
            rng=self._rng,
        )
        if question is not None:
            self._set_current_question(question, now)

    def _set_current_question(self, question: Question, now: datetime) -> None:
        """Make a question current and start its server-side timer (recorded once)."""
        limit = question.estimated_time_seconds or DEFAULT_QUESTION_TIME_LIMIT_SECONDS
        self.current_question_id = question.question_id
        self.asked_question_ids.append(question.question_id)
        self.question_assigned_at[question.question_id] = now
        self.question_started_at = now
        self.question_time_limit_seconds = limit
        self.question_grace_seconds = config.ANSWER_GRACE_SECONDS
        self.changes.append(
            ch.QuestionAssigned(
                question_id=question.question_id,
                sequence=self.current_question,
                assigned_at=now,
                time_limit_seconds=limit,
                grace_seconds=self.question_grace_seconds,
            )
        )

    # --------------------------------------------------------------------- timing

    @property
    def deadline_at(self) -> Optional[datetime]:
        if self.question_started_at is None or self.question_time_limit_seconds is None:
            return None
        return compute_deadline(self.question_started_at, self.question_time_limit_seconds, self.question_grace_seconds)

    def _past_deadline(self, now: datetime) -> bool:
        if self.question_started_at is None or self.question_time_limit_seconds is None:
            return False
        return is_past_deadline(
            self.question_started_at, self.question_time_limit_seconds, self.question_grace_seconds, at=now
        )

    def _mark_timed_out(self, now: datetime) -> None:
        qid = self.current_question_id
        if qid is not None and qid not in self.timed_out_question_ids:
            self.timed_out_question_ids.add(qid)
            self.changes.append(ch.QuestionTimedOut(question_id=qid, at=now))

    # ------------------------------------------------------------------ integrity

    def _log(
        self,
        event_type: str,
        source: str,
        now: datetime,
        question_id: Optional[str] = None,
        answer_id: Optional[str] = None,
        client_occurred_at: Optional[datetime] = None,
        client_source: Optional[str] = None,
        duration_ms: Optional[int] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record an integrity INDICATOR. Never affects scoring. Capped per interview."""
        if self.integrity_event_count >= config.MAX_INTEGRITY_EVENTS_PER_INTERVIEW:
            return False
        self.integrity_event_count += 1
        entry = dict(
            event_type=event_type,
            source=source,
            question_id=question_id,
            answer_id=answer_id,
            client_occurred_at=client_occurred_at,
            received_at=now,
            duration_ms=duration_ms,
            detail=detail or {},
        )
        self.integrity_log.append(entry)
        self.changes.append(
            ch.IntegrityLogged(
                event_type=event_type,
                source=source,
                received_at=now,
                question_id=question_id,
                answer_id=answer_id,
                client_occurred_at=client_occurred_at,
                client_source=client_source,
                duration_ms=duration_ms,
                detail=detail or {},
            )
        )
        return True

    def record_client_integrity_events(
        self, events: List[IntegrityEvent], question_id: Optional[str] = None, now: Optional[datetime] = None
    ) -> int:
        """Store client-reported events for the CURRENT question. Returns how many were kept."""
        now = now or utcnow()
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()
        if question_id is None:
            question_id = self.current_question_id
        if question_id is None or question_id != self.current_question_id:
            raise QuestionNotCurrentError()
        kept = 0
        for event in events:
            if self._log(
                event.event_type.value,
                "client",
                now,
                question_id=question_id,
                client_occurred_at=event.occurred_at,
                client_source=event.source,
                duration_ms=event.duration_ms,
            ):
                kept += 1
        return kept

    # -------------------------------------------------------------------- answers

    def get_answer(self, question_id: str) -> Optional[Dict[str, Any]]:
        for record in self.answers:
            if record["question_id"] == question_id:
                return record
        return None

    def _retries_left(self, record: Dict[str, Any]) -> bool:
        return record["evaluation_attempts"] < 1 + config.MAX_EVALUATION_RETRIES

    def ensure_accepting_answer(self, question_id: str, now: Optional[datetime] = None) -> None:
        """Raise unless `question_id` is the active, unanswered, in-time current question.

        Shared by answer submission and audio transcription, so a recording can only
        ever be attributed to the question the interview is asking now.
        """
        now = now or utcnow()
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()

        if question_id != self.current_question_id:
            self._log(
                ServerIntegrityEventType.UNASSIGNED_QUESTION_ATTEMPT.value,
                "server",
                now,
                detail={"attempted_question_id": str(question_id)[:64]},
            )
            raise QuestionNotCurrentError()

        if question_id in self.answered_question_ids:
            self._log(ServerIntegrityEventType.DUPLICATE_SUBMISSION.value, "server", now, question_id=question_id)
            raise AnswerAlreadySubmittedError()

        if question_id in self.timed_out_question_ids:
            raise QuestionDeadlinePassedError()

        if self._past_deadline(now):
            elapsed = (now - self.question_started_at).total_seconds()
            self._mark_timed_out(now)
            self._log(
                ServerIntegrityEventType.LATE_SUBMISSION_REJECTED.value,
                "server",
                now,
                question_id=question_id,
                detail={
                    "elapsed_seconds": round(elapsed, 1),
                    "time_limit_seconds": self.question_time_limit_seconds,
                    "grace_seconds": self.question_grace_seconds,
                },
            )
            raise QuestionDeadlinePassedError()

    def record_answer(
        self,
        question_id: str,
        answer_text: str,
        submission_reason: SubmissionReason = SubmissionReason.CANDIDATE_SUBMITTED,
        integrity_events: Optional[List[IntegrityEvent]] = None,
        answer_source: AnswerSource = AnswerSource.TEXT,
        language: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Accept and store an answer (evaluation status: pending). No scoring happens here.

        Timing is computed from the SERVER's clock; submission_reason and any client
        timestamps are metadata only. Copy/paste/tab events are stored as reported.
        """
        now = now or utcnow()
        self.ensure_accepting_answer(question_id, now)

        timed_out, elapsed = check_timeout(self.question_started_at, self.question_time_limit_seconds, at=now)
        timing = TimingMetadata(
            question_started_at=self.question_started_at,
            submitted_at=now,
            time_limit_seconds=self.question_time_limit_seconds,
            grace_seconds=self.question_grace_seconds,
            elapsed_seconds=elapsed,
            timed_out=timed_out,
            submission_reason=submission_reason,
            integrity_events=list(integrity_events or []),
        )
        answer_id = str(uuid.uuid4())
        record: Dict[str, Any] = {
            "answer_id": answer_id,
            "question_id": question_id,
            "answer_text": answer_text,
            "answer_source": answer_source,
            "language": language,
            "timing": timing,
            "evaluation": None,
            "competency_update": None,
            "evaluation_status": EvaluationStatus.PENDING,
            "evaluation_error": None,
            "evaluation_attempts": 0,
            "evaluator": None,
        }
        self.answers.append(record)
        self.answered_question_ids.add(question_id)
        self.changes.append(
            ch.AnswerRecorded(
                answer_id=answer_id,
                question_id=question_id,
                answer_text=answer_text,
                answer_source=answer_source.value,
                submission_reason=submission_reason.value,
                language=language,
                submitted_at=now,
                elapsed_seconds=elapsed,
                time_limit_seconds=self.question_time_limit_seconds,
                grace_seconds=self.question_grace_seconds,
                timed_out=timed_out,
            )
        )

        # Indicators only (never scoring): implausibly fast typed answers, and the client's own events.
        if (
            answer_source == AnswerSource.TEXT
            and len(answer_text) >= config.FAST_SUBMISSION_MIN_CHARS
            and elapsed > 0
            and len(answer_text) / max(elapsed, 0.001) > config.FAST_SUBMISSION_CHARS_PER_SECOND
        ):
            self._log(
                ServerIntegrityEventType.FAST_SUBMISSION.value,
                "server",
                now,
                question_id=question_id,
                answer_id=answer_id,
                detail={
                    "characters": len(answer_text),
                    "elapsed_seconds": round(elapsed, 2),
                    "chars_per_second": round(len(answer_text) / max(elapsed, 0.001), 1),
                },
            )
        for event in integrity_events or []:
            self._log(
                event.event_type.value,
                "client",
                now,
                question_id=question_id,
                answer_id=answer_id,
                client_occurred_at=event.occurred_at,
                client_source=event.source,
                duration_ms=event.duration_ms,
            )
        return record

    def prepare_evaluation_retry(self, question_id: str) -> Dict[str, Any]:
        """Return the recorded answer if (re-)evaluating it is allowed, else raise."""
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()
        record = self.get_answer(question_id)
        if record is None:
            raise AnswerNotFoundError()
        if record["evaluation_status"] != EvaluationStatus.COMPLETED and not self._retries_left(record):
            raise EvaluationRetriesExhaustedError()
        return record

    def apply_evaluation(
        self,
        question: Question,
        evaluation: "ConceptualEvaluation | CodingEvaluation",
        now: Optional[datetime] = None,
    ) -> CompetencyUpdate:
        """Store a COMPLETED evaluation and update competency, exactly once per answer."""
        now = now or utcnow()
        record = self.get_answer(question.question_id)
        if record is None:
            raise AnswerNotFoundError()
        if record["evaluation_status"] == EvaluationStatus.COMPLETED:
            raise RuntimeError("answer already evaluated; competency must not be updated twice")

        update = self.competency_state.update_from_answer(question=question, overall_score=evaluation.overall_score)
        state = self.competency_state.get(update.competency)
        record["evaluation_attempts"] += 1
        record.update(
            evaluation=evaluation,
            competency_update=update,
            evaluation_status=EvaluationStatus.COMPLETED,
            evaluation_error=None,
            evaluator=evaluation.evaluator,
        )
        self.changes.append(
            ch.EvaluationCompleted(
                answer_id=record["answer_id"],
                question_id=question.question_id,
                evaluation=evaluation,
                evaluator=evaluation.evaluator,
                competency_id=update.competency,
                competency_update=update,
                last_score=state.last_score,
                at=now,
                attempts=record["evaluation_attempts"],
            )
        )
        return update

    def mark_evaluation_failed(self, question_id: str, error: EvaluationError, now: Optional[datetime] = None) -> None:
        """Record that evaluation did not produce a score. No score, no competency change."""
        now = now or utcnow()
        record = self.get_answer(question_id)
        if record is None:
            raise AnswerNotFoundError()
        if record["evaluation_status"] == EvaluationStatus.COMPLETED:
            raise RuntimeError("answer already evaluated")
        status = EvaluationStatus(error.status)
        record["evaluation_attempts"] += 1
        record.update(evaluation_status=status, evaluation_error=error.code)
        self.changes.append(
            ch.EvaluationFailed(
                answer_id=record["answer_id"],
                status=status,
                error_code=error.code,
                attempts=record["evaluation_attempts"],
                at=now,
            )
        )

    # ---------------------------------------------------------------- progression

    def advance_to_next_question(self, now: Optional[datetime] = None) -> None:
        """Move to the next question, or complete the interview.

        The current question must be RESOLVED first: answered and evaluated, or
        timed out (no accepted answer before the deadline), or its evaluation
        permanently failed after all retries. An answer whose evaluation is still
        pending/failed-with-retries-left blocks progress, because competency (and so
        the next question) depends on it. The next question comes from
        question_selector.select_next_question (QScore ranking). The interview
        completes after question_count questions, or when the topic has no
        unasked servable question left.
        """
        now = now or utcnow()
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()

        qid = self.current_question_id
        if qid is None:
            raise QuestionNotAnsweredError()

        if qid not in self.timed_out_question_ids:
            record = self.get_answer(qid)
            if record is None:
                if self._past_deadline(now):
                    self._mark_timed_out(now)
                else:
                    raise QuestionNotAnsweredError()
            elif record["evaluation_status"] != EvaluationStatus.COMPLETED and self._retries_left(record):
                raise EvaluationPendingError()

        if self.current_question >= self.question_count:
            self._complete(now)
            return

        next_question = select_next_question(
            topic=self.topic,
            difficulty=self.difficulty,
            asked_question_ids=self.asked_question_ids,
            competency_states=self.competency_state.get_all(),
            encountered=self.encountered,
            rng=self._rng,
        )
        if next_question is None:
            self._complete(now)
            return

        self.current_question += 1
        self._set_current_question(next_question, now)

    def _complete(self, now: datetime) -> None:
        self.status = InterviewStatus.COMPLETED
        self.completed_at = now
        self.current_question_id = None
        self.question_started_at = None
        self.question_time_limit_seconds = None
        self.changes.append(ch.InterviewCompleted(at=now))

    # --------------------------------------------------------------------- views

    def question_state(self) -> Optional[QuestionState]:
        qid = self.current_question_id
        if qid is None:
            return None
        if qid in self.timed_out_question_ids:
            return QuestionState.TIMED_OUT
        record = self.get_answer(qid)
        if record is None:
            return QuestionState.ACTIVE
        status = record["evaluation_status"]
        if status == EvaluationStatus.COMPLETED:
            return QuestionState.EVALUATED
        if status == EvaluationStatus.PENDING:
            return QuestionState.EVALUATION_PENDING
        return QuestionState.EVALUATION_FAILED

    def next_action(self, now: Optional[datetime] = None) -> NextAction:
        now = now or utcnow()
        if self.status == InterviewStatus.COMPLETED:
            return NextAction.COMPLETED
        state = self.question_state()
        if state is None:
            return NextAction.NONE
        if state == QuestionState.ACTIVE:
            return NextAction.ADVANCE if self._past_deadline(now) else NextAction.ANSWER
        if state in (QuestionState.EVALUATION_PENDING, QuestionState.EVALUATION_FAILED):
            record = self.get_answer(self.current_question_id)
            return NextAction.RETRY_EVALUATION if self._retries_left(record) else NextAction.ADVANCE
        return NextAction.ADVANCE  # evaluated or timed out

    def to_response(self, now: Optional[datetime] = None) -> InterviewResponse:
        """Convert internal session state into the API response shape."""
        now = now or utcnow()
        remaining = None
        if self.question_started_at is not None and self.question_time_limit_seconds is not None:
            remaining = max(0.0, self.question_time_limit_seconds - (now - self.question_started_at).total_seconds())
        return InterviewResponse(
            interview_id=self.interview_id,
            topic=self.topic,
            difficulty=self.difficulty,
            question_count=self.question_count,
            current_question=self.current_question,
            current_question_id=self.current_question_id,
            status=self.status,
            candidate_id=self.candidate_id,
            question_state=self.question_state(),
            next_action=self.next_action(now),
            question_started_at=self.question_started_at,
            question_time_limit_seconds=self.question_time_limit_seconds,
            grace_seconds=self.question_grace_seconds if self.question_started_at is not None else None,
            deadline_at=self.deadline_at,
            seconds_remaining=remaining,
        )


class InterviewEngine:
    """In-memory interview storage: DEVELOPMENT AND TESTS ONLY (lost on restart).

    Production uses PostgreSQL (app/db/postgres_store.py).
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, InterviewSession] = {}
        self._locks: Dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def create_interview(
        self,
        topic: str,
        difficulty: DifficultyLevel,
        question_count: int,
        candidate_id: Optional[str] = None,
        encountered: Optional[Mapping[str, datetime]] = None,
    ) -> InterviewSession:
        """Create a new interview session and store it."""
        session = InterviewSession(
            topic=topic,
            difficulty=difficulty,
            question_count=question_count,
            candidate_id=candidate_id,
            encountered=encountered,
        )
        with self._guard:
            self._sessions[session.interview_id] = session
            self._locks[session.interview_id] = threading.RLock()
        return session

    def get_interview(self, interview_id: str) -> Optional[InterviewSession]:
        """Return the session for interview_id, or None if it doesn't exist."""
        return self._sessions.get(interview_id)

    def lock_for(self, interview_id: str) -> Optional[threading.RLock]:
        return self._locks.get(interview_id)

    def sessions(self) -> List[InterviewSession]:
        with self._guard:
            return list(self._sessions.values())


# Shared in-memory engine (used by MemoryInterviewStore).
interview_engine = InterviewEngine()
