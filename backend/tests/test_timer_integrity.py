from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_QUESTION_TIME_LIMIT_SECONDS
from app.main import app
from app.services.interview_engine import interview_engine
from app.services.timer_service import check_timeout

client = TestClient(app)


def _start_algorithms_interview():
    response = client.post(
        "/interview/start",
        json={"topic": "Algorithms", "difficulty": "easy", "question_count": 3},
    )
    interview = response.json()
    assert interview["current_question_id"] is not None
    return interview


# ---------------------------------------------------------------------------
# Timer basics
# ---------------------------------------------------------------------------


def test_default_time_limit_is_90_seconds():
    assert DEFAULT_QUESTION_TIME_LIMIT_SECONDS == 90

    interview = _start_algorithms_interview()
    session = interview_engine.get_interview(interview["interview_id"])
    assert session.question_time_limit_seconds == 90


def test_question_start_time_is_recorded_correctly():
    before = datetime.now(timezone.utc)
    interview = _start_algorithms_interview()
    after = datetime.now(timezone.utc)

    session = interview_engine.get_interview(interview["interview_id"])
    assert session.question_started_at is not None
    assert before <= session.question_started_at <= after


def test_question_within_time_limit_is_accepted():
    started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    timed_out, elapsed = check_timeout(question_started_at=started_at, time_limit_seconds=90)
    assert timed_out is False
    assert elapsed == pytest.approx(30, abs=1)


def test_question_beyond_time_limit_is_detected():
    started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    timed_out, elapsed = check_timeout(question_started_at=started_at, time_limit_seconds=90)
    assert timed_out is True
    assert elapsed == pytest.approx(120, abs=1)


# ---------------------------------------------------------------------------
# Timeout metadata via the real answer-submission API
# ---------------------------------------------------------------------------


def test_timeout_metadata_is_stored_correctly():
    interview = _start_algorithms_interview()
    session = interview_engine.get_interview(interview["interview_id"])
    # Simulate the question having started 120s ago -- no real waiting.
    session.question_started_at = datetime.now(timezone.utc) - timedelta(seconds=120)

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
            "submission_reason": "timeout",
        },
    )

    assert response.status_code == 200
    timing = response.json()["timing"]
    assert timing["timed_out"] is True
    assert timing["elapsed_seconds"] >= 90
    assert timing["submission_reason"] == "timeout"
    assert timing["time_limit_seconds"] == 90


def test_timer_is_not_reset_by_resubmitting():
    """A candidate cannot extend their time by submitting more than once.

    Since Stage 3.8 a second submission for the same question is rejected (409),
    and in every case question_started_at is set once and never reset.
    """
    interview = _start_algorithms_interview()
    session = interview_engine.get_interview(interview["interview_id"])
    original_start = session.question_started_at

    first_response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "First submission."},
    )
    assert first_response.status_code == 200
    assert session.question_started_at == original_start

    second_response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "Second submission."},
    )
    assert second_response.status_code == 409
    assert session.question_started_at == original_start


# ---------------------------------------------------------------------------
# submission_reason validation
# ---------------------------------------------------------------------------


def test_submission_reason_is_validated():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
            "submission_reason": "candidate_submitted",
        },
    )
    assert response.status_code == 200
    assert response.json()["timing"]["submission_reason"] == "candidate_submitted"


def test_invalid_submission_reason_is_rejected():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
            "submission_reason": "because_i_felt_like_it",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Copy/paste integrity events
# ---------------------------------------------------------------------------


def test_copy_event_is_accepted():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
            "integrity_events": [{"event_type": "copy"}],
        },
    )
    assert response.status_code == 200
    events = response.json()["timing"]["integrity_events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "copy"


def test_paste_event_is_accepted():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
            "integrity_events": [{"event_type": "paste", "source": "answer_box"}],
        },
    )
    assert response.status_code == 200
    events = response.json()["timing"]["integrity_events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "paste"
    assert events[0]["source"] == "answer_box"


def test_invalid_integrity_event_type_is_rejected():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
            "integrity_events": [{"event_type": "screenshot"}],
        },
    )
    assert response.status_code == 422


def test_integrity_events_are_associated_with_the_correct_question():
    interview = _start_algorithms_interview()
    question_id = interview["current_question_id"]

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": question_id,
            "answer_text": "A sufficiently detailed technical answer.",
            "integrity_events": [{"event_type": "copy"}, {"event_type": "paste"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interview_id"] == interview["interview_id"]
    assert body["question_id"] == question_id
    assert len(body["timing"]["integrity_events"]) == 2


def test_copy_paste_events_do_not_automatically_flag_cheating():
    """Presence of copy/paste events must never block or alter evaluation."""
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "Binary search runs in O(log n) time because it halves the search space each step.",
            "integrity_events": [{"event_type": "copy"}, {"event_type": "paste"}, {"event_type": "copy"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    # No "cheating" flag anywhere; evaluation and competency proceed normally.
    assert "evaluation" in body
    assert "competency_update" in body
    assert 0 <= body["evaluation"]["overall_score"] <= 10


# ---------------------------------------------------------------------------
# Timing metadata is genuinely persisted with the answer
# ---------------------------------------------------------------------------


def test_timing_metadata_is_preserved_with_the_answer():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
        },
    )
    assert response.status_code == 200

    session = interview_engine.get_interview(interview["interview_id"])
    assert len(session.answers) == 1
    stored_timing = session.answers[0]["timing"]
    assert stored_timing.submission_reason.value == "candidate_submitted"
    assert stored_timing.timed_out is False


# ---------------------------------------------------------------------------
# Regression: Stage 3.4/3.5 behavior and error handling untouched
# ---------------------------------------------------------------------------


def test_existing_conceptual_evaluation_still_works():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "Binary search runs in O(log n) time because it halves the search space each step.",
        },
    )
    assert response.status_code == 200
    assert response.json()["evaluation"]["question_type"] == "conceptual"


def test_competency_state_is_still_updated_correctly():
    interview = _start_algorithms_interview()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": "A sufficiently detailed technical answer.",
        },
    )
    assert response.status_code == 200
    update = response.json()["competency_update"]
    assert update["previous_theta"] == pytest.approx(0.5, abs=1e-9)
    assert update["questions_attempted"] == 1


def test_unknown_interview_is_handled_correctly():
    response = client.post(
        "/interview/does-not-exist/answer",
        json={"question_id": "sample-001", "answer_text": "Some answer."},
    )
    assert response.status_code == 404


def test_inactive_interview_is_handled_correctly():
    from app.schemas.interview import InterviewStatus

    interview = _start_algorithms_interview()
    session = interview_engine.get_interview(interview["interview_id"])
    session.status = InterviewStatus.COMPLETED

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "Some answer."},
    )
    assert response.status_code == 409


def test_health_still_works():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}