"""Candidate-aware cooldown rotation tests.

Pure-pool tests use a tiny fake repository so expectations do not depend on the
real question bank. Hand-computed QScores are unchanged from test_adaptive_selection:
    theta 0.2: easy 0.835964..., medium 0.710964..., hard 0.585964...
    theta 0.5: easy/hard 0.875, medium 1.0
"""

import random
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.candidate import CandidateCreate
from app.schemas.competency import CompetencyState
from app.schemas.evaluation import ConceptualEvaluation
from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question, QuestionType, ReviewStatus
from app.services import question_selector
from app.services.interview_engine import InterviewEngine, InterviewSession
from app.services.interview_store import MemoryInterviewStore
from app.services.question_selector import select_next_question

E, M, H = DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- helpers


class FakeRepo:
    def __init__(self, questions):
        self.questions = list(questions)

    def get_by_topic(self, topic):
        return [q for q in self.questions if q.topic.lower() == topic.lower()]

    def get_by_id(self, question_id):
        return next((q for q in self.questions if q.question_id == question_id), None)


def _q(question_id, difficulty, competency="A", topic="T"):
    return Question(
        question_id=question_id,
        question_text=f"Question {question_id}?",
        topic=topic,
        difficulty=difficulty,
        question_type=QuestionType.CONCEPTUAL,
        competency=competency,
        review_status=ReviewStatus.REVIEWED,
    )


def _state(competency, theta, attempts=1):
    return CompetencyState(
        competency_id=competency,
        theta=theta,
        questions_attempted=attempts,
        last_score=0.5,
        last_updated=datetime.now(timezone.utc),
    )


def _use_bank(monkeypatch, questions):
    monkeypatch.setattr(question_selector, "question_repository", FakeRepo(questions))


def _evaluation(question_id):
    return ConceptualEvaluation(
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


# --------------------------------------------------------------------- cooldown


def test_unseen_question_wins_over_a_better_scoring_seen_one(monkeypatch):
    # theta 0.2 scores the seen easy question far above the unseen hard one (0.836 > 0.586).
    _use_bank(monkeypatch, [_q("SEEN-E", E), _q("NEW-H", H)])
    states = {"A": _state("A", 0.2)}
    chosen = select_next_question("T", M, [], states, encountered={"SEEN-E": T0})
    assert chosen.question_id == "NEW-H"


def test_least_recently_assigned_question_is_chosen_when_all_are_seen(monkeypatch):
    _use_bank(monkeypatch, [_q("E1", E), _q("E2", E)])
    states = {"A": _state("A", 0.5)}
    encountered = {"E1": T0, "E2": T0 + timedelta(hours=1)}
    assert select_next_question("T", M, [], states, encountered=encountered).question_id == "E1"


def test_seen_questions_re_enter_the_pool_when_unseen_are_exhausted(monkeypatch):
    pool = [_q("E1", E), _q("E2", E), _q("E3", E)]
    _use_bank(monkeypatch, pool)
    states = {"A": _state("A", 0.5)}
    encountered = {q.question_id: T0 + timedelta(minutes=i) for i, q in enumerate(pool)}
    chosen = select_next_question("T", M, [], states, encountered=encountered)
    assert chosen is not None
    assert chosen.question_id == "E1"  # oldest assignment


def test_rotation_never_repeats_within_one_interview(monkeypatch):
    pool = [_q(f"Q{i}", M) for i in range(1, 6)]
    _use_bank(monkeypatch, pool)
    states = {"A": _state("A", 0.5)}
    encountered = {q.question_id: T0 + timedelta(minutes=i) for i, q in enumerate(pool)}
    asked = []
    for _ in range(5):
        chosen = select_next_question(
            "T", M, asked, states, encountered=encountered, rng=random.Random(0)
        )
        assert chosen is not None
        assert chosen.question_id not in asked
        asked.append(chosen.question_id)
    assert select_next_question("T", M, asked, states, encountered=encountered) is None


def test_anti_streak_guard_still_beats_the_unseen_tier(monkeypatch):
    # Three mediums in a row; the only alternative difficulty is a seen easy question.
    pool = [_q("M1", M), _q("M2", M), _q("M3", M), _q("M4", M), _q("E-seen", E)]
    _use_bank(monkeypatch, pool)
    states = {"A": _state("A", 0.5)}
    chosen = select_next_question(
        "T", M, ["M1", "M2", "M3"], states, encountered={"E-seen": T0}
    )
    assert chosen.question_id == "E-seen"


def test_anonymous_selection_is_unaffected_by_rotation(monkeypatch):
    _use_bank(monkeypatch, [_q("E1", E), _q("M1", M), _q("H1", H)])
    states = {"A": _state("A", 0.5)}
    for encountered in (None, {}):
        chosen = select_next_question("T", M, [], states, encountered=encountered)
        assert chosen is not None
        assert chosen.topic == "T"


# -------------------------------------------------------------------- cold start


def test_first_question_respects_the_requested_difficulty_over_cooldown(monkeypatch):
    _use_bank(monkeypatch, [_q("H-seen", H), _q("E-new", E)])
    chosen = select_next_question("T", H, [], None, encountered={"H-seen": T0})
    assert chosen.question_id == "H-seen"


def test_first_question_prefers_unseen_within_the_requested_difficulty(monkeypatch):
    _use_bank(monkeypatch, [_q("E-seen", E), _q("E-new", E)])
    chosen = select_next_question("T", E, [], None, encountered={"E-seen": T0})
    assert chosen.question_id == "E-new"


def test_first_question_rotates_to_the_least_recent_when_all_are_seen(monkeypatch):
    _use_bank(monkeypatch, [_q("E1", E), _q("E2", E)])
    encountered = {"E1": T0, "E2": T0 + timedelta(hours=1)}
    assert select_next_question("T", E, [], None, encountered=encountered).question_id == "E1"


# ------------------------------------------------------- controlled randomisation


def test_seeded_tie_break_is_deterministic_and_order_independent(monkeypatch):
    pool = [_q(f"M{i}", M) for i in range(1, 7)]
    states = {"A": _state("A", 0.5)}
    _use_bank(monkeypatch, pool)
    first = select_next_question("T", M, [], states, rng=random.Random(3)).question_id
    _use_bank(monkeypatch, list(reversed(pool)))
    assert select_next_question("T", M, [], states, rng=random.Random(3)).question_id == first


def test_ties_are_randomised_within_the_winning_group(monkeypatch):
    _use_bank(monkeypatch, [_q(f"M{i}", M) for i in range(1, 7)])
    states = {"A": _state("A", 0.5)}
    picks = {
        select_next_question("T", M, [], states, rng=random.Random(seed)).question_id
        for seed in range(12)
    }
    assert len(picks) > 1  # not always the alphabetically first question
    assert all(question_selector.question_repository.get_by_id(qid).difficulty == M for qid in picks)


def test_randomisation_never_leaves_the_top_tie_group(monkeypatch):
    # theta 0.5 ties easy and hard at 0.875; medium is 1.0, so medium must always win.
    _use_bank(monkeypatch, [_q("E1", E), _q("M1", M), _q("H1", H)])
    states = {"A": _state("A", 0.5)}
    for seed in range(10):
        chosen = select_next_question("T", M, [], states, rng=random.Random(seed))
        assert chosen.question_id == "M1"


# --------------------------------------------------------- domain + memory store


def test_session_uses_history_for_its_first_question(monkeypatch):
    _use_bank(monkeypatch, [_q(f"M{i}", M) for i in range(1, 5)])
    session = InterviewSession(
        "T", M, 3, candidate_id="c", encountered={"M1": T0, "M2": T0}, rng=random.Random(0)
    )
    assert session.current_question_id in {"M3", "M4"}


def test_session_advance_keeps_rotating_and_never_repeats(monkeypatch):
    _use_bank(monkeypatch, [_q(f"M{i}", M) for i in range(1, 5)])
    session = InterviewSession("T", M, 4, candidate_id="c", encountered={}, rng=random.Random(0))
    now = T0
    seen = [session.current_question_id]
    for _ in range(3):
        question_id = session.current_question_id
        question = question_selector.question_repository.get_by_id(question_id)
        session.record_answer(question_id, "A thorough answer.", now=now)
        session.apply_evaluation(question, _evaluation(question_id), now=now)
        session.advance_to_next_question(now=now)
        now += timedelta(seconds=1)
        seen.append(session.current_question_id)
    assert len(set(seen)) == 4


def test_memory_store_rotates_questions_across_interviews():
    engine = InterviewEngine()
    store = MemoryInterviewStore(engine)
    candidate = store.create_candidate(CandidateCreate(display_name="Ada"))

    seen = []
    for _ in range(5):
        session = store.create_interview("Databases", E, 3, candidate.candidate_id)
        seen.append(session.current_question_id)
    assert len(set(seen)) == 5


def test_concurrent_creation_for_one_candidate_does_not_repeat_questions():
    engine = InterviewEngine()
    store = MemoryInterviewStore(engine)
    candidate = store.create_candidate(CandidateCreate(display_name="Concurrent"))
    barrier = threading.Barrier(6)
    picked, errors = [], []

    def start():
        try:
            barrier.wait()
            picked.append(store.create_interview("Databases", E, 1, candidate.candidate_id).current_question_id)
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(picked) == 6
    assert len(set(picked)) == 6


def test_memory_store_history_is_scoped_by_candidate():
    engine = InterviewEngine()
    store = MemoryInterviewStore(engine)
    ada = store.create_candidate(CandidateCreate(display_name="Ada"))
    grace = store.create_candidate(CandidateCreate(display_name="Grace"))

    first = store.create_interview("Databases", E, 1, ada.candidate_id)

    assert set(store._question_history(ada.candidate_id, "Databases")) == {first.current_question_id}
    assert store._question_history(grace.candidate_id, "Databases") == {}
    assert store._question_history(ada.candidate_id, "Security") == {}


def test_anonymous_assignments_are_not_attributed_to_a_candidate():
    engine = InterviewEngine()
    store = MemoryInterviewStore(engine)
    ada = store.create_candidate(CandidateCreate(display_name="Ada"))

    anonymous = store.create_interview("Databases", E, 1, None)
    assert anonymous.encountered == {}
    assert store._question_history(ada.candidate_id, "Databases") == {}


def test_rotation_preserves_the_qscore_numbers():
    # The mathematical model is untouched: same theta, same difficulty, same QScore.
    from app.services.question_selector import score_candidates

    scored = score_candidates([_q("E1", E)], {"A": _state("A", 0.2)})[0]
    assert scored.qscore == pytest.approx(0.835964047444, abs=1e-9)
    assert scored.idi == pytest.approx(0.7219280948873623, abs=1e-12)
