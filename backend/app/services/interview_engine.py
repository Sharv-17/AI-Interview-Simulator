"""Interview Engine service.

Owns interview session state. This module is the only place that knows
how sessions are stored. For this stage storage is a plain in-memory
dict; a later stage can replace it with a database-backed store without
the API layer (app/api/interview.py) needing to change, since it only
calls create_interview() / get_interview().
"""

import uuid
from typing import Dict, List, Optional, Union

from app.repositories.question_repository import question_repository
from app.schemas.evaluation import CodingEvaluation, ConceptualEvaluation
from app.schemas.interview import DifficultyLevel, InterviewResponse, InterviewStatus
from app.services.answer_evaluator import evaluate_answer
from app.services.evaluation_errors import InterviewNotActiveError, QuestionNotCurrentError
from app.services.question_selector import select_next_question


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
        self.answers: List[dict] = []

        self._select_initial_question()

    def _select_initial_question(self) -> None:
        """Pick the first question from the question bank, if one fits.

        No suitable question (e.g. an unknown topic) is not an error at
        this stage: the interview still starts, current_question_id is
        simply left as None. The selector never substitutes an
        unrelated topic, so this only happens when the bank genuinely
        has nothing for the requested topic.
        """
        question = select_next_question(
            topic=self.topic,
            difficulty=self.difficulty,
            asked_question_ids=self.asked_question_ids,
        )
        if question is not None:
            self.current_question_id = question.question_id
            self.asked_question_ids.append(question.question_id)

    def submit_answer(self, question_id: str, answer_text: str) -> Union[ConceptualEvaluation, CodingEvaluation]:
        """Evaluate a candidate's answer to this interview's current question.

        Only the interview's current question may be answered — this
        deliberately rejects both unknown question IDs and previously
        asked-but-no-longer-current ones with the same error, since
        from the interview's point of view they're the same situation:
        "not the question I'm currently asking".
        """
        if self.status != InterviewStatus.ACTIVE:
            raise InterviewNotActiveError()

        if question_id != self.current_question_id:
            raise QuestionNotCurrentError()

        question = question_repository.get_by_id(question_id)
        if question is None:
            # Shouldn't happen — current_question_id always comes from the
            # repository — but never trust stored IDs blindly.
            raise QuestionNotCurrentError()

        evaluation = evaluate_answer(question=question, answer_text=answer_text)

        self.answers.append(
            {
                "question_id": question_id,
                "answer_text": answer_text,
                "evaluation": evaluation,
            }
        )

        return evaluation

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