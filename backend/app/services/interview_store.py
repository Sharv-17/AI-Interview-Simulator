"""Interview storage interface and the in-memory implementation.

InterviewStore is what the service layer talks to. Two implementations:
* MemoryInterviewStore (here): development and tests; lost on restart.
* PostgresInterviewStore (app/db/postgres_store.py): production.

`edit()` gives exclusive access to one interview for one operation. On success OR
on a DomainRejection the changes the domain made are committed (rejections can
deliberately leave integrity indicators / a timed-out mark behind); any other
exception rolls the operation back. If another request holds the interview,
InterviewBusyError is raised instead of waiting.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple
import threading
import uuid

from app.schemas.candidate import (
    CandidateCreate,
    CandidateView,
    CompetencyHistoryEntry,
    InterviewSummary,
)
from app.schemas.integrity import IntegrityEvent
from app.schemas.interview import DifficultyLevel
from app.schemas.report import AnswerReport, InterviewReport, QuestionReport
from app.services.evaluation_errors import (
    CandidateNotFoundError,
    InterviewBusyError,
    InterviewNotFoundError,
)
from app.services.interview_engine import InterviewEngine, InterviewSession, interview_engine, utcnow


class InterviewStore(ABC):
    backend_name = "abstract"

    @abstractmethod
    def create_interview(
        self, topic: str, difficulty: DifficultyLevel, question_count: int, candidate_id: Optional[str]
    ) -> InterviewSession: ...

    @abstractmethod
    def edit(self, interview_id: str, with_history: bool = False): ...  # context manager yielding InterviewSession

    @abstractmethod
    def read(self, interview_id: str) -> InterviewSession: ...

    @abstractmethod
    def record_integrity_events(
        self, interview_id: str, question_id: Optional[str], events: List[IntegrityEvent], now: datetime
    ) -> Tuple[str, int]: ...

    @abstractmethod
    def create_candidate(self, payload: CandidateCreate) -> CandidateView: ...

    @abstractmethod
    def get_candidate(self, candidate_id: str) -> CandidateView: ...

    @abstractmethod
    def list_interviews(self, candidate_id: str) -> List[InterviewSummary]: ...

    @abstractmethod
    def competency_history(self, candidate_id: str) -> List[CompetencyHistoryEntry]: ...

    @abstractmethod
    def report(self, interview_id: str) -> InterviewReport: ...

    @abstractmethod
    def check_ready(self) -> None:
        """Raise if the store cannot serve requests (e.g. database unreachable)."""

    def register_candidate(
        self, candidate_id: str, created_at: datetime, display_name: Optional[str] = None
    ) -> None:
        """Make a candidate created outside this store usable by it.

        Only the memory backend needs this: it keeps its own candidate registry, while
        PostgreSQL already holds the row the account store inserted. A no-op here.
        """
        return None

    def startup(self) -> None:
        """Optional one-time preparation at application start (e.g. seed reference data)."""
        return None


class MemoryInterviewStore(InterviewStore):
    backend_name = "memory"

    def __init__(self, engine: Optional[InterviewEngine] = None) -> None:
        self._engine = engine or interview_engine
        self._candidates: Dict[str, CandidateView] = {}
        # Serialise concurrent interview creation for one candidate so the second
        # creation sees the first one's assignment in its cooldown history.
        self._creation_guard = threading.Lock()
        self._creation_locks: Dict[str, threading.Lock] = {}

    # ---------------------------------------------------------------- interviews

    def _creation_lock(self, candidate_id: str) -> threading.Lock:
        with self._creation_guard:
            return self._creation_locks.setdefault(candidate_id, threading.Lock())

    def _question_history(self, candidate_id: str, topic: str) -> Dict[str, datetime]:
        """When this candidate last saw each question of `topic` (assigned, not answered)."""
        history: Dict[str, datetime] = {}
        for session in self._engine.sessions():
            if session.candidate_id != candidate_id or session.topic.lower() != topic.lower():
                continue
            for question_id in session.asked_question_ids:
                assigned_at = session.question_assigned_at.get(question_id, session.created_at)
                if question_id not in history or assigned_at > history[question_id]:
                    history[question_id] = assigned_at
        return history

    def create_interview(self, topic, difficulty, question_count, candidate_id):
        if candidate_id is not None and candidate_id not in self._candidates:
            raise CandidateNotFoundError()
        if candidate_id is None:
            session = self._engine.create_interview(topic, difficulty, question_count, candidate_id)
        else:
            with self._creation_lock(candidate_id):
                history = self._question_history(candidate_id, topic)
                session = self._engine.create_interview(
                    topic, difficulty, question_count, candidate_id, encountered=history
                )
        session.changes.clear()
        return session

    @contextmanager
    def edit(self, interview_id: str, with_history: bool = False) -> Iterator[InterviewSession]:
        # The in-memory session already carries its cooldown history; nothing to load.
        session = self._engine.get_interview(interview_id)
        lock = self._engine.lock_for(interview_id)
        if session is None or lock is None:
            raise InterviewNotFoundError()
        if not lock.acquire(blocking=False):
            raise InterviewBusyError()
        try:
            yield session
        finally:
            session.changes.clear()
            lock.release()

    def read(self, interview_id: str) -> InterviewSession:
        session = self._engine.get_interview(interview_id)
        if session is None:
            raise InterviewNotFoundError()
        return session

    def record_integrity_events(self, interview_id, question_id, events, now):
        with self.edit(interview_id) as session:
            kept = session.record_client_integrity_events(events, question_id, now)
            return session.current_question_id, kept

    # --------------------------------------------------------------- candidates

    def create_candidate(self, payload: CandidateCreate) -> CandidateView:
        if payload.external_id and any(c.external_id == payload.external_id for c in self._candidates.values()):
            raise ValueError("external_id already exists")
        candidate = CandidateView(
            candidate_id=str(uuid.uuid4()),
            display_name=payload.display_name,
            external_id=payload.external_id,
            created_at=utcnow(),
        )
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    def get_candidate(self, candidate_id: str) -> CandidateView:
        if candidate_id not in self._candidates:
            raise CandidateNotFoundError()
        return self._candidates[candidate_id]

    def register_candidate(
        self, candidate_id: str, created_at: datetime, display_name: Optional[str] = None
    ) -> None:
        """Register a candidate created by the account layer (registration)."""
        with self._creation_guard:
            self._candidates.setdefault(
                candidate_id,
                CandidateView(
                    candidate_id=candidate_id,
                    display_name=display_name,
                    external_id=None,
                    created_at=created_at,
                ),
            )

    def _sessions_of(self, candidate_id: str) -> List[InterviewSession]:
        self.get_candidate(candidate_id)
        sessions = [s for s in self._engine.sessions() if s.candidate_id == candidate_id]
        return sorted(sessions, key=lambda s: s.created_at)

    def list_interviews(self, candidate_id: str) -> List[InterviewSummary]:
        return [_summary(s) for s in self._sessions_of(candidate_id)]

    def competency_history(self, candidate_id: str) -> List[CompetencyHistoryEntry]:
        entries: List[CompetencyHistoryEntry] = []
        for session in self._sessions_of(candidate_id):
            for record in session.answers:
                update = record["competency_update"]
                if update is None:
                    continue
                entries.append(
                    CompetencyHistoryEntry(
                        interview_id=session.interview_id,
                        competency_id=update.competency,
                        answer_id=record["answer_id"],
                        question_id=record["question_id"],
                        previous_theta=update.previous_theta,
                        new_theta=update.new_theta,
                        normalized_score=update.normalized_score,
                        questions_attempted=update.questions_attempted,
                        recorded_at=record["timing"].submitted_at,
                    )
                )
        return entries

    # ------------------------------------------------------------------ reports

    def report(self, interview_id: str) -> InterviewReport:
        from app.repositories.question_repository import question_repository

        session = self.read(interview_id)
        questions = []
        for sequence, qid in enumerate(session.asked_question_ids, start=1):
            bank = question_repository.get_by_id(qid)
            record = session.get_answer(qid)
            if qid in session.timed_out_question_ids:
                state = "timed_out"
            elif record is None:
                state = "active" if qid == session.current_question_id else "unanswered"
            else:
                state = "evaluated" if record["evaluation_status"].value == "completed" else "answered"
            questions.append(
                QuestionReport(
                    sequence=sequence,
                    question_id=qid,
                    question_text=bank.question_text if bank else None,
                    topic=bank.topic if bank else None,
                    difficulty=bank.difficulty.value if bank else None,
                    question_type=bank.question_type.value if bank else None,
                    state=state,
                    assigned_at=session.created_at,
                    closed_at=None,
                    time_limit_seconds=session.question_time_limit_seconds or 0,
                    grace_seconds=session.question_grace_seconds,
                )
            )
        answers = [
            AnswerReport(
                answer_id=r["answer_id"],
                question_id=r["question_id"],
                answer_text=r["answer_text"],
                answer_source=r["answer_source"].value,
                submission_reason=r["timing"].submission_reason.value,
                language=r.get("language"),
                submitted_at=r["timing"].submitted_at,
                elapsed_seconds=r["timing"].elapsed_seconds,
                time_limit_seconds=r["timing"].time_limit_seconds,
                grace_seconds=r["timing"].grace_seconds,
                timed_out=r["timing"].timed_out,
                evaluation_status=r["evaluation_status"],
                evaluation_attempts=r["evaluation_attempts"],
                evaluation_error=r["evaluation_error"],
                evaluator=r["evaluator"],
                evaluation=r["evaluation"],
                reasoning_summary=getattr(r["evaluation"], "reasoning_summary", None),
                competency_update=r["competency_update"],
            )
            for r in session.answers
        ]
        from app.schemas.integrity import IntegrityRecord

        records = [IntegrityRecord(**e) for e in session.integrity_log]
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

    def check_ready(self) -> None:
        return None


def _summary(session: InterviewSession) -> InterviewSummary:
    return InterviewSummary(
        interview_id=session.interview_id,
        candidate_id=session.candidate_id,
        topic=session.topic,
        difficulty=session.difficulty,
        question_count=session.question_count,
        current_question=session.current_question,
        status=session.status,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )
