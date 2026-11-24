"""Phase 4 tests: question-aware deadlines and integrity indicators."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel, InterviewStatus
from app.schemas.question import Question, QuestionType
from app.services.evaluation_errors import (
    AnswerAlreadySubmittedError,
    QuestionDeadlinePassedError,
)
from app.services.interview_engine import InterviewSession, interview_engine

client = TestClient(app)
ANSWER = "A reasonably detailed technical answer that is long enough to count."
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
GRACE = 15


def _start(count=3):
    interview = client.post(
        "/interview/start", json={"topic": "Algorithms", "difficulty": "easy", "question_count": count}
    ).json()
    assert interview["current_question_id"]
    return interview


def _session(interview):
    return interview_engine.get_interview(interview["interview_id"])


def _age(interview, seconds):
    """Pretend the current question started `seconds` ago (no real waiting)."""
    _session(interview).question_started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _answer(interview, text=ANSWER, **extra):
    return client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": text, **extra},
    )


def _events(interview):
    return client.get(f"/interview/{interview['interview_id']}/report").json()["integrity_events"]


def _post_events(interview, events, **extra):
    return client.post(f"/interview/{interview['interview_id']}/integrity-events", json={"events": events, **extra})


def _limit(interview):
    return _session(interview).question_time_limit_seconds


# ---------------------------------------------------------------------------
# Deadline fields for the frontend
# ---------------------------------------------------------------------------


def test_interview_state_exposes_limit_grace_deadline_and_countdown():
    interview = _start()
    state = client.get(f"/interview/{interview['interview_id']}").json()
    question = question_repository.get_by_id(interview["current_question_id"])

    assert state["question_time_limit_seconds"] == question.estimated_time_seconds
    assert state["grace_seconds"] == GRACE
    started = datetime.fromisoformat(state["question_started_at"])
    deadline = datetime.fromisoformat(state["deadline_at"])
    assert (deadline - started).total_seconds() == question.estimated_time_seconds + GRACE
    assert question.estimated_time_seconds - 5 <= state["seconds_remaining"] <= question.estimated_time_seconds
    assert (state["question_state"], state["next_action"]) == ("active", "answer")


def test_seconds_remaining_never_goes_negative_and_next_action_becomes_advance():
    interview = _start()
    _age(interview, _limit(interview) + GRACE + 30)
    state = client.get(f"/interview/{interview['interview_id']}").json()
    assert state["seconds_remaining"] == 0.0 and state["next_action"] == "advance"


# ---------------------------------------------------------------------------
# Deadline enforcement (exact boundaries, fixed clock)
# ---------------------------------------------------------------------------


def _domain_session(**kwargs):
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    session = InterviewSession("Algorithms", DifficultyLevel.EASY, 3, now=t0, **kwargs)
    return session, t0


def test_an_answer_exactly_at_the_deadline_is_accepted_and_one_instant_later_is_rejected():
    session, t0 = _domain_session()
    limit, grace = session.question_time_limit_seconds, session.question_grace_seconds
    at_deadline = t0 + timedelta(seconds=limit + grace)

    record = session.record_answer(session.current_question_id, "answer", now=at_deadline)
    assert record["timing"].timed_out is True  # used the grace period

    late_session, t0 = _domain_session()
    with pytest.raises(QuestionDeadlinePassedError):
        late_session.record_answer(
            late_session.current_question_id, "answer", now=t0 + timedelta(seconds=limit + grace, microseconds=1)
        )
    assert late_session.answers == []


def test_an_answer_within_the_nominal_limit_is_not_flagged():
    session, t0 = _domain_session()
    record = session.record_answer(
        session.current_question_id, "answer", now=t0 + timedelta(seconds=session.question_time_limit_seconds)
    )
    assert record["timing"].timed_out is False and record["timing"].elapsed_seconds == session.question_time_limit_seconds


def test_the_grace_period_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "ANSWER_GRACE_SECONDS", 0)
    session, t0 = _domain_session()
    assert session.question_grace_seconds == 0
    with pytest.raises(QuestionDeadlinePassedError):
        session.record_answer(
            session.current_question_id, "a", now=t0 + timedelta(seconds=session.question_time_limit_seconds + 1)
        )


def test_a_question_without_an_estimate_falls_back_to_the_default_limit():
    session, t0 = _domain_session()
    bare = Question(
        question_id="X-1", question_text="Q?", topic="Algorithms", difficulty=DifficultyLevel.EASY,
        question_type=QuestionType.CONCEPTUAL, competency="Algorithms",
    )
    session._set_current_question(bare, t0)
    assert session.question_time_limit_seconds == config.DEFAULT_QUESTION_TIME_LIMIT_SECONDS == 90


def test_a_late_answer_is_rejected_marks_the_question_timed_out_and_never_updates_competency():
    interview = _start()
    _age(interview, _limit(interview) + GRACE + 5)
    response = _answer(interview)

    assert response.status_code == 409 and response.json()["detail"]["code"] == "question_deadline_passed"
    session = _session(interview)
    assert session.answers == [] and session.competency_state.get_all() == {}
    state = client.get(f"/interview/{interview['interview_id']}").json()
    assert (state["question_state"], state["next_action"]) == ("timed_out", "advance")
    late = [e for e in _events(interview) if e["event_type"] == "late_submission_rejected"]
    assert len(late) == 1 and late[0]["source"] == "server" and late[0]["detail"]["elapsed_seconds"] > _limit(interview)


def test_repeated_late_attempts_stay_rejected_and_do_not_flood_the_log():
    interview = _start()
    _age(interview, _limit(interview) + GRACE + 5)
    assert [_answer(interview).status_code for _ in range(4)] == [409] * 4
    assert len([e for e in _events(interview) if e["event_type"] == "late_submission_rejected"]) == 1


def test_a_timed_out_question_can_be_skipped_and_the_next_one_gets_a_fresh_timer():
    interview = _start()
    _age(interview, _limit(interview) + GRACE + 5)
    assert _answer(interview).status_code == 409

    moved = client.post(f"/interview/{interview['interview_id']}/next")
    assert moved.status_code == 200 and moved.json()["current_question"] == 2
    assert moved.json()["current_question_id"] != interview["current_question_id"]
    assert moved.json()["seconds_remaining"] > moved.json()["question_time_limit_seconds"] - 5
    assert _session(interview).competency_state.get_all() == {}


def test_next_without_an_answer_is_refused_before_the_deadline_and_allowed_after_it():
    interview = _start()
    assert client.post(f"/interview/{interview['interview_id']}/next").status_code == 409
    assert _session(interview).current_question == 1

    _age(interview, _limit(interview) + GRACE + 5)
    assert client.post(f"/interview/{interview['interview_id']}/next").status_code == 200
    report = client.get(f"/interview/{interview['interview_id']}/report").json()
    assert [q["state"] for q in report["questions"]][:1] == ["timed_out"]


def test_timing_out_the_last_question_lets_the_interview_complete():
    interview = _start(count=1)
    _age(interview, _limit(interview) + GRACE + 5)
    done = client.post(f"/interview/{interview['interview_id']}/next")
    assert done.status_code == 200 and done.json()["status"] == "completed"


def test_audio_is_refused_after_the_deadline_because_recording_time_counts():
    interview = _start()
    _age(interview, _limit(interview) + GRACE + 5)
    response = client.post(
        f"/interview/{interview['interview_id']}/transcribe",
        data={"question_id": interview["current_question_id"]},
        files={"audio": ("a.webm", WEBM, "audio/webm")},
    )
    assert response.status_code == 409 and response.json()["detail"]["code"] == "question_deadline_passed"


def test_the_client_cannot_claim_its_way_past_the_deadline():
    interview = _start()
    _age(interview, _limit(interview) + GRACE + 5)
    assert _answer(interview, submission_reason="candidate_submitted").status_code == 409
    assert _answer(interview, submission_reason="timeout").status_code == 409


def test_a_client_claiming_timeout_early_does_not_make_the_server_flag_it():
    interview = _start()
    timing = _answer(interview, submission_reason="timeout").json()["timing"]
    assert timing["timed_out"] is False and timing["submission_reason"] == "timeout"


def test_client_clocks_and_repeated_reads_never_move_the_servers_timer():
    interview = _start()
    started = _session(interview).question_started_at
    _post_events(interview, [{"event_type": "tab_switch", "occurred_at": "1999-01-01T00:00:00Z"}])
    client.get(f"/interview/{interview['interview_id']}")
    assert _session(interview).question_started_at == started

    answer = _answer(interview, integrity_events=[{"event_type": "copy", "occurred_at": "2999-01-01T00:00:00Z"}])
    assert answer.status_code == 200
    assert 0 <= answer.json()["timing"]["elapsed_seconds"] < 5  # the server's clock, not the client's


# ---------------------------------------------------------------------------
# Client integrity events
# ---------------------------------------------------------------------------


def test_tab_switch_focus_and_copy_paste_events_are_recorded_for_the_current_question():
    interview = _start()
    response = _post_events(
        interview,
        [
            {"event_type": "tab_switch", "duration_ms": 4200, "source": "visibilitychange"},
            {"event_type": "focus_loss", "duration_ms": 900},
            {"event_type": "focus_gain"},
            {"event_type": "paste", "source": "answer_box"},
        ],
    )
    assert response.status_code == 200
    assert response.json() == {
        "interview_id": interview["interview_id"],
        "question_id": interview["current_question_id"],
        "recorded": 4,
    }
    stored = _events(interview)
    assert [e["event_type"] for e in stored] == ["tab_switch", "focus_loss", "focus_gain", "paste"]
    assert all(e["source"] == "client" and e["question_id"] == interview["current_question_id"] for e in stored)
    assert stored[0]["duration_ms"] == 4200 and stored[0]["received_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {"events": []},
        {"events": [{"event_type": "fast_submission"}]},  # server-only indicator: clients may not report it
        {"events": [{"event_type": "late_submission_rejected"}]},
        {"events": [{"event_type": "screenshot"}]},
        {"events": [{"event_type": "copy", "duration_ms": -1}]},
        {"events": [{"event_type": "copy", "duration_ms": 86_400_001}]},
        {"events": [{"event_type": "copy"}] * 51},
        {"events": [{"event_type": "copy", "occurred_at": "not-a-date"}]},
        {"events": [{"event_type": "copy", "source": "x" * 65}]},
        {"events": "copy"},
    ],
)
def test_invalid_integrity_events_are_rejected(payload):
    interview = _start()
    assert client.post(f"/interview/{interview['interview_id']}/integrity-events", json=payload).status_code == 422
    assert _events(interview) == []


def test_arbitrary_metadata_is_never_stored():
    interview = _start()
    _post_events(interview, [{"event_type": "copy", "metadata": {"clipboard": "SECRET TEXT"}, "text": "SECRET TEXT"}])
    assert "SECRET TEXT" not in client.get(f"/interview/{interview['interview_id']}/report").text


def test_events_for_another_question_are_refused():
    interview = _start()
    response = _post_events(interview, [{"event_type": "copy"}], question_id="SWQ-9999")
    assert response.status_code == 400 and _events(interview) == []


def test_the_per_interview_event_cap_drops_the_excess(monkeypatch):
    monkeypatch.setattr(config, "MAX_INTEGRITY_EVENTS_PER_INTERVIEW", 3)
    interview = _start()
    response = _post_events(interview, [{"event_type": "copy"}] * 5)
    assert response.json()["recorded"] == 3 and len(_events(interview)) == 3


def test_integrity_events_never_change_scoring_or_block_an_answer():
    plain = _answer(_start()).json()
    flagged_interview = _start()
    _post_events(flagged_interview, [{"event_type": "tab_switch"}] * 5 + [{"event_type": "paste"}] * 5)
    flagged = _answer(
        flagged_interview, integrity_events=[{"event_type": "copy"}, {"event_type": "focus_loss", "duration_ms": 9000}]
    ).json()
    assert flagged["evaluation"]["overall_score"] == plain["evaluation"]["overall_score"]
    assert flagged["competency_update"]["new_theta"] == plain["competency_update"]["new_theta"]
    assert len(flagged["timing"]["integrity_events"]) == 2


# ---------------------------------------------------------------------------
# Server-side indicators (never used for scoring)
# ---------------------------------------------------------------------------


def test_duplicate_and_unassigned_attempts_are_logged_as_indicators_without_changing_state():
    interview = _start()
    assert _answer(interview).status_code == 200
    assert _answer(interview).status_code == 409
    wrong = client.post(
        f"/interview/{interview['interview_id']}/answer", json={"question_id": "SWQ-9999", "answer_text": "x"}
    )
    assert wrong.status_code == 400
    types = [e["event_type"] for e in _events(interview)]
    assert "duplicate_submission" in types and "unassigned_question_attempt" in types
    assert len(_session(interview).answers) == 1


def test_implausibly_fast_typed_answers_are_flagged_but_still_accepted_and_scored():
    interview = _start()
    text = ("typed instantly " * 40).strip()
    assert len(text) >= config.FAST_SUBMISSION_MIN_CHARS
    response = _answer(interview, text)
    assert response.status_code == 200 and response.json()["evaluation"]["overall_score"] >= 0
    fast = [e for e in _events(interview) if e["event_type"] == "fast_submission"]
    assert len(fast) == 1 and fast[0]["detail"]["chars_per_second"] > config.FAST_SUBMISSION_CHARS_PER_SECOND


def test_voice_answers_are_not_flagged_as_fast_typing():
    interview = _start()
    assert _answer(interview, ("spoken words " * 40).strip(), answer_source="voice").status_code == 200
    assert [e for e in _events(interview) if e["event_type"] == "fast_submission"] == []


# ---------------------------------------------------------------------------
# Completed interviews are frozen
# ---------------------------------------------------------------------------


def test_a_completed_interview_accepts_no_changes_and_logs_nothing():
    interview = _start(count=1)
    assert _answer(interview).status_code == 200
    assert client.post(f"/interview/{interview['interview_id']}/next").json()["status"] == "completed"
    iid, qid = interview["interview_id"], interview["current_question_id"]
    before = _events(interview)

    attempts = [
        client.post(f"/interview/{iid}/answer", json={"question_id": qid, "answer_text": "again"}),
        client.post(f"/interview/{iid}/answer/retry-evaluation", json={"question_id": qid}),
        client.post(f"/interview/{iid}/next"),
        client.post(f"/interview/{iid}/integrity-events", json={"events": [{"event_type": "copy"}]}),
        client.post(f"/interview/{iid}/transcribe", data={"question_id": qid}, files={"audio": ("a.webm", WEBM, "audio/webm")}),
    ]
    assert [r.status_code for r in attempts] == [409] * 5
    assert _events(interview) == before
    assert len(_session(interview).answers) == 1
