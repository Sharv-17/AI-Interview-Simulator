"""Interview Engine service.

Owns interview session state. This module is the only place that knows
how sessions are stored. For this stage storage is a plain in-memory
dict; a later stage can replace it with a database-backed store without
the API layer (app/api/interview.py) needing to change, since it only
calls create_interview() / get_interview().
"""

import uuid
from typing import Dict, Optional

from app.schemas.interview import DifficultyLevel, InterviewResponse, InterviewStatus


class InterviewSession:
    """In-memory representation of a single interview."""

    def __init__(self, topic: str, difficulty: DifficultyLevel, question_count: int) -> None:
        self.interview_id: str = str(uuid.uuid4())
        self.topic: str = topic
        self.difficulty: DifficultyLevel = difficulty
        self.question_count: int = question_count
        self.current_question: int = 1
        self.status: InterviewStatus = InterviewStatus.ACTIVE

    def to_response(self) -> InterviewResponse:
        """Convert internal session state into the API response shape."""
        return InterviewResponse(
            interview_id=self.interview_id,
            topic=self.topic,
            difficulty=self.difficulty,
            question_count=self.question_count,
            current_question=self.current_question,
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