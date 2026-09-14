from fastapi.testclient import TestClient

from app.main import app
from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.services.question_selector import select_next_question

client = TestClient(app)


def test_question_bank_loads_successfully():
    questions = question_repository.get_all()
    assert len(questions) > 0


def test_question_bank_size_matches_csv_row_count():
    import csv
    from pathlib import Path

    csv_path = Path(__file__).resolve().parent.parent / "data" / "question_bank.csv"
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        row_count = sum(1 for _ in csv.DictReader(f))

    assert len(question_repository.get_all()) == row_count


def test_questions_can_be_retrieved():
    questions = question_repository.get_all()
    assert all(q.question_id and q.question_text for q in questions)


def test_topic_filtering_works():
    questions = question_repository.get_by_topic("Algorithms")
    assert len(questions) > 0
    assert all(q.topic == "Algorithms" for q in questions)


def test_difficulty_filtering_works():
    questions = question_repository.get_by_difficulty(DifficultyLevel.EASY)
    assert len(questions) > 0
    assert all(q.difficulty == DifficultyLevel.EASY for q in questions)


def test_topic_and_difficulty_filtering_works():
    questions = question_repository.get_by_topic_and_difficulty("Data Structures", DifficultyLevel.MEDIUM)
    assert len(questions) > 0
    assert all(q.topic == "Data Structures" and q.difficulty == DifficultyLevel.MEDIUM for q in questions)


def test_a_valid_question_can_be_selected():
    question = select_next_question(topic="Security", difficulty=DifficultyLevel.MEDIUM)
    assert question is not None


def test_selected_question_belongs_to_requested_topic():
    question = select_next_question(topic="Database and SQL", difficulty=DifficultyLevel.EASY)
    assert question is not None
    assert question.topic == "Database and SQL"


def test_selected_question_has_requested_difficulty_when_available():
    question = select_next_question(topic="System Design", difficulty=DifficultyLevel.HARD)
    assert question is not None
    assert question.difficulty == DifficultyLevel.HARD


def test_previously_asked_questions_are_not_selected_again():
    first = select_next_question(topic="Algorithms", difficulty=DifficultyLevel.HARD)
    second = select_next_question(
        topic="Algorithms",
        difficulty=DifficultyLevel.HARD,
        asked_question_ids=[first.question_id],
    )
    assert second is not None
    assert second.question_id != first.question_id


def test_missing_topic_returns_none_instead_of_an_unrelated_question():
    question = select_next_question(topic="Quantum Computing", difficulty=DifficultyLevel.EASY)
    assert question is None


def test_questions_api_filters_by_topic():
    response = client.get("/questions", params={"topic": "Data Structures"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    assert all(q["topic"] == "Data Structures" for q in body)


def test_questions_api_filters_by_topic_and_difficulty():
    response = client.get("/questions", params={"topic": "Security", "difficulty": "medium"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    assert all(q["topic"] == "Security" and q["difficulty"] == "medium" for q in body)


def test_interview_start_assigns_a_question_when_topic_matches():
    response = client.post(
        "/interview/start",
        json={"topic": "Algorithms", "difficulty": "easy", "question_count": 3},
    )
    assert response.status_code == 201
    assert response.json()["current_question_id"] is not None


def test_interview_start_handles_unknown_topic_without_error():
    response = client.post(
        "/interview/start",
        json={"topic": "Quantum Computing", "difficulty": "easy", "question_count": 3},
    )
    assert response.status_code == 201
    assert response.json()["current_question_id"] is None