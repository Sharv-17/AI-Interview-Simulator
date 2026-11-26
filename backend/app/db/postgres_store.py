"""PostgreSQL implementation of InterviewStore.

The interview rules stay in the domain (app/services/interview_engine.py). This module
loads one interview from the database, hands it to the domain inside a single
transaction, and writes back the changes the domain recorded in `session.changes`
(app/services/domain_changes.py). No rule, score or formula is duplicated here.

Transaction boundaries match MemoryInterviewStore:

* `edit()` takes an exclusive row lock (SELECT ... FOR UPDATE NOWAIT); a second writer
  gets InterviewBusyError instead of waiting.
* A successful operation is committed.
* A DomainRejection is committed too: the domain may deliberately leave an integrity
  indicator or a "timed out" mark behind.
* Any other exception rolls the whole operation back.

The question bank (data/question_bank.json) stays the source of truth; `startup()`
copies it into the `questions` table so interview questions can reference it.
"""

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    CandidateAnswerModel,
    CandidateModel,
    CompetencyHistoryModel,
    EvaluationResultModel,
    InterviewQuestionModel,
    InterviewSessionModel,
    IntegrityEventModel,
    QuestionModel,
)
from app.repositories.question_repository import question_repository
from app.schemas.candidate import (
    CandidateCreate,
    CandidateView,
    CompetencyHistoryEntry,
    InterviewSummary,
)
from app.schemas.competency import CompetencyState, CompetencyUpdate
from app.schemas.evaluation import (
    AnswerSource,
    CodingEvaluation,
    ConceptualEvaluation,
    EvaluationStatus,
)
from app.schemas.integrity import (
    IntegrityEvent,
    IntegrityEventType,
    IntegrityRecord,
    SubmissionReason,
    TimingMetadata,
)
from app.schemas.interview import DifficultyLevel, InterviewStatus
from app.schemas.question import Question, QuestionType
from app.schemas.report import AnswerReport, InterviewReport, QuestionReport
from app.services import domain_changes as ch
from app.services.competency_state import CompetencyStateStore
from app.services.evaluation_errors import (
    CandidateNotFoundError,
    DomainRejection,
    InterviewBusyError,
    InterviewNotFoundError,
)
from app.services.interview_engine import InterviewSession, utcnow
from app.services.interview_store import InterviewStore, _summary

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATE for "could not obtain lock" (NOWAIT on a locked row).
_LOCK_NOT_AVAILABLE = "55P03"


def _normalize_url(url: str) -> str:
    """Ensure the URL names the psycopg driver explicitly (the declared dependency)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def _question_values(question: Question, synced_at: datetime) -> Dict[str, Any]:
    """Column values for one question-bank entry (the JSON file is the source of truth)."""
    return dict(
        question_id=question.question_id,
        question_text=question.question_text,
        topic=question.topic,
        subtopic=question.subtopic,
        difficulty=question.difficulty.value,
        question_type=question.question_type.value,
        competency=question.competency,
        estimated_time_seconds=question.estimated_time_seconds,
        review_status=question.review_status.value if question.review_status else None,
        source=question.source,
        tags=list(question.tags),
        expected_concepts=list(question.expected_concepts),
        evaluation_criteria=list(question.evaluation_criteria),
        reference_answer=question.reference_answer,
        synced_at=synced_at,
    )


class PostgresInterviewStore(InterviewStore):
    backend_name = "postgres"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    # ------------------------------------------------------------------ wiring

    @classmethod
    def from_url(cls, url: str, **engine_kwargs: Any) -> "PostgresInterviewStore":
        """Build a store from a connection URL. Credentials are never logged."""
        options: Dict[str, Any] = {"pool_pre_ping": True, "pool_recycle": 300}
        options.update(engine_kwargs)
        return cls(create_engine(_normalize_url(url), **options))

    def dispose(self) -> None:
        self._engine.dispose()

    def check_ready(self) -> None:
        """Run a real query; never report readiness from configuration alone."""
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - reported as unavailable, details stay in logs
            logger.warning("PostgreSQL readiness check failed: %s", type(exc).__name__)
            raise RuntimeError("PostgreSQL is not available") from exc

    def startup(self) -> None:
        """Copy the question bank into `questions` (idempotent).

        Interview questions carry a foreign key to `questions`, so the reference rows
        must exist before any interview can be persisted. Re-running updates rows in
        place instead of duplicating them.
        """
        with self._session_factory() as db:
            try:
                synced = self._sync_questions(db)
                db.commit()
            except Exception:
                db.rollback()
                raise
        logger.info("Question bank synced to PostgreSQL (%d questions).", synced)

    def _sync_questions(self, db: Session) -> int:
        questions = question_repository.get_all()
        if not questions:
            return 0
        now = utcnow()
        rows = [_question_values(question, now) for question in questions]
        statement = pg_insert(QuestionModel).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=[QuestionModel.question_id],
            set_={column: getattr(statement.excluded, column) for column in rows[0] if column != "question_id"},
        )
        db.execute(statement)
        return len(rows)

    # ---------------------------------------------------------------- interviews

    def _question_history(self, db: Session, candidate_id: str, topic: str) -> Dict[str, datetime]:
        """When this candidate last saw each question of `topic` (assigned, not answered).

        Reads the existing interview_questions rows: unanswered, timed-out and
        abandoned assignments all count as encounters. No extra table is needed.
        """
        rows = db.execute(
            select(InterviewQuestionModel.question_id, func.max(InterviewQuestionModel.assigned_at))
            .join(
                InterviewSessionModel,
                InterviewQuestionModel.interview_id == InterviewSessionModel.interview_id,
            )
            .where(
                InterviewSessionModel.candidate_id == candidate_id,
                func.lower(InterviewSessionModel.topic) == topic.lower(),
            )
            .group_by(InterviewQuestionModel.question_id)
        ).all()
        return {question_id: last_assigned for question_id, last_assigned in rows}

    def create_interview(
        self, topic: str, difficulty: DifficultyLevel, question_count: int, candidate_id: Optional[str]
    ) -> InterviewSession:
        db = self._session_factory()
        try:
            history: Dict[str, datetime] = {}
            if candidate_id is not None:
                # Lock the candidate row: two concurrent starts for one candidate are
                # serialised, so the second one sees the first assignment in its history.
                # FOR NO KEY UPDATE (not FOR UPDATE) because it conflicts with itself but
                # not with the FOR KEY SHARE locks that FK checks take when answers are
                # evaluated for the same candidate; the lock is held only until commit.
                candidate = db.execute(
                    select(CandidateModel)
                    .where(CandidateModel.candidate_id == candidate_id)
                    .with_for_update(key_share=True)
                ).scalar_one_or_none()
                if candidate is None:
                    raise CandidateNotFoundError()
                history = self._question_history(db, candidate_id, topic)
            session = InterviewSession(
                topic=topic,
                difficulty=difficulty,
                question_count=question_count,
                candidate_id=candidate_id,
                encountered=history,
            )
            # The session row references its first question: that row must exist first
            # (a no-op after startup(), but it makes the store independent of call order).
            if session.current_question_id is not None:
                self._ensure_question_row(db, session.current_question_id)
            db.add(
                InterviewSessionModel(
                    interview_id=session.interview_id,
                    candidate_id=session.candidate_id,
                    topic=session.topic,
                    difficulty=session.difficulty.value,
                    question_count=session.question_count,
                    current_question=session.current_question,
                    status=session.status.value,
                    current_question_id=session.current_question_id,
                    question_started_at=session.question_started_at,
                    question_time_limit_seconds=session.question_time_limit_seconds,
                    question_grace_seconds=session.question_grace_seconds,
                    created_at=session.created_at,
                    completed_at=None,
                )
            )
            db.flush()
            self._persist(db, session)
            db.commit()
            return session
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def edit(self, interview_id: str, with_history: bool = False) -> Iterator[InterviewSession]:
        db = self._session_factory()
        committed = False
        try:
            row = self._lock_interview(db, interview_id)
            session, _, _ = self._load_interview(db, row, with_history=with_history)
            try:
                yield session
            except DomainRejection:
                # A rejection may deliberately leave an integrity event or a timeout mark.
                self._persist(db, session)
                db.commit()
                committed = True
                raise
            else:
                self._persist(db, session)
                db.commit()
                committed = True
        except BaseException:
            if not committed:
                db.rollback()
            raise
        finally:
            db.close()

    def read(self, interview_id: str) -> InterviewSession:
        db = self._session_factory()
        try:
            session, _, _ = self._load_interview_by_id(db, interview_id)
            return session
        finally:
            db.rollback()
            db.close()

    def record_integrity_events(
        self, interview_id: str, question_id: Optional[str], events: List[IntegrityEvent], now: datetime
    ) -> Tuple[str, int]:
        with self.edit(interview_id) as session:
            kept = session.record_client_integrity_events(events, question_id, now)
            return session.current_question_id, kept

    # ---------------------------------------------------------------- candidates

    def create_candidate(self, payload: CandidateCreate) -> CandidateView:
        db = self._session_factory()
        candidate_id = str(uuid.uuid4())
        created_at = utcnow()
        try:
            db.add(
                CandidateModel(
                    candidate_id=candidate_id,
                    display_name=payload.display_name,
                    external_id=payload.external_id,
                    created_at=created_at,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if payload.external_id:
                    # Same contract as MemoryInterviewStore (the API maps this to 409).
                    raise ValueError("external_id already exists") from None
                raise
            return CandidateView(
                candidate_id=candidate_id,
                display_name=payload.display_name,
                external_id=payload.external_id,
                created_at=created_at,
            )
        finally:
            db.close()

    def get_candidate(self, candidate_id: str) -> CandidateView:
        db = self._session_factory()
        try:
            row = db.get(CandidateModel, candidate_id)
            if row is None:
                raise CandidateNotFoundError()
            return _candidate_view(row)
        finally:
            db.close()

    def list_interviews(self, candidate_id: str) -> List[InterviewSummary]:
        db = self._session_factory()
        try:
            if db.get(CandidateModel, candidate_id) is None:
                raise CandidateNotFoundError()
            rows = (
                db.execute(
                    select(InterviewSessionModel)
                    .where(InterviewSessionModel.candidate_id == candidate_id)
                    .order_by(InterviewSessionModel.created_at, InterviewSessionModel.interview_id)
                )
                .scalars()
                .all()
            )
            return [_summary_of_row(row) for row in rows]
        finally:
            db.close()

    def competency_history(self, candidate_id: str) -> List[CompetencyHistoryEntry]:
        db = self._session_factory()
        try:
            if db.get(CandidateModel, candidate_id) is None:
                raise CandidateNotFoundError()
            rows = (
                db.execute(
                    select(CompetencyHistoryModel)
                    .where(CompetencyHistoryModel.candidate_id == candidate_id)
                    .order_by(CompetencyHistoryModel.recorded_at, CompetencyHistoryModel.id)
                )
                .scalars()
                .all()
            )
            return [
                CompetencyHistoryEntry(
                    interview_id=row.interview_id,
                    competency_id=row.competency_id,
                    answer_id=row.answer_id,
                    question_id=row.question_id,
                    previous_theta=row.previous_theta,
                    new_theta=row.new_theta,
                    normalized_score=row.normalized_score,
                    questions_attempted=row.questions_attempted,
                    recorded_at=row.recorded_at,
                )
                for row in rows
            ]
        finally:
            db.close()

    # ------------------------------------------------------------------ reports

    def report(self, interview_id: str) -> InterviewReport:
        db = self._session_factory()
        try:
            session, _, iq_rows = self._load_interview_by_id(db, interview_id)
            questions: List[QuestionReport] = []
            for iq in iq_rows:
                bank = question_repository.get_by_id(iq.question_id)
                record = session.get_answer(iq.question_id)
                if iq.question_id in session.timed_out_question_ids:
                    state = "timed_out"
                elif record is None:
                    state = "active" if iq.question_id == session.current_question_id else "unanswered"
                else:
                    state = (
                        "evaluated"
                        if record["evaluation_status"] == EvaluationStatus.COMPLETED
                        else "answered"
                    )
                questions.append(
                    QuestionReport(
                        sequence=iq.sequence,
                        question_id=iq.question_id,
                        question_text=bank.question_text if bank else None,
                        topic=bank.topic if bank else None,
                        difficulty=bank.difficulty.value if bank else None,
                        question_type=bank.question_type.value if bank else None,
                        state=state,
                        assigned_at=iq.assigned_at,
                        closed_at=iq.closed_at,
                        time_limit_seconds=iq.time_limit_seconds,
                        grace_seconds=iq.grace_seconds,
                    )
                )
            answers = [_answer_report(record) for record in session.answers]
            records = [IntegrityRecord(**entry) for entry in session.integrity_log]
            summary: Dict[str, int] = {}
            for record in records:
                summary[record.event_type] = summary.get(record.event_type, 0) + 1
            return InterviewReport(
                interview=_summary(session),
                questions=questions,
                answers=answers,
                competency=session.competency_state.get_all(),
                integrity_events=records,
                integrity_summary=summary,
            )
        finally:
            db.rollback()
            db.close()

    # -------------------------------------------------------------- row locking

    def _lock_interview(self, db: Session, interview_id: str) -> InterviewSessionModel:
        try:
            row = db.execute(
                select(InterviewSessionModel)
                .where(InterviewSessionModel.interview_id == interview_id)
                .with_for_update(nowait=True)
            ).scalar_one_or_none()
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE:
                raise InterviewBusyError() from None
            raise
        if row is None:
            raise InterviewNotFoundError()
        return row

    # ----------------------------------------------------------- reconstruction

    def _load_interview_by_id(
        self, db: Session, interview_id: str, with_history: bool = False
    ) -> Tuple[InterviewSession, InterviewSessionModel, List[InterviewQuestionModel]]:
        row = db.get(InterviewSessionModel, interview_id)
        if row is None:
            raise InterviewNotFoundError()
        return self._load_interview(db, row, with_history=with_history)

    def _load_interview(
        self, db: Session, row: InterviewSessionModel, with_history: bool = False
    ) -> Tuple[InterviewSession, InterviewSessionModel, List[InterviewQuestionModel]]:
        """Rebuild the domain object from the database. No rule is re-implemented here.

        History is loaded only when the caller is about to select a question
        (`with_history=True`), never for ordinary reads.
        """
        history: Dict[str, datetime] = {}
        if with_history and row.candidate_id is not None:
            history = self._question_history(db, row.candidate_id, row.topic)
        session = InterviewSession(
            topic=row.topic,
            difficulty=DifficultyLevel(row.difficulty),
            question_count=row.question_count,
            candidate_id=row.candidate_id,
            now=row.created_at,
            encountered=history,
            select_initial=False,
        )
        session.changes.clear()

        session.interview_id = row.interview_id
        session.candidate_id = row.candidate_id
        session.topic = row.topic
        session.difficulty = DifficultyLevel(row.difficulty)
        session.question_count = row.question_count
        session.current_question = row.current_question
        session.status = InterviewStatus(row.status)
        session.created_at = row.created_at
        session.completed_at = row.completed_at
        session.current_question_id = row.current_question_id
        session.question_started_at = row.question_started_at
        session.question_time_limit_seconds = row.question_time_limit_seconds
        session.question_grace_seconds = row.question_grace_seconds

        iq_rows = (
            db.execute(
                select(InterviewQuestionModel)
                .where(InterviewQuestionModel.interview_id == row.interview_id)
                .order_by(InterviewQuestionModel.sequence)
            )
            .scalars()
            .all()
        )
        by_question = {iq.question_id: iq for iq in iq_rows}
        session.encountered = dict(history)
        session.question_assigned_at = {iq.question_id: iq.assigned_at for iq in iq_rows}
        session.asked_question_ids = [iq.question_id for iq in iq_rows]
        session.timed_out_question_ids = {iq.question_id for iq in iq_rows if iq.state == "timed_out"}

        answer_rows = (
            db.execute(
                select(CandidateAnswerModel)
                .join(
                    InterviewQuestionModel,
                    CandidateAnswerModel.interview_question_id == InterviewQuestionModel.id,
                )
                .where(CandidateAnswerModel.interview_id == row.interview_id)
                .order_by(InterviewQuestionModel.sequence)
            )
            .scalars()
            .all()
        )
        answer_ids = [answer.answer_id for answer in answer_rows]
        evaluation_rows: Dict[str, EvaluationResultModel] = {}
        competency_rows: Dict[str, CompetencyHistoryModel] = {}
        if answer_ids:
            evaluation_rows = {
                evaluation.answer_id: evaluation
                for evaluation in db.execute(
                    select(EvaluationResultModel).where(EvaluationResultModel.answer_id.in_(answer_ids))
                )
                .scalars()
                .all()
            }
            # Ordered by id: the LAST row per competency is its current state, so the
            # order must be chronological (several answers can hit one competency).
            competency_rows = {
                competency.answer_id: competency
                for competency in db.execute(
                    select(CompetencyHistoryModel)
                    .where(CompetencyHistoryModel.answer_id.in_(answer_ids))
                    .order_by(CompetencyHistoryModel.id)
                )
                .scalars()
                .all()
            }

        integrity_rows = (
            db.execute(
                select(IntegrityEventModel)
                .where(IntegrityEventModel.interview_id == row.interview_id)
                .order_by(IntegrityEventModel.id)
            )
            .scalars()
            .all()
        )
        client_events: Dict[str, List[IntegrityEvent]] = {}
        for event in integrity_rows:
            if event.answer_id is None:
                continue
            parsed = _client_event(event)
            if parsed is not None:
                client_events.setdefault(event.answer_id, []).append(parsed)

        session.answers = [
            _answer_record(
                answer,
                by_question[answer.question_id],
                evaluation_rows.get(answer.answer_id),
                competency_rows.get(answer.answer_id),
                client_events.get(answer.answer_id, []),
            )
            for answer in answer_rows
            if answer.question_id in by_question
        ]
        session.answered_question_ids = {record["question_id"] for record in session.answers}
        session.integrity_log = [
            dict(
                event_type=event.event_type,
                source=event.source,
                question_id=event.question_id,
                answer_id=event.answer_id,
                client_occurred_at=event.client_occurred_at,
                received_at=event.received_at,
                duration_ms=event.duration_ms,
                detail=event.detail or {},
            )
            for event in integrity_rows
        ]
        session.integrity_event_count = len(integrity_rows)
        session.competency_state = CompetencyStateStore()
        session.competency_state.restore(_competency_states(list(competency_rows.values())))
        return session, row, list(iq_rows)

    # ------------------------------------------------------------------ writing

    def _persist(self, db: Session, session: InterviewSession) -> None:
        """Apply the domain's recorded changes, then write the session's own row."""
        for change in session.changes:
            self._apply_change(db, session, change)
        self._write_session_row(db, session)
        db.flush()
        session.changes.clear()

    def _apply_change(self, db: Session, session: InterviewSession, change: ch.Change) -> None:
        if isinstance(change, ch.QuestionAssigned):
            self._ensure_question_row(db, change.question_id)
            db.add(
                InterviewQuestionModel(
                    interview_id=session.interview_id,
                    sequence=change.sequence,
                    question_id=change.question_id,
                    state="active",
                    assigned_at=change.assigned_at,
                    closed_at=None,
                    time_limit_seconds=change.time_limit_seconds,
                    grace_seconds=change.grace_seconds,
                )
            )
            db.flush()
        elif isinstance(change, ch.QuestionTimedOut):
            db.execute(
                update(InterviewQuestionModel)
                .where(
                    InterviewQuestionModel.interview_id == session.interview_id,
                    InterviewQuestionModel.question_id == change.question_id,
                )
                .values(state="timed_out", closed_at=change.at)
            )
        elif isinstance(change, ch.AnswerRecorded):
            interview_question = self._interview_question(db, session.interview_id, change.question_id)
            db.add(
                CandidateAnswerModel(
                    answer_id=change.answer_id,
                    interview_question_id=interview_question.id,
                    interview_id=session.interview_id,
                    question_id=change.question_id,
                    answer_text=change.answer_text,
                    answer_source=change.answer_source,
                    submission_reason=change.submission_reason,
                    language=change.language,
                    submitted_at=change.submitted_at,
                    elapsed_seconds=change.elapsed_seconds,
                    time_limit_seconds=change.time_limit_seconds,
                    grace_seconds=change.grace_seconds,
                    timed_out=change.timed_out,
                    evaluation_status=EvaluationStatus.PENDING.value,
                    evaluation_error=None,
                    evaluation_attempts=0,
                )
            )
            interview_question.state = "answered"
            interview_question.closed_at = change.submitted_at
            db.flush()
        elif isinstance(change, ch.EvaluationCompleted):
            evaluation = change.evaluation
            answer = db.get(CandidateAnswerModel, change.answer_id)
            if answer is None:
                raise RuntimeError(f"answer {change.answer_id} is not persisted")
            answer.evaluation_status = EvaluationStatus.COMPLETED.value
            answer.evaluation_error = None
            answer.evaluation_attempts = change.attempts
            details = evaluation.model_dump(mode="json")
            details.pop("reasoning_summary", None)
            db.add(
                EvaluationResultModel(
                    answer_id=change.answer_id,
                    kind=evaluation.question_type.value,
                    evaluator=change.evaluator,
                    overall_score=evaluation.overall_score,
                    max_score=evaluation.max_score,
                    details=details,
                    reasoning_summary=getattr(evaluation, "reasoning_summary", None),
                    created_at=change.at,
                )
            )
            update_ = change.competency_update
            db.add(
                CompetencyHistoryModel(
                    interview_id=session.interview_id,
                    candidate_id=session.candidate_id,
                    competency_id=change.competency_id,
                    answer_id=change.answer_id,
                    question_id=change.question_id,
                    previous_theta=update_.previous_theta,
                    new_theta=update_.new_theta,
                    normalized_score=update_.normalized_score,
                    last_score=change.last_score,
                    questions_attempted=update_.questions_attempted,
                    recorded_at=change.at,
                )
            )
            db.flush()
        elif isinstance(change, ch.EvaluationFailed):
            answer = db.get(CandidateAnswerModel, change.answer_id)
            if answer is None:
                raise RuntimeError(f"answer {change.answer_id} is not persisted")
            answer.evaluation_status = change.status.value
            answer.evaluation_error = change.error_code
            answer.evaluation_attempts = change.attempts
        elif isinstance(change, ch.IntegrityLogged):
            db.add(
                IntegrityEventModel(
                    interview_id=session.interview_id,
                    question_id=change.question_id,
                    answer_id=change.answer_id,
                    event_type=change.event_type,
                    source=change.source,
                    client_occurred_at=change.client_occurred_at,
                    client_source=change.client_source,
                    received_at=change.received_at,
                    duration_ms=change.duration_ms,
                    detail=change.detail or {},
                )
            )
        elif isinstance(change, ch.InterviewCompleted):
            pass  # the session row (status/completed_at) is written by _write_session_row

    def _write_session_row(self, db: Session, session: InterviewSession) -> None:
        row = db.get(InterviewSessionModel, session.interview_id)
        if row is None:
            raise RuntimeError(f"interview {session.interview_id} is not persisted")
        row.candidate_id = session.candidate_id
        row.topic = session.topic
        row.difficulty = session.difficulty.value
        row.question_count = session.question_count
        row.current_question = session.current_question
        row.status = session.status.value
        row.current_question_id = session.current_question_id
        row.question_started_at = session.question_started_at
        row.question_time_limit_seconds = session.question_time_limit_seconds
        row.question_grace_seconds = session.question_grace_seconds
        row.completed_at = session.completed_at

    def _interview_question(self, db: Session, interview_id: str, question_id: str) -> InterviewQuestionModel:
        row = db.execute(
            select(InterviewQuestionModel).where(
                InterviewQuestionModel.interview_id == interview_id,
                InterviewQuestionModel.question_id == question_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise RuntimeError(f"question {question_id} is not assigned to interview {interview_id}")
        return row

    def _ensure_question_row(self, db: Session, question_id: str) -> None:
        """The questions table must hold a row before interview_questions can reference it."""
        if db.get(QuestionModel, question_id) is not None:
            return
        question = question_repository.get_by_id(question_id)
        if question is None:
            raise RuntimeError(f"question {question_id} is not in the question bank")
        db.add(QuestionModel(**_question_values(question, utcnow())))
        db.flush()


# --------------------------------------------------------------------- mapping


def _candidate_view(row: CandidateModel) -> CandidateView:
    return CandidateView(
        candidate_id=row.candidate_id,
        display_name=row.display_name,
        external_id=row.external_id,
        created_at=row.created_at,
    )


def _summary_of_row(row: InterviewSessionModel) -> InterviewSummary:
    return InterviewSummary(
        interview_id=row.interview_id,
        candidate_id=row.candidate_id,
        topic=row.topic,
        difficulty=DifficultyLevel(row.difficulty),
        question_count=row.question_count,
        current_question=row.current_question,
        status=InterviewStatus(row.status),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _client_event(row: IntegrityEventModel) -> Optional[IntegrityEvent]:
    if row.source != "client":
        return None
    try:
        event_type = IntegrityEventType(row.event_type)
    except ValueError:
        return None
    return IntegrityEvent(
        event_type=event_type,
        occurred_at=row.client_occurred_at,
        source=row.client_source,
        duration_ms=row.duration_ms,
    )


def _evaluation(row: Optional[EvaluationResultModel]) -> Optional[Any]:
    if row is None:
        return None
    details = dict(row.details or {})
    details.pop("reasoning_summary", None)
    details["overall_score"] = row.overall_score
    details["max_score"] = row.max_score
    details["evaluator"] = row.evaluator
    if row.kind == QuestionType.CODING.value:
        return CodingEvaluation(**details)
    return ConceptualEvaluation(**details, reasoning_summary=row.reasoning_summary)


def _answer_record(
    row: CandidateAnswerModel,
    interview_question: InterviewQuestionModel,
    evaluation_row: Optional[EvaluationResultModel],
    competency_row: Optional[CompetencyHistoryModel],
    client_events: List[IntegrityEvent],
) -> Dict[str, Any]:
    """Rebuild one entry of InterviewSession.answers (same shape the domain keeps)."""
    evaluation = _evaluation(evaluation_row)
    competency_update = (
        CompetencyUpdate(
            competency=competency_row.competency_id,
            previous_theta=competency_row.previous_theta,
            normalized_score=competency_row.normalized_score,
            new_theta=competency_row.new_theta,
            questions_attempted=competency_row.questions_attempted,
        )
        if competency_row is not None
        else None
    )
    return {
        "answer_id": row.answer_id,
        "question_id": row.question_id,
        "answer_text": row.answer_text,
        "answer_source": AnswerSource(row.answer_source),
        "language": row.language,
        "timing": TimingMetadata(
            question_started_at=interview_question.assigned_at,
            submitted_at=row.submitted_at,
            time_limit_seconds=row.time_limit_seconds,
            grace_seconds=row.grace_seconds,
            elapsed_seconds=row.elapsed_seconds,
            timed_out=row.timed_out,
            submission_reason=SubmissionReason(row.submission_reason),
            integrity_events=list(client_events),
        ),
        "evaluation": evaluation,
        "competency_update": competency_update,
        "evaluation_status": EvaluationStatus(row.evaluation_status),
        "evaluation_error": row.evaluation_error,
        "evaluation_attempts": row.evaluation_attempts,
        "evaluator": evaluation.evaluator if evaluation is not None else None,
    }


def _competency_states(rows: Sequence[CompetencyHistoryModel]) -> Dict[str, CompetencyState]:
    """Persisted state per competency: the last history row holds the current theta."""
    states: Dict[str, CompetencyState] = {}
    for row in rows:
        states[row.competency_id] = CompetencyState(
            competency_id=row.competency_id,
            theta=row.new_theta,
            questions_attempted=row.questions_attempted,
            last_score=row.last_score,
            last_updated=row.recorded_at,
        )
    return states


def _answer_report(record: Dict[str, Any]) -> AnswerReport:
    return AnswerReport(
        answer_id=record["answer_id"],
        question_id=record["question_id"],
        answer_text=record["answer_text"],
        answer_source=record["answer_source"].value,
        submission_reason=record["timing"].submission_reason.value,
        language=record.get("language"),
        submitted_at=record["timing"].submitted_at,
        elapsed_seconds=record["timing"].elapsed_seconds,
        time_limit_seconds=record["timing"].time_limit_seconds,
        grace_seconds=record["timing"].grace_seconds,
        timed_out=record["timing"].timed_out,
        evaluation_status=record["evaluation_status"],
        evaluation_attempts=record["evaluation_attempts"],
        evaluation_error=record["evaluation_error"],
        evaluator=record["evaluator"],
        evaluation=record["evaluation"],
        reasoning_summary=getattr(record["evaluation"], "reasoning_summary", None),
        competency_update=record["competency_update"],
    )
