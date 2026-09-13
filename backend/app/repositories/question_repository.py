"""Question bank repository.

Answers: "what questions exist?" — nothing here decides which question
to ask; that is the job of app/services/question_selector.py.

Storage is a local JSON file for this stage. A later stage can replace
this class with a PostgreSQL-backed implementation without changing any
caller, since callers only depend on the methods below.
"""

import json
from pathlib import Path
from typing import List, Optional

from pydantic import ValidationError

from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question

_DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "question_bank.json"


class QuestionRepository:
    """Loads the question bank once and serves read-only queries over it."""

    def __init__(self, data_path: Path = _DEFAULT_DATA_PATH) -> None:
        self._data_path = data_path
        self._questions: List[Question] = self._load()

    def _load(self) -> List[Question]:
        try:
            with open(self._data_path, "r", encoding="utf-8") as f:
                raw_entries = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not load question bank from {self._data_path}") from exc

        try:
            return [Question(**entry) for entry in raw_entries]
        except ValidationError as exc:
            raise RuntimeError("Question bank contains one or more invalid entries") from exc

    def get_all(self) -> List[Question]:
        """Return every question in the bank."""
        return list(self._questions)

    def get_by_id(self, question_id: str) -> Optional[Question]:
        """Return the question with this ID, or None if it doesn't exist."""
        for question in self._questions:
            if question.question_id == question_id:
                return question
        return None

    def get_by_topic(self, topic: str) -> List[Question]:
        """Return all questions for a topic (case-insensitive match)."""
        return [q for q in self._questions if q.topic.lower() == topic.lower()]

    def get_by_difficulty(self, difficulty: DifficultyLevel) -> List[Question]:
        """Return all questions at a given difficulty."""
        return [q for q in self._questions if q.difficulty == difficulty]

    def get_by_topic_and_difficulty(self, topic: str, difficulty: DifficultyLevel) -> List[Question]:
        """Return all questions matching both topic and difficulty."""
        return [
            q
            for q in self._questions
            if q.topic.lower() == topic.lower() and q.difficulty == difficulty
        ]

    def get_by_tags(self, tags: List[str]) -> List[Question]:
        """Return all questions that share at least one tag with `tags`."""
        wanted = {t.lower() for t in tags}
        return [q for q in self._questions if wanted.intersection({t.lower() for t in q.tags})]


# Single shared repository instance used by services/routers for this stage.
question_repository = QuestionRepository()