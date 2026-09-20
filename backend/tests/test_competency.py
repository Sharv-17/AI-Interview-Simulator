from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.competency import EMA_ALPHA, THETA_INITIAL
from app.services.competency_state import (
    CompetencyStateStore,
    resolve_competency_id,
)

client = TestClient(app)

TOLERANCE = 1e-9


def _fake_question(competency="Python", subtopic=None, topic="Python"):
    """A minimal duck-typed stand-in for Question — these tests only
    exercise competency_state.py, which reads .competency/.subtopic/.topic."""
    return SimpleNamespace(competency=competency, subtopic=subtopic, topic=topic)


# ---------------------------------------------------------------------------
# theta initialization and the EMA formula itself
# ---------------------------------------------------------------------------


def test_new_competency_initializes_at_theta_0_5():
    store = CompetencyStateStore()
    update = store.update_from_answer(question=_fake_question(), overall_score=5.0)
    assert update.previous_theta == pytest.approx(THETA_INITIAL, abs=TOLERANCE)


def test_score_of_zero_updates_correctly():
    store = CompetencyStateStore()
    update = store.update_from_answer(question=_fake_question(), overall_score=0.0)
    expected = (1 - EMA_ALPHA) * THETA_INITIAL + EMA_ALPHA * 0.0
    assert update.new_theta == pytest.approx(expected, abs=TOLERANCE)


def test_score_of_ten_updates_correctly():
    store = CompetencyStateStore()
    update = store.update_from_answer(question=_fake_question(), overall_score=10.0)
    expected = (1 - EMA_ALPHA) * THETA_INITIAL + EMA_ALPHA * 1.0
    assert update.new_theta == pytest.approx(expected, abs=TOLERANCE)


def test_score_of_five_keeps_theta_unchanged_when_theta_already_0_5():
    store = CompetencyStateStore()
    update = store.update_from_answer(question=_fake_question(), overall_score=5.0)
    assert update.new_theta == pytest.approx(0.5, abs=TOLERANCE)


def test_score_of_eight_produces_theta_0_545():
    store = CompetencyStateStore()
    update = store.update_from_answer(question=_fake_question(), overall_score=8.0)
    assert update.new_theta == pytest.approx(0.545, abs=1e-9)


def test_multiple_answers_update_the_same_competency_sequentially():
    store = CompetencyStateStore()
    question = _fake_question()

    first = store.update_from_answer(question=question, overall_score=8.0)
    assert first.new_theta == pytest.approx(0.545, abs=1e-9)

    second = store.update_from_answer(question=question, overall_score=4.0)
    expected_second = (1 - EMA_ALPHA) * 0.545 + EMA_ALPHA * 0.4
    assert second.previous_theta == pytest.approx(0.545, abs=1e-9)
    assert second.new_theta == pytest.approx(expected_second, abs=1e-9)


# ---------------------------------------------------------------------------
# Per-competency isolation and bookkeeping
# ---------------------------------------------------------------------------


def test_different_competencies_maintain_independent_states():
    store = CompetencyStateStore()
    store.update_from_answer(question=_fake_question(competency="Python", topic="Python"), overall_score=10.0)
    store.update_from_answer(question=_fake_question(competency="SQL", topic="SQL"), overall_score=0.0)

    assert store.get("Python").theta > THETA_INITIAL
    assert store.get("SQL").theta < THETA_INITIAL


def test_questions_attempted_increments_correctly():
    store = CompetencyStateStore()
    question = _fake_question()

    store.update_from_answer(question=question, overall_score=8.0)
    store.update_from_answer(question=question, overall_score=4.0)
    update = store.update_from_answer(question=question, overall_score=6.0)

    assert update.questions_attempted == 3
    assert store.get("Python").questions_attempted == 3


def test_last_score_is_updated_correctly():
    store = CompetencyStateStore()
    question = _fake_question()

    store.update_from_answer(question=question, overall_score=8.0)
    store.update_from_answer(question=question, overall_score=4.0)

    assert store.get("Python").last_score == pytest.approx(0.4, abs=TOLERANCE)


def test_theta_never_leaves_0_1():
    store = CompetencyStateStore()
    question = _fake_question()

    for _ in range(50):
        update = store.update_from_answer(question=question, overall_score=0.0)
        assert 0.0 <= update.new_theta <= 1.0

    for _ in range(50):
        update = store.update_from_answer(question=question, overall_score=10.0)
        assert 0.0 <= update.new_theta <= 1.0


def test_question_without_competency_metadata_is_handled_safely():
    assert resolve_competency_id(_fake_question(competency="", subtopic=None, topic="")) == "unspecified"
    assert resolve_competency_id(_fake_question(competency="", subtopic=None, topic="Algorithms")) == "Algorithms"
    assert (
        resolve_competency_id(_fake_question(competency="", subtopic="Recursion", topic="Algorithms")) == "Recursion"
    )


# ---------------------------------------------------------------------------
# Integration through the real answer-submission API
# ---------------------------------------------------------------------------


def test_answer_submission_updates_competency_state():
    start_response = client.post(
        "/interview/start",
        json={"topic": "Algorithms", "difficulty": "easy", "question_count": 3},
    )
    interview = start_response.json()
    question_id = interview["current_question_id"]
    assert question_id is not None

    answer_response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": question_id,
            "answer_text": "Binary search runs in O(log n) time because it halves the search space each step.",
        },
    )

    assert answer_response.status_code == 200
    body = answer_response.json()
    assert "competency_update" in body
    update = body["competency_update"]
    assert update["previous_theta"] == pytest.approx(0.5, abs=TOLERANCE)
    assert 0.0 <= update["new_theta"] <= 1.0
    assert update["questions_attempted"] == 1


def test_competency_endpoint_reflects_answered_questions():
    start_response = client.post(
        "/interview/start",
        json={"topic": "Algorithms", "difficulty": "easy", "question_count": 3},
    )
    interview = start_response.json()
    question_id = interview["current_question_id"]

    client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": question_id, "answer_text": "A sufficiently detailed technical answer."},
    )

    competency_response = client.get(f"/interview/{interview['interview_id']}/competency")
    assert competency_response.status_code == 200
    body = competency_response.json()
    assert len(body) == 1
    (state,) = body.values()
    assert state["questions_attempted"] == 1


def test_competency_endpoint_for_unknown_interview_returns_404():
    response = client.get("/interview/does-not-exist/competency")
    assert response.status_code == 404