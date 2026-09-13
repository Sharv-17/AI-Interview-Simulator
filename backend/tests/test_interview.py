from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_still_works():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_interview_returns_interview_id():
    response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "medium", "question_count": 5},
    )
    assert response.status_code == 201
    assert "interview_id" in response.json()


def test_start_interview_returns_active_status():
    response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "easy", "question_count": 3},
    )
    assert response.json()["status"] == "active"


def test_start_interview_stores_configuration_correctly():
    response = client.post(
        "/interview/start",
        json={"topic": "SQL", "difficulty": "hard", "question_count": 8},
    )
    body = response.json()
    assert body["topic"] == "SQL"
    assert body["difficulty"] == "hard"
    assert body["question_count"] == 8
    assert body["current_question"] == 1


def test_get_interview_returns_created_interview():
    create_response = client.post(
        "/interview/start",
        json={"topic": "Go", "difficulty": "medium", "question_count": 4},
    )
    interview_id = create_response.json()["interview_id"]

    get_response = client.get(f"/interview/{interview_id}")

    assert get_response.status_code == 200
    assert get_response.json()["interview_id"] == interview_id


def test_get_interview_with_invalid_id_returns_404():
    response = client.get("/interview/does-not-exist")
    assert response.status_code == 404


def test_invalid_difficulty_is_rejected():
    response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "expert", "question_count": 5},
    )
    assert response.status_code == 422


def test_invalid_question_count_is_rejected():
    response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "medium", "question_count": 0},
    )
    assert response.status_code == 422