"""Interview Engine service.

Owns interview session state. This module is the only place that knows
how sessions are stored. For this stage storage is a plain in-memory
dict; a later stage can replace it with a database-backed store without
the API layer (app/api/interview.py) needing to change, since it only
calls create_interview() / get_interview().
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Union

from app.config import DEFAULT_QUESTION_TIME_LIMIT_SECONDS
from app.repositories.question_repository import question_repository
from app.schemas.competency import CompetencyUpdate
from app.schemas.evaluation import AnswerSource, CodingEvaluation, ConceptualEvaluation
from app.schemas.integrity import IntegrityEvent, SubmissionReason, TimingMetadata
from app.schemas.interview import DifficultyLevel, InterviewResponse, InterviewStatus
from app.services.answer_evaluator import evaluate_answer
from app.services.competency_state import CompetencyStateStore
from app.services.evaluation_errors import (
    AnswerAlreadySubmittedError,
    InterviewNotActiveError,
    QuestionNotAnsweredError,
    QuestionNotCurrentError,
)
from app.services.question_selector import select_next_question
from app.services.timer_service import check_timeout


class InterviewSession:
    """In-memory representation of a single interview."""

    def __init__(self, topic: str, difficulty: DifficultyLevel, question_count: int) -> None:
        self.interview_id: str = str(uuid.uuid4())
        self.topic: str = topic
        self.difficulty: DifficultyLevel = difficulty
        self.question_count: int = question_count
        self.current_question: int = 1
        self.status: InterviewStatus = InterviewStatus.ACTIVE
        self.asked_question_ids: List[str] = []
        self.current_question_id: Optional[str] = None
        self.question_started_at: Optional[datetime] = None
        self.question_time_limit_seconds: Optional[int] = None
        self.answers: List[dict] = []
        self.answered_question_ids: Set[str] = set()
        self.competency_state = CompetencyStateStore()

        self._select_initial_question()

    def _select_initial_question(self) -> None:
        """Pick the first question from the question bank, if one fits.

        No suitable question (e.g. an unknown topic) is not an error at
        this stage: the interview still starts, current_question_id is
        simply left as None. The selector never substitutes an
        unrelated topic, so this only happens when the bank genuinely
        has nothing for the requested topic.

        When a question is selected, its timer starts immediately:
        question_started_at is recorded once here and is never reset,
        including by later answer submissions (see submit_answer).
        """
        question = select_next_question(
            topic=self.topic,
            difficulty=self.difficulty,
            asked_question_ids=self.asked_question_ids,
        )
        if question is not None:
            self._set_current_question(question.question_id)

    def _set_current_question(self, question_id: str) -> None:
        """Make a question current and start its timer (recorded once, never reset)."""
        self.current_question_id = question_id
        self.asked_question_ids.append(question_id)
        self.question_started_at = datetime.now(timezone.utc)
        self.question_time_limit_seconds = DEFAULT_QUESTION_TIME_LIMIT_SECONDS

    def ensure_accepting_answer(self, question_id: str) -> None:
        """Raise unless `question_id` is the active, still-unanswered current question.

        Shared by answer submission and audio transcription so a recording can
        only ever be attributed to the question the interview is asking now.
        """
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()

        if question_id != self.current_question_id:
            raise QuestionNotCurrentError()

        if question_id in self.answered_question_ids:
            raise AnswerAlreadySubmittedError()

    def advance_to_next_question(self) -> None:
        """Move to the next question, or complete the interview.

        The current question must be answered first. The next question is
        chosen by app/services/question_selector.py, which ranks eligible
        questions by QScore using this interview's competency state (the
        requested difficulty only decides the first question). The interview
        completes when question_count questions have been answered, or earlier
        if the bank has no unasked question left for the topic.
        """
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()

        if self.current_question_id is None or self.current_question_id not in self.answered_question_ids:
            raise QuestionNotAnsweredError()

        if self.current_question >= self.question_count:
            self._complete()
            return

        next_question = select_next_question(
            topic=self.topic,
            difficulty=self.difficulty,
            asked_question_ids=self.asked_question_ids,
            competency_states=self.competency_state.get_all(),
        )
        if next_question is None:
            self._complete()
            return

        self.current_question += 1
        self._set_current_question(next_question.question_id)

    def _complete(self) -> None:
        self.status = InterviewStatus.COMPLETED
        self.current_question_id = None
        self.question_started_at = None
        self.question_time_limit_seconds = None

    def submit_answer(
        self,
        question_id: str,
        answer_text: str,
        submission_reason: SubmissionReason = SubmissionReason.CANDIDATE_SUBMITTED,
        integrity_events: Optional[List[IntegrityEvent]] = None,
        answer_source: AnswerSource = AnswerSource.TEXT,
    ) -> Tuple[Union[ConceptualEvaluation, CodingEvaluation], CompetencyUpdate, TimingMetadata]:
        """Evaluate a candidate's answer to this interview's current question.

        Only the interview's current question may be answered — this
        deliberately rejects both unknown question IDs and previously
        asked-but-no-longer-current ones with the same error, since
        from the interview's point of view they're the same situation:
        "not the question I'm currently asking".

        Timing: timed_out is computed server-side from
        question_started_at (set once, never reset) — never from the
        client's submission_reason, which is recorded as metadata only.
        A late submission is still evaluated and stored normally; it is
        simply flagged timed_out=True for later audit rather than
        rejected outright, since this stage does not implement
        automatic question progression.

        Each question can be answered only once: a second submission raises
        AnswerAlreadySubmittedError, so evaluation and the competency update
        happen exactly once per question. answer_source ("text" | "voice") is
        client-reported metadata stored with the answer; it never changes
        evaluation or scoring.

        Integrity events (copy/paste) are stored as reported, verbatim,
        alongside the timing metadata. They never affect whether the
        answer is accepted, evaluated, or scored.

        After evaluation, the answer's overall_score also updates this
        interview's estimated competency state for the question's
        competency (see app/services/competency_state.py). This is a
        separate concept from the evaluation itself: evaluation asks
        "what quality was this answer?"; competency state asks "what
        does this suggest about the candidate's estimated ability?" —
        neither the timing nor the competency update ever changes the
        evaluation's score.
        """
        self.ensure_accepting_answer(question_id)

        question = question_repository.get_by_id(question_id)
        if question is None:
            # Shouldn't happen — current_question_id always comes from the
            # repository — but never trust stored IDs blindly.
            raise QuestionNotCurrentError()

        submitted_at = datetime.now(timezone.utc)
        timed_out, elapsed = check_timeout(
            question_started_at=self.question_started_at,
            time_limit_seconds=self.question_time_limit_seconds,
            at=submitted_at,
        )
        timing = TimingMetadata(
            question_started_at=self.question_started_at,
            submitted_at=submitted_at,
            time_limit_seconds=self.question_time_limit_seconds,
            elapsed_seconds=elapsed,
            timed_out=timed_out,
            submission_reason=submission_reason,
            integrity_events=integrity_events or [],
        )

        evaluation = evaluate_answer(question=question, answer_text=answer_text)
        competency_update = self.competency_state.update_from_answer(
            question=question, overall_score=evaluation.overall_score
        )

        self.answers.append(
            {
                "question_id": question_id,
                "answer_text": answer_text,
                "answer_source": answer_source,
                "evaluation": evaluation,
                "competency_update": competency_update,
                "timing": timing,
            }
        )
        # Marked only after a successful evaluation, so a failed evaluation
        # (e.g. 502) can be retried, while a completed one can never be repeated.
        self.answered_question_ids.add(question_id)

        return evaluation, competency_update, timing

    def to_response(self) -> InterviewResponse:
        """Convert internal session state into the API response shape."""
        return InterviewResponse(
            interview_id=self.interview_id,
            topic=self.topic,
            difficulty=self.difficulty,
            question_count=self.question_count,
            current_question=self.current_question,
            current_question_id=self.current_question_id,
            status=self.status,
        )


class InterviewEngine:
    """Creates and retrieves interview sessions.

    Storage is in-memory and intentionally simple for this stage. The
    session data disappears on server restart - that is expected.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, InterviewSession] = {}

    def create_interview(
        self, topic: str, difficulty: DifficultyLevel, question_count: int
    ) -> InterviewSession:
        """Create a new interview session and store it."""
        session = InterviewSession(topic=topic, difficulty=difficulty, question_count=question_count)
        self._sessions[session.interview_id] = session
        return session

    def get_interview(self, interview_id: str) -> Optional[InterviewSession]:
        """Return the session for interview_id, or None if it doesn't exist."""
        return self._sessions.get(interview_id)


# Single shared engine instance used by the API layer for this stage.
interview_engine = InterviewEngine()