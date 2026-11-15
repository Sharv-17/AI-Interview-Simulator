"""Phase 1 tests: the question selector ranks by QScore using competency state.

Pure-pool tests use a tiny fake repository so expectations don't depend on the
real question bank. Expected numbers are hand-computed:
    H(0.2) = H(0.8) = 0.7219280948873623,  H(0.9) = 0.4689955935892811
    QScore = 0.5 * H(theta) + 0.5 * (1 - |theta - d|),  d: easy .25 / medium .5 / hard .75
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.question_repository import question_repository
from app.schemas.competency import THETA_INITIAL, CompetencyState
from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question, QuestionType, ReviewStatus
from app.services import question_selector
from app.services.adaptive_metrics import difficulty_value
from app.services.question_selector import (
    STREAK_LIMIT,
    score_candidates,
    select_next_question,
)

client = TestClient(app)
TOL = 1e-9
E, M, H = DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD


# ---------------------------------------------------------------------------
# Helpers: a fake bank and hand-built questions
# ---------------------------------------------------------------------------


class FakeRepo:
    def __init__(self, questions):
        self.questions = list(questions)

    def get_by_topic(self, topic):
        return [q for q in self.questions if q.topic.lower() == topic.lower()]

    def get_by_id(self, question_id):
        return next((q for q in self.questions if q.question_id == question_id), None)


def _q(question_id, difficulty, competency="A", topic="T", status=ReviewStatus.REVIEWED):
    return Question(
        question_id=question_id,
        question_text=f"Question {question_id}?",
        topic=topic,
        difficulty=difficulty,
        question_type=QuestionType.CONCEPTUAL,
        competency=competency,
        review_status=status,
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


def _three_difficulties():
    return [_q("E1", E), _q("M1", M), _q("H1", H)]


# ---------------------------------------------------------------------------
# Candidate levels: difficulty follows theta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "theta, expected_id, label",
    [(0.2, "E1", "beginner"), (0.5, "M1", "intermediate"), (0.8, "H1", "advanced")],
)
def test_difficulty_follows_the_candidate_level(monkeypatch, theta, expected_id, label):
    _use_bank(monkeypatch, _three_difficulties())
    chosen = select_next_question("T", M, [], {"A": _state("A", theta)})
    assert chosen.question_id == expected_id, label


def test_requested_difficulty_does_not_override_theta_once_history_exists(monkeypatch):
    _use_bank(monkeypatch, _three_difficulties())
    # Asked for HARD, but a beginner (theta 0.2) is served an easy question.
    assert select_next_question("T", H, [], {"A": _state("A", 0.2)}).question_id == "E1"


# ---------------------------------------------------------------------------
# The numbers behind the ranking
# ---------------------------------------------------------------------------


def test_scores_match_hand_computed_values(monkeypatch):
    scored = {s.question_id: s for s in score_candidates(_three_difficulties(), {"A": _state("A", 0.2)})}
    assert scored["E1"].qscore == pytest.approx(0.835964047444, abs=1e-9)
    assert scored["M1"].qscore == pytest.approx(0.710964047444, abs=1e-9)
    assert scored["H1"].qscore == pytest.approx(0.585964047444, abs=1e-9)
    assert scored["E1"].entropy == pytest.approx(0.7219280948873623, abs=1e-12)
    assert scored["E1"].difficulty_fit == pytest.approx(0.95, abs=TOL)
    assert scored["E1"].has_history is True


def test_scoring_is_read_only_and_keeps_input_order():
    state = _state("A", 0.4)
    before = state.model_copy()
    pool = [_q("Z", H), _q("A1", E)]
    scored = score_candidates(pool, {"A": state})
    assert [s.question_id for s in scored] == ["Z", "A1"]
    assert state == before


# ---------------------------------------------------------------------------
# Uncertainty (IDI) decides between competencies
# ---------------------------------------------------------------------------


def test_higher_uncertainty_competency_is_probed_first_when_difficulty_fit_is_equal(monkeypatch):
    # Both easy questions fit equally (|theta - 0.25| = 0.05), so only IDI differs:
    # A (theta 0.3) is less certain than B (theta 0.2): 0.9156 > 0.8360.
    _use_bank(monkeypatch, [_q("B-easy", E, "B"), _q("A-easy", E, "A")])
    states = {"A": _state("A", 0.3), "B": _state("B", 0.2)}
    assert select_next_question("T", M, [], states).question_id == "A-easy"
    scored = {s.question_id: s.qscore for s in score_candidates([_q("A-easy", E, "A"), _q("B-easy", E, "B")], states)}
    assert scored["A-easy"] == pytest.approx(0.915645449615, abs=1e-9)
    assert scored["B-easy"] == pytest.approx(0.835964047444, abs=1e-9)


def test_a_nearly_certain_competency_loses_to_an_unexplored_one(monkeypatch):
    # theta 0.99 is almost certain (H = 0.081); the untouched competency uses the prior 0.5.
    _use_bank(monkeypatch, [_q("A-med", M, "A"), _q("B-med", M, "B")])
    chosen = select_next_question("T", M, [], {"A": _state("A", 0.99)})
    assert chosen.question_id == "B-med"


def test_competencies_without_history_use_the_documented_prior(monkeypatch):
    scored = score_candidates([_q("B-med", M, "B")], {"A": _state("A", 0.9)})[0]
    assert scored.has_history is False
    assert scored.theta == THETA_INITIAL
    assert scored.qscore == pytest.approx(1.0, abs=TOL)


def test_different_competencies_and_difficulties_are_ranked_together(monkeypatch):
    # A (theta 0.5): easy/hard -> 0.875.  B (theta 0.9): hard -> 0.6595, medium -> 0.5345.
    pool = [_q("B-med", M, "B"), _q("B-hard", H, "B"), _q("A-hard", H, "A"), _q("A-easy", E, "A")]
    _use_bank(monkeypatch, pool)
    states = {"A": _state("A", 0.5), "B": _state("B", 0.9)}
    assert select_next_question("T", M, [], states).question_id == "A-easy"  # tie 0.875, id order
    scored = {s.question_id: s.qscore for s in score_candidates(pool, states)}
    assert scored["B-hard"] == pytest.approx(0.659497796795, abs=1e-9)
    assert scored["B-med"] == pytest.approx(0.534497796795, abs=1e-9)


# ---------------------------------------------------------------------------
# No history / cold start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("states", [None, {}])
def test_no_history_uses_the_requested_difficulty(monkeypatch, states):
    _use_bank(monkeypatch, _three_difficulties())
    # theta prior 0.5 would favour medium; cold start honours the request instead.
    assert select_next_question("T", H, [], states).question_id == "H1"
    assert select_next_question("T", E, [], states).question_id == "E1"


# ---------------------------------------------------------------------------
# Repeats, eligibility, empty pools
# ---------------------------------------------------------------------------


def test_asked_questions_are_never_repeated_and_pool_exhausts_cleanly(monkeypatch):
    _use_bank(monkeypatch, [_q("E1", E), _q("E2", E), _q("M1", M), _q("H1", H)])
    states = {"A": _state("A", 0.5)}
    asked = []
    for _ in range(4):
        chosen = select_next_question("T", M, asked, states)
        assert chosen is not None and chosen.question_id not in asked
        asked.append(chosen.question_id)
    assert select_next_question("T", M, asked, states) is None


def test_unreviewed_questions_are_excluded_even_when_they_fit_perfectly(monkeypatch):
    _use_bank(
        monkeypatch,
        [
            _q("M-bad", M, status=ReviewStatus.NEEDS_MANUAL_REVIEW),
            _q("M-coding", M, status=ReviewStatus.REQUIRES_CODING_EVALUATION),
            _q("E-ok", E),
        ],
    )
    assert select_next_question("T", M, [], {"A": _state("A", 0.5)}).question_id == "E-ok"


def test_unknown_topic_returns_none(monkeypatch):
    _use_bank(monkeypatch, _three_difficulties())
    assert select_next_question("Other", M, [], {"A": _state("A", 0.5)}) is None


# ---------------------------------------------------------------------------
# Missing or invalid competency data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_theta", [1.7, -0.2, float("nan"), float("inf"), "high", None, True])
def test_invalid_competency_data_falls_back_to_the_prior_without_crashing(monkeypatch, bad_theta, caplog):
    _use_bank(monkeypatch, _three_difficulties())
    with caplog.at_level("WARNING"):
        chosen = select_next_question("T", M, [], {"A": SimpleNamespace(theta=bad_theta)})
    assert chosen.question_id == "M1"  # prior 0.5 -> medium
    scored = score_candidates(_three_difficulties(), {"A": SimpleNamespace(theta=bad_theta)})
    assert all(s.theta == THETA_INITIAL and s.has_history is False for s in scored)
    assert "invalid competency state" in caplog.text


def test_unscorable_candidates_fall_back_to_the_baseline_instead_of_returning_nothing(monkeypatch):
    unknown = SimpleNamespace(
        question_id="X1", topic="T", competency="A", subtopic=None, difficulty="mystery", is_servable=True
    )
    _use_bank(monkeypatch, [unknown])
    assert select_next_question("T", M, [], {"A": _state("A", 0.5)}).question_id == "X1"


# ---------------------------------------------------------------------------
# Anti-streak guard
# ---------------------------------------------------------------------------


def _streak_pool():
    return [_q("E1", E), _q("E2", E), _q("M1", M), _q("M2", M), _q("M3", M), _q("M4", M), _q("M5", M), _q("H1", H)]


def test_difficulty_streak_is_broken_after_the_limit(monkeypatch):
    _use_bank(monkeypatch, _streak_pool())
    states = {"A": _state("A", 0.5)}
    assert STREAK_LIMIT == 3
    # Two mediums in a row: no guard, theta 0.5 still prefers medium.
    assert select_next_question("T", M, ["M1", "M2"], states).question_id == "M3"
    # Three mediums in a row: forced to a different difficulty (easy/hard tie -> id order).
    assert select_next_question("T", M, ["M1", "M2", "M3"], states).question_id == "E1"


def test_streak_guard_never_causes_a_dead_end(monkeypatch):
    _use_bank(monkeypatch, [_q(f"M{i}", M) for i in range(1, 7)])
    states = {"A": _state("A", 0.5)}
    assert select_next_question("T", M, ["M1", "M2", "M3"], states).question_id == "M4"


def test_streak_guard_only_counts_consecutive_same_difficulty(monkeypatch):
    _use_bank(monkeypatch, _streak_pool())
    states = {"A": _state("A", 0.5)}
    assert select_next_question("T", M, ["M1", "E1", "M2"], states).question_id == "M3"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_inputs_always_give_the_same_question(monkeypatch):
    _use_bank(monkeypatch, _streak_pool())
    states = {"A": _state("A", 0.37)}
    results = {select_next_question("T", M, ["M1"], states).question_id for _ in range(10)}
    assert len(results) == 1


def test_result_does_not_depend_on_the_order_questions_are_stored(monkeypatch):
    pool = _streak_pool()
    states = {"A": _state("A", 0.5)}
    _use_bank(monkeypatch, pool)
    forward = select_next_question("T", M, ["M1"], states).question_id
    _use_bank(monkeypatch, list(reversed(pool)))
    assert select_next_question("T", M, ["M1"], states).question_id == forward


# ---------------------------------------------------------------------------
# Real bank, end to end through the API
# ---------------------------------------------------------------------------

LONG_ANSWER = "A thorough, well structured answer that covers the main ideas, trade-offs and an example."
SHORT_ANSWER = "I do not know."


def _run_interview(answer_text, topic="System Design", questions=8):
    """Run a whole interview; returns the numeric difficulty of each question asked."""
    interview = client.post(
        "/interview/start", json={"topic": topic, "difficulty": "medium", "question_count": questions}
    ).json()
    iid, current, difficulties = interview["interview_id"], interview["current_question_id"], []
    while current is not None:
        difficulties.append(difficulty_value(question_repository.get_by_id(current).difficulty))
        answered = client.post(f"/interview/{iid}/answer", json={"question_id": current, "answer_text": answer_text})
        assert answered.status_code == 200
        current = client.post(f"/interview/{iid}/next").json()["current_question_id"]
    return difficulties


def test_weak_and_strong_candidates_get_different_difficulty_on_the_real_bank():
    # The placeholder evaluator scores long answers 8/10 and short ones 3/10, so
    # theta rises for one candidate and falls for the other.
    beginner = _run_interview(SHORT_ANSWER)
    advanced = _run_interview(LONG_ANSWER)

    assert beginner[0] == advanced[0] == 0.5  # same cold-start (requested medium)
    assert sum(beginner[1:]) / len(beginner[1:]) < sum(advanced[1:]) / len(advanced[1:])
    assert min(beginner) == 0.25 and max(advanced) == 0.75


def test_real_interview_never_exceeds_the_streak_limit_while_alternatives_exist():
    for answer in (SHORT_ANSWER, LONG_ANSWER):
        difficulties = _run_interview(answer)
        for i in range(len(difficulties) - STREAK_LIMIT):
            window = difficulties[i : i + STREAK_LIMIT + 1]
            assert len(set(window)) > 1, f"{STREAK_LIMIT + 1} identical difficulties in a row: {difficulties}"


def test_advancing_uses_qscore_ranking(monkeypatch):
    calls = []
    original = question_selector.rank_by_qscore
    monkeypatch.setattr(question_selector, "rank_by_qscore", lambda scored: calls.append(len(scored)) or original(scored))

    interview = client.post(
        "/interview/start", json={"topic": "Databases", "difficulty": "easy", "question_count": 3}
    ).json()
    iid = interview["interview_id"]
    assert calls == []  # first question: cold start, no ranking
    client.post(f"/interview/{iid}/answer", json={"question_id": interview["current_question_id"], "answer_text": LONG_ANSWER})
    client.post(f"/interview/{iid}/next")
    assert len(calls) == 1 and calls[0] > 1  # second question: ranked by QScore


def test_unreviewed_questions_are_never_asked_in_adaptive_mode():
    for answer in (SHORT_ANSWER, LONG_ANSWER):
        interview = client.post(
            "/interview/start", json={"topic": "Security", "difficulty": "medium", "question_count": 10}
        ).json()
        iid, current = interview["interview_id"], interview["current_question_id"]
        while current is not None:
            assert question_repository.get_by_id(current).is_servable
            client.post(f"/interview/{iid}/answer", json={"question_id": current, "answer_text": answer})
            current = client.post(f"/interview/{iid}/next").json()["current_question_id"]