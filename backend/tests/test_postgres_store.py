"""PostgreSQL store tests (opt-in).

Set TEST_DATABASE_URL to a PostgreSQL database and these run; otherwise they are
skipped. Every test works inside a temporary schema that the module creates and drops,
so no existing table or row outside that schema is read, truncated or dropped (running
them against the Neon database cannot damage its `public` schema).
"""

import os
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.db.postgres_store import PostgresInterviewStore, _normalize_url
from app.repositories.question_repository import question_repository
from app.schemas.candidate import CandidateCreate
from app.schemas.competency import EMA_ALPHA, THETA_INITIAL
from app.schemas.evaluation import AnswerSubmitRequest, ConceptualEvaluation, EvaluationStatus
from app.schemas.integrity import IntegrityEvent, IntegrityEventType
from app.schemas.interview import DifficultyLevel, InterviewStatus
from app.schemas.question import QuestionType
from app.services.evaluation_errors import (
    CandidateNotFoundError,
    InterviewBusyError,
    InterviewNotFoundError,
    QuestionDeadlinePassedError,
)
from app.services.interview_engine import utcnow
from app.services.interview_service import InterviewService

TEST_URL = (os.environ.get("TEST_DATABASE_URL") or "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="TEST_DATABASE_URL is not set (PostgreSQL integration tests are opt-in)"
)

TOPIC = "Databases"  # a topic with many servable questions in the bank
SCHEMA = f"test_interview_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="module")
def engine():
    from app.db.models import Base

    url = _normalize_url(TEST_URL)
    admin = create_engine(url, poolclass=NullPool)
    scoped = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        created = True
        scoped = create_engine(
            url, connect_args={"options": f"-csearch_path={SCHEMA}"}, poolclass=NullPool
        )
        # Inside try: a failed table setup must still drop the schema it created.
        Base.metadata.create_all(scoped)
        yield scoped
    finally:
        if scoped is not None:
            scoped.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        admin.dispose()


@pytest.fixture(scope="module")
def synced_engine(engine):
    PostgresInterviewStore(engine).startup()
    return engine


@pytest.fixture()
def store(synced_engine):
    return PostgresInterviewStore(synced_engine)


def _new_candidate(store, name="Ada"):
    return store.create_candidate(CandidateCreate(display_name=name, external_id=f"ext-{uuid.uuid4()}"))


def _current_question(session):
    question = question_repository.get_by_id(session.current_question_id)
    assert question is not None, "the bank must offer a servable question for this test"
    return question


def _evaluation(question_id, **overrides):
    payload = dict(
        question_id=question_id,
        overall_score=7.5,
        feedback="Solid answer.",
        evaluator="test-evaluator",
        technical_score=8,
        relevance_score=7,
        completeness_score=8,
        clarity_score=7,
        conceptual_understanding_score=8,
        correct_concepts=["normalization"],
        missing_concepts=[],
        incorrect_concepts=[],
        reasoning_summary="Reviewer-only reasoning summary.",
    )
    payload.update(overrides)
    return ConceptualEvaluation(**payload)


def _answer_and_evaluate(session, overall_score=7.5):
    question = _current_question(session)
    now = utcnow()
    session.record_answer(question.question_id, "A thorough answer " * 8, now=now)
    session.apply_evaluation(question, _evaluation(question.question_id, overall_score=overall_score), now=now)
    return question


# ------------------------------------------------------------------ connectivity


def test_normalize_url_adds_the_psycopg_driver():
    assert _normalize_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert _normalize_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _normalize_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"


def test_check_ready_reports_an_unreachable_database():
    unreachable = PostgresInterviewStore.from_url(
        "postgresql://nobody:nobody@127.0.0.1:1/nothing", connect_args={"connect_timeout": 1}
    )
    try:
        with pytest.raises(RuntimeError):
            unreachable.check_ready()
    finally:
        unreachable.dispose()


def test_check_ready_runs_against_the_database(store):
    store.check_ready()


# --------------------------------------------------------------------- questions


def test_question_bank_sync_is_idempotent_and_complete(synced_engine, store):
    def count():
        with synced_engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM questions")).scalar_one()

    first = count()
    assert first == len(question_repository.get_all())

    store.startup()  # repeated startup must update, never duplicate
    assert count() == first


def test_question_sync_keeps_review_status(synced_engine, store):
    coding = next(q for q in question_repository.get_all() if q.question_type == QuestionType.CODING)
    with synced_engine.connect() as connection:
        row = connection.execute(
            text("SELECT question_type, review_status FROM questions WHERE question_id = :qid"),
            {"qid": coding.question_id},
        ).one()
    assert row.question_type == "coding"
    assert row.review_status == coding.review_status.value


# -------------------------------------------------------------------- candidates


def test_candidate_roundtrip_and_errors(store):
    candidate = _new_candidate(store)
    assert store.get_candidate(candidate.candidate_id).display_name == "Ada"

    with pytest.raises(CandidateNotFoundError):
        store.get_candidate(str(uuid.uuid4()))
    with pytest.raises(CandidateNotFoundError):
        store.create_interview(TOPIC, DifficultyLevel.EASY, 1, str(uuid.uuid4()))

    external_id = f"dup-{uuid.uuid4()}"
    store.create_candidate(CandidateCreate(external_id=external_id))
    with pytest.raises(ValueError):
        store.create_candidate(CandidateCreate(external_id=external_id))


# -------------------------------------------------------------------- interviews


def test_interview_roundtrip_survives_a_restart(store, synced_engine):
    candidate = _new_candidate(store)
    session = store.create_interview(TOPIC, DifficultyLevel.MEDIUM, 3, candidate.candidate_id)

    restarted = PostgresInterviewStore(synced_engine)  # fresh engine sessions == new process
    loaded = restarted.read(session.interview_id)

    assert loaded.interview_id == session.interview_id
    assert loaded.candidate_id == candidate.candidate_id
    assert loaded.topic == TOPIC
    assert loaded.difficulty == DifficultyLevel.MEDIUM
    assert loaded.question_count == 3
    assert loaded.status == InterviewStatus.ACTIVE
    assert loaded.current_question == 1
    assert loaded.current_question_id == session.current_question_id
    assert loaded.question_started_at == session.question_started_at
    assert loaded.question_time_limit_seconds == session.question_time_limit_seconds
    assert loaded.question_grace_seconds == session.question_grace_seconds
    assert loaded.asked_question_ids == session.asked_question_ids
    assert loaded.answers == []


def test_read_unknown_interview(store):
    with pytest.raises(InterviewNotFoundError):
        store.read(str(uuid.uuid4()))


def test_anonymous_interview_persists_and_reports(store):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    assert session.candidate_id is None
    question_id = session.current_question_id

    with store.edit(session.interview_id) as editing:
        _answer_and_evaluate(editing)

    loaded = store.read(session.interview_id)
    assert loaded.candidate_id is None
    record = loaded.get_answer(question_id)
    assert record["evaluation_status"] == EvaluationStatus.COMPLETED

    report = store.report(session.interview_id)
    assert report.interview.candidate_id is None
    assert report.answers[0].question_id == question_id
    assert report.answers[0].reasoning_summary == "Reviewer-only reasoning summary."
    assert report.competency, "an evaluated answer must leave a competency state"


# -------------------------------------------------------------------- evaluation


def test_evaluation_details_and_competency_survive_reconstruction(store, synced_engine):
    candidate = _new_candidate(store, "Grace")
    session = store.create_interview(TOPIC, DifficultyLevel.MEDIUM, 3, candidate.candidate_id)

    with store.edit(session.interview_id) as editing:
        question = _answer_and_evaluate(editing, overall_score=7.5)

    restarted = PostgresInterviewStore(synced_engine)
    loaded = restarted.read(session.interview_id)
    record = loaded.get_answer(question.question_id)
    evaluation = record["evaluation"]

    assert isinstance(evaluation, ConceptualEvaluation)
    assert evaluation.overall_score == 7.5
    assert evaluation.technical_score == 8
    assert evaluation.correct_concepts == ["normalization"]
    assert evaluation.evaluation_status == EvaluationStatus.COMPLETED
    assert evaluation.reasoning_summary == "Reviewer-only reasoning summary."
    assert record["evaluator"] == "test-evaluator"
    assert record["evaluation_attempts"] == 1

    expected_theta = (1 - EMA_ALPHA) * THETA_INITIAL + EMA_ALPHA * 0.75
    update = record["competency_update"]
    assert update.competency == question.competency
    assert update.previous_theta == pytest.approx(THETA_INITIAL)
    assert update.new_theta == pytest.approx(expected_theta)

    state = loaded.competency_state.get(question.competency)
    assert state.theta == pytest.approx(expected_theta)
    assert state.questions_attempted == 1
    assert state.last_score == pytest.approx(0.75)

    history = restarted.competency_history(candidate.candidate_id)
    assert len(history) == 1
    assert history[0].answer_id == record["answer_id"]
    assert history[0].new_theta == pytest.approx(expected_theta)
    assert history[0].questions_attempted == 1


def test_failed_evaluation_is_persisted_without_a_score(store):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    with store.edit(session.interview_id) as editing:
        question = _current_question(editing)
        record = editing.record_answer(question.question_id, "Saved answer " * 5, now=utcnow())
    with store.edit(session.interview_id) as editing:
        from app.services.evaluation_errors import EvaluationUnavailableError

        editing.mark_evaluation_failed(question.question_id, EvaluationUnavailableError())
        assert record["answer_id"] == editing.get_answer(question.question_id)["answer_id"]

    loaded = store.read(session.interview_id)
    loaded_record = loaded.get_answer(question.question_id)
    assert loaded_record["evaluation_status"] == EvaluationStatus.PENDING
    assert loaded_record["evaluation"] is None
    assert loaded_record["competency_update"] is None
    assert loaded_record["evaluation_error"] == "evaluator_unavailable"
    assert loaded.competency_state.get_all() == {}

    report = store.report(session.interview_id)
    assert report.answers[0].evaluation_status == EvaluationStatus.PENDING
    assert report.answers[0].evaluation is None


# --------------------------------------------------------------------- integrity


def test_integrity_events_are_persisted_and_reported(store, synced_engine):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    question_id = session.current_question_id
    now = utcnow()
    events = [
        IntegrityEvent(event_type=IntegrityEventType.PASTE, occurred_at=now, source="answer_box"),
        IntegrityEvent(event_type=IntegrityEventType.TAB_SWITCH, duration_ms=1200),
    ]

    current, kept = store.record_integrity_events(session.interview_id, question_id, events, now)
    assert current == question_id
    assert kept == 2

    loaded = store.read(session.interview_id)
    assert [entry["event_type"] for entry in loaded.integrity_log] == ["paste", "tab_switch"]
    assert loaded.integrity_log[1]["duration_ms"] == 1200
    assert loaded.integrity_event_count == 2

    # The domain log (and IntegrityRecord) never carries client_source; the column is still stored.
    with synced_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT client_source, duration_ms FROM integrity_events WHERE interview_id = :iid ORDER BY id"),
            {"iid": session.interview_id},
        ).all()
    assert stored[0].client_source == "answer_box"
    assert stored[1].duration_ms == 1200

    report = store.report(session.interview_id)
    assert report.integrity_summary == {"paste": 1, "tab_switch": 1}
    assert report.integrity_events[0].question_id == question_id


def test_server_integrity_indicators_survive_a_late_submission(store):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    question_id = session.current_question_id
    late = session.question_started_at + timedelta(
        seconds=session.question_time_limit_seconds + session.question_grace_seconds + 5
    )
    service = InterviewService(store, clock=lambda: late)

    with pytest.raises(QuestionDeadlinePassedError):
        service.submit_answer(
            session.interview_id, AnswerSubmitRequest(question_id=question_id, answer_text="Too late")
        )

    loaded = store.read(session.interview_id)
    assert loaded.timed_out_question_ids == {question_id}
    assert [entry["event_type"] for entry in loaded.integrity_log] == ["late_submission_rejected"]
    report = store.report(session.interview_id)
    assert report.questions[0].state == "timed_out"
    assert report.questions[0].closed_at is not None


# ------------------------------------------------------------- transactions/locks


def test_failed_operation_rolls_back_completely(store):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    question_id = session.current_question_id

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with store.edit(session.interview_id) as editing:
            editing.record_answer(question_id, "Half-written answer " * 5, now=utcnow())
            raise Boom()

    loaded = store.read(session.interview_id)
    assert loaded.get_answer(question_id) is None
    assert loaded.answers == []
    assert loaded.current_question_id == question_id
    assert loaded.integrity_log == []
    report = store.report(session.interview_id)
    assert report.answers == []
    assert report.questions[0].state == "active"


def test_second_writer_gets_interview_busy(store):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    with store.edit(session.interview_id):
        with pytest.raises(InterviewBusyError):
            with store.edit(session.interview_id):
                pass


# -------------------------------------------------------------------- progression


def test_advance_persists_the_next_question_and_completion(store):
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 1, None)
    with store.edit(session.interview_id) as editing:
        first_question = _answer_and_evaluate(editing)

    response = InterviewService(store).advance(session.interview_id)
    assert response.status == InterviewStatus.COMPLETED

    loaded = store.read(session.interview_id)
    assert loaded.status == InterviewStatus.COMPLETED
    assert loaded.completed_at is not None
    assert loaded.current_question_id is None
    assert loaded.current_question == 1
    assert loaded.get_answer(first_question.question_id)["evaluation_status"] == EvaluationStatus.COMPLETED


def test_create_interview_works_before_question_sync(synced_engine):
    """The store must not depend on startup() having run before its first interview."""
    from app.db.models import Base

    schema = f"{SCHEMA}_nosync"
    admin = create_engine(synced_engine.url, poolclass=NullPool)
    fresh = None
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        fresh = create_engine(
            synced_engine.url, connect_args={"options": f"-csearch_path={schema}"}, poolclass=NullPool
        )
        Base.metadata.create_all(fresh)
        store = PostgresInterviewStore(fresh)
        session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
        assert session.current_question_id is not None
        assert store.read(session.interview_id).current_question_id == session.current_question_id
        with fresh.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM questions")).scalar_one() == 1
    finally:
        if fresh is not None:
            fresh.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_two_evaluations_on_one_competency_reconstruct_the_latest_state(store, synced_engine):
    """Multiple evaluated answers on one competency must reconstruct the LAST theta."""
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, None)
    with store.edit(session.interview_id) as editing:
        first = _answer_and_evaluate(editing, overall_score=8.0)
    InterviewService(store).advance(session.interview_id)
    with store.edit(session.interview_id) as editing:
        second = _answer_and_evaluate(editing, overall_score=6.0)
    assert first.competency == second.competency == "Databases"

    restarted = PostgresInterviewStore(synced_engine)
    loaded = restarted.read(session.interview_id)
    state = loaded.competency_state.get("Databases")

    # 0.85 * 0.5 + 0.15 * 0.8 = 0.545, then 0.85 * 0.545 + 0.15 * 0.6 = 0.55325
    assert state.questions_attempted == 2
    assert state.theta == pytest.approx(0.55325)
    assert state.last_score == pytest.approx(0.6)
    assert loaded.get_answer(second.question_id)["competency_update"].previous_theta == pytest.approx(0.545)
    assert len(loaded.answers) == 2
    assert loaded.get_answer(first.question_id)["evaluation_status"] == EvaluationStatus.COMPLETED
    assert restarted.report(session.interview_id).competency["Databases"].theta == pytest.approx(0.55325)


# --------------------------------------------------------------------- rotation


def test_assigned_questions_enter_the_cooldown_history(store, synced_engine):
    candidate = _new_candidate(store, "Rotating")
    first = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, candidate.candidate_id)
    with synced_engine.connect() as connection:
        assigned = (
            connection.execute(
                text("SELECT question_id FROM interview_questions WHERE interview_id = :iid"),
                {"iid": first.interview_id},
            )
            .scalars()
            .all()
        )
    assert assigned == [first.current_question_id]

    # Assigned but never answered still counts as an encounter.
    second = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, candidate.candidate_id)
    assert second.current_question_id != first.current_question_id


def test_rotation_continues_across_many_interviews(store):
    candidate = _new_candidate(store, "Rotating")
    seen = [
        store.create_interview(TOPIC, DifficultyLevel.EASY, 1, candidate.candidate_id).current_question_id
        for _ in range(6)
    ]
    assert len(set(seen)) == 6


def test_question_history_is_scoped_to_candidate_and_topic(store):
    candidate = _new_candidate(store, "Scoped")
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 1, candidate.candidate_id)

    with store._session_factory() as db:
        scoped = store._question_history(db, candidate.candidate_id, TOPIC)
        other_topic = store._question_history(db, candidate.candidate_id, "Security")
        unknown_candidate = store._question_history(db, str(uuid.uuid4()), TOPIC)

    assert set(scoped) == {session.current_question_id}
    assert other_topic == {}
    assert unknown_candidate == {}


def test_rotation_survives_a_restart(store, synced_engine):
    candidate = _new_candidate(store, "Restart")
    first = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, candidate.candidate_id)

    restarted = PostgresInterviewStore(synced_engine)
    second = restarted.create_interview(TOPIC, DifficultyLevel.EASY, 2, candidate.candidate_id)
    assert second.current_question_id != first.current_question_id


def test_timed_out_assignment_counts_as_an_encounter(store):
    candidate = _new_candidate(store, "Abandoned")
    first = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, candidate.candidate_id)
    question_id = first.current_question_id
    late = first.question_started_at + timedelta(
        seconds=first.question_time_limit_seconds + first.question_grace_seconds + 5
    )
    service = InterviewService(store, clock=lambda: late)
    with pytest.raises(QuestionDeadlinePassedError):
        service.submit_answer(
            first.interview_id, AnswerSubmitRequest(question_id=question_id, answer_text="Too late")
        )

    second = store.create_interview(TOPIC, DifficultyLevel.EASY, 2, candidate.candidate_id)
    assert second.current_question_id != question_id


def test_advance_keeps_rotation_active(store):
    candidate = _new_candidate(store, "Advancing")
    session = store.create_interview(TOPIC, DifficultyLevel.EASY, 3, candidate.candidate_id)
    asked = [session.current_question_id]
    service = InterviewService(store)
    for _ in range(2):
        state = store.read(session.interview_id)
        service.submit_answer(
            session.interview_id,
            AnswerSubmitRequest(question_id=state.current_question_id, answer_text="A detailed answer " * 5),
        )
        asked.append(service.advance(session.interview_id).current_question_id)
    assert len(set(asked)) == 3


def test_topic_history_matching_is_case_insensitive(store, synced_engine):
    """`Databases` and `databases` share one cooldown history (the real SQL query)."""
    candidate = _new_candidate(store, "Case")

    first = store.create_interview("Databases", DifficultyLevel.EASY, 1, candidate.candidate_id)
    assert first.current_question_id is not None
    assert first.encountered == {}  # nothing to rotate yet

    # The stored topic keeps the caller's capitalization: only the lookup normalizes.
    with synced_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT topic FROM interview_sessions WHERE interview_id = :iid"),
            {"iid": first.interview_id},
        ).scalar_one()
    assert stored == "Databases"

    with store._session_factory() as db:
        mixed_case = store._question_history(db, candidate.candidate_id, "dAtAbAsEs")
    assert set(mixed_case) == {first.current_question_id}

    # A case-sensitive history query would return {} here, so `encountered` would be
    # empty and the cooldown tier would not know the first question was already used.
    second = store.create_interview("databases", DifficultyLevel.EASY, 1, candidate.candidate_id)
    assert set(second.encountered) == {first.current_question_id}
    assert second.current_question_id != first.current_question_id
    assert question_repository.get_by_id(second.current_question_id).difficulty == DifficultyLevel.EASY

    with synced_engine.connect() as connection:
        second_topic = connection.execute(
            text("SELECT topic FROM interview_sessions WHERE interview_id = :iid"),
            {"iid": second.interview_id},
        ).scalar_one()
        assigned = (
            connection.execute(
                text("SELECT question_id FROM interview_questions WHERE interview_id = :iid"),
                {"iid": second.interview_id},
            )
            .scalars()
            .all()
        )
    assert second_topic == "databases"
    assert assigned == [second.current_question_id]

    # Neither another candidate nor a genuinely different topic sees this history.
    other = _new_candidate(store, "Unrelated")
    with store._session_factory() as db:
        assert store._question_history(db, other.candidate_id, "Databases") == {}
        assert store._question_history(db, candidate.candidate_id, "Security") == {}


def test_concurrent_creation_serialises_the_cooldown(synced_engine, store):
    """Two independent sessions starting at once must not assign the same question.

    Each worker owns its engine (its own connections), and a barrier releases both
    into `create_interview` together. Server-side statement/lock timeouts plus the
    bounded joins keep a deadlock from hanging the suite.
    """
    candidate = _new_candidate(store, "Concurrent")
    barrier = threading.Barrier(2)
    created, errors = [], []

    def worker():
        engine = create_engine(
            synced_engine.url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 10,
                "options": (
                    f"-csearch_path={SCHEMA} -cstatement_timeout=30000 -clock_timeout=15000"
                ),
            },
        )
        own_store = PostgresInterviewStore(engine)
        try:
            barrier.wait(timeout=15)
            created.append(
                own_store.create_interview("Databases", DifficultyLevel.EASY, 1, candidate.candidate_id)
            )
        except BaseException as exc:  # surfaced by the assertions below, never swallowed
            errors.append(exc)
        finally:
            own_store.dispose()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    assert not any(thread.is_alive() for thread in threads), "concurrent creation did not finish in 90s"
    assert errors == []
    assert len(created) == 2

    # The candidate row lock serialises the two starts: the later one already saw the
    # earlier assignment. Without the lock both would read an empty history.
    ordered = sorted(created, key=lambda session: len(session.encountered))
    first, second = ordered
    assert [len(session.encountered) for session in ordered] == [0, 1]
    assert set(second.encountered) == {first.current_question_id}
    assert first.current_question_id != second.current_question_id

    # Persisted state: exactly one assignment per interview, matching what was returned.
    with synced_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT s.interview_id, s.current_question_id, iq.question_id "
                "FROM interview_sessions s JOIN interview_questions iq USING (interview_id) "
                "WHERE s.candidate_id = :cid"
            ),
            {"cid": candidate.candidate_id},
        ).all()
    assert len(rows) == 2
    assert {row.interview_id for row in rows} == {session.interview_id for session in created}
    assert {row.question_id for row in rows} == {session.current_question_id for session in created}
    assert all(row.current_question_id == row.question_id for row in rows)

    # Cooldown history after both commits contains both questions, and rotation continues.
    with store._session_factory() as db:
        history = store._question_history(db, candidate.candidate_id, "Databases")
    assert set(history) == {session.current_question_id for session in created}

    third = store.create_interview("Databases", DifficultyLevel.EASY, 1, candidate.candidate_id)
    assert third.current_question_id not in {session.current_question_id for session in created}
    assert set(third.encountered) == {session.current_question_id for session in created}


def test_list_interviews_returns_only_this_candidates(store, synced_engine):
    candidate = _new_candidate(store, "Listed")
    first = store.create_interview(TOPIC, DifficultyLevel.EASY, 1, candidate.candidate_id)
    second = store.create_interview(TOPIC, DifficultyLevel.EASY, 1, candidate.candidate_id)
    store.create_interview(TOPIC, DifficultyLevel.EASY, 1, None)

    restarted = PostgresInterviewStore(synced_engine)
    summaries = restarted.list_interviews(candidate.candidate_id)
    assert {summary.interview_id for summary in summaries} == {first.interview_id, second.interview_id}
    assert all(summary.candidate_id == candidate.candidate_id for summary in summaries)
