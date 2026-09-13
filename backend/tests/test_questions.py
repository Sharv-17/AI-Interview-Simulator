from fastapi.testclient import TestClient

from app.main import app
from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.services.question_selector import select_next_question

client = TestClient(app)


def test_question_bank_loads_successfully():
    questions = question_repository.get_all()
    assert len(questions) > 0


def test_questions_can_be_retrieved():
    questions = question_repository.get_all()
    assert all(q.question_id and q.question_text for q in questions)


def test_topic_filtering_works():
    questions = question_repository.get_by_topic("Python")
    assert len(questions) > 0
    assert all(q.topic == "Python" for q in questions)


def test_difficulty_filtering_works():
    questions = question_repository.get_by_difficulty(DifficultyLevel.EASY)
    assert len(questions) > 0
    assert all(q.difficulty == DifficultyLevel.EASY for q in questions)


def test_topic_and_difficulty_filtering_works():
    questions = question_repository.get_by_topic_and_difficulty("Python", DifficultyLevel.MEDIUM)
    assert len(questions) > 0
    assert all(q.topic == "Python" and q.difficulty == DifficultyLevel.MEDIUM for q in questions)


def test_a_valid_question_can_be_selected():
    question = select_next_question(topic="Python", difficulty=DifficultyLevel.MEDIUM)
    assert question is not None


def test_selected_question_belongs_to_requested_topic():
    question = select_next_question(topic="SQL", difficulty=DifficultyLevel.EASY)
    assert question is not None
    assert question.topic == "SQL"


def test_selected_question_has_requested_difficulty_when_available():
    question = select_next_question(topic="Algorithms", difficulty=DifficultyLevel.HARD)
    assert question is not None
    assert question.difficulty == DifficultyLevel.HARD


def test_previously_asked_questions_are_not_selected_again():
    first = select_next_question(topic="Python", difficulty=DifficultyLevel.EASY)
    second = select_next_question(
        topic="Python",
        difficulty=DifficultyLevel.EASY,
        asked_question_ids=[first.question_id],
    )
    assert second is not None
    assert second.question_id != first.question_id


def test_missing_topic_returns_none_instead_of_an_unrelated_question():
    question = select_next_question(topic="Rust", difficulty=DifficultyLevel.EASY)
    assert question is None


def test_questions_api_filters_by_topic():
    response = client.get("/questions", params={"topic": "OOP"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    assert all(q["topic"] == "OOP" for q in body)


def test_questions_api_filters_by_topic_and_difficulty():
    response = client.get("/questions", params={"topic": "SQL", "difficulty": "medium"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    assert all(q["topic"] == "SQL" and q["difficulty"] == "medium" for q in body)


def test_interview_start_assigns_a_question_when_topic_matches():
    response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "easy", "question_count": 3},
    )
    assert response.status_code == 201
    assert response.json()["current_question_id"] is not None


def test_interview_start_handles_unknown_topic_without_error():
    response = client.post(
        "/interview/start",
        json={"topic": "Rust", "difficulty": "easy", "question_count": 3},
    )
    assert response.status_code == 201
    assert response.json()["current_question_id"] is None