
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services import interview_engine as engine_module
from app.services.interview_engine import interview_engine

client = TestClient(app)


def _start(question_count=3, topic="Algorithms", difficulty="easy"):
    response = client.post(
        "/interview/start",
        json={"topic": topic, "difficulty": difficulty, "question_count": question_count},
    )
    interview = response.json()
    assert interview["current_question_id"] is not None
    return interview


def _answer(interview_id, question_id, text="A reasonably detailed technical answer."):
    return client.post(
        f"/interview/{interview_id}/answer",
        json={"question_id": question_id, "answer_text": text},
    )


def _next(interview_id):
    return client.post(f"/interview/{interview_id}/next")


# ---------------------------------------------------------------------------
# GET /questions/{id}
# ---------------------------------------------------------------------------


def test_question_endpoint_returns_text_without_the_answer_key():
    interview = _start()
    response = client.get(f"/questions/{interview['current_question_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["question_id"] == interview["current_question_id"]
    assert body["question_text"]
    assert "reference_answer" not in body


def test_question_endpoint_unknown_id_returns_404():
    assert client.get("/questions/does-not-exist").status_code == 404


def test_question_list_endpoint_still_works():
    assert client.get("/questions", params={"topic": "Algorithms"}).status_code == 200


# ---------------------------------------------------------------------------
# POST /interview/{id}/next
# ---------------------------------------------------------------------------


def test_next_requires_the_current_question_to_be_answered():
    interview = _start()
    response = _next(interview["interview_id"])
    assert response.status_code == 409
    session = interview_engine.get_interview(interview["interview_id"])
    assert session.current_question_id == interview["current_question_id"]
    assert session.current_question == 1


def test_next_advances_to_a_new_question_and_restarts_the_timer():
    interview = _start()
    iid, first_id = interview["interview_id"], interview["current_question_id"]
    assert _answer(iid, first_id).status_code == 200

    session = interview_engine.get_interview(iid)
    stale = datetime.now(timezone.utc) - timedelta(seconds=100)
    session.question_started_at = stale

    response = _next(iid)
    assert response.status_code == 200
    body = response.json()
    assert body["current_question"] == 2
    assert body["current_question_id"] not in (None, first_id)
    assert body["status"] == "active"
    # The new question has its own, fresh timer.
    assert session.question_started_at > stale
    assert session.question_time_limit_seconds == 90


def test_answer_after_advancing_applies_to_the_new_question_and_updates_competency_again():
    interview = _start()
    iid = interview["interview_id"]
    _answer(iid, interview["current_question_id"])
    second_id = _next(iid).json()["current_question_id"]

    response = _answer(iid, second_id)
    assert response.status_code == 200
    assert response.json()["competency_update"]["questions_attempted"] == 2


def test_previous_question_cannot_be_answered_after_advancing():
    interview = _start()
    iid, first_id = interview["interview_id"], interview["current_question_id"]
    _answer(iid, first_id)
    _next(iid)
    assert _answer(iid, first_id).status_code == 400


def test_questions_are_not_repeated_during_one_interview():
    interview = _start(question_count=5)
    iid = interview["interview_id"]
    seen = [interview["current_question_id"]]
    for _ in range(4):
        _answer(iid, seen[-1])
        seen.append(_next(iid).json()["current_question_id"])
    assert len(set(seen)) == 5


def test_next_on_unknown_interview_returns_404():
    assert _next("does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def test_interview_completes_after_question_count_answers():
    interview = _start(question_count=2)
    iid = interview["interview_id"]
    _answer(iid, interview["current_question_id"])
    second_id = _next(iid).json()["current_question_id"]
    _answer(iid, second_id)

    done = _next(iid)
    assert done.status_code == 200
    assert done.json()["status"] == "completed"
    assert done.json()["current_question_id"] is None
    assert done.json()["current_question"] == 2

    # Nothing further is accepted, and completion is stable.
    assert _answer(iid, second_id).status_code == 409
    assert _next(iid).status_code == 409
    assert client.get(f"/interview/{iid}").json()["status"] == "completed"
    # Competency from the interview remains readable after completion.
    assert client.get(f"/interview/{iid}/competency").status_code == 200


def test_interview_completes_early_when_the_question_pool_is_exhausted(monkeypatch):
    interview = _start(question_count=5)
    iid = interview["interview_id"]
    _answer(iid, interview["current_question_id"])
    monkeypatch.setattr(engine_module, "select_next_question", lambda **kwargs: None)

    done = _next(iid)
    assert done.status_code == 200
    assert done.json()["status"] == "completed"
    assert done.json()["current_question"] == 1


def test_single_question_interview_completes_on_first_next():
    interview = _start(question_count=1)
    iid = interview["interview_id"]
    _answer(iid, interview["current_question_id"])
    assert _next(iid).json()["status"] == "completed"


def test_interview_with_no_matching_questions_cannot_be_advanced():
    interview = client.post(
        "/interview/start",
        json={"topic": "Quantum Computing", "difficulty": "easy", "question_count": 3},
    ).json()
    assert interview["current_question_id"] is None
    assert _next(interview["interview_id"]).status_code == 409