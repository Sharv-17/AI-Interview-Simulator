import math
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.competency import EMA_ALPHA, THETA_INITIAL, CompetencyState
from app.schemas.interview import DifficultyLevel
from app.services.adaptive_metrics import (
    DIFFICULTY_VALUE,
    bernoulli_entropy,
    competency_entropy,
    difficulty_fit,
    difficulty_value,
    idi,
    qscore,
    rank_by_qscore,
    score_candidate,
)
from app.services.competency_state import CompetencyStateStore, apply_ema

client = TestClient(app)
TOL = 1e-9


def _state(theta: float) -> CompetencyState:
    return CompetencyState(
        competency_id="Algorithms",
        theta=theta,
        questions_attempted=1,
        last_score=0.5,
        last_updated=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1-2. Stage 3.5 theta / EMA regression (must be unchanged)
# ---------------------------------------------------------------------------


def test_alpha_and_initial_theta_are_unchanged():
    assert EMA_ALPHA == 0.15
    assert THETA_INITIAL == 0.5


def test_ema_regression_from_stage_3_5():
    # theta_new = 0.85*0.5 + 0.15*0.8 = 0.545
    assert apply_ema(0.5, 0.8) == pytest.approx(0.545, abs=TOL)
    # second step from the spec example: 0.85*0.545 + 0.15*0.4 = 0.52325
    assert apply_ema(0.545, 0.4) == pytest.approx(0.52325, abs=TOL)


def test_competency_values_remain_valid_after_many_updates():
    store = CompetencyStateStore()
    q = SimpleNamespace(competency="X", subtopic=None, topic="X")
    for score in [0, 10, 0, 10, 5, 10, 0] * 10:
        update = store.update_from_answer(question=q, overall_score=score)
        assert 0.0 <= update.new_theta <= 1.0


# ---------------------------------------------------------------------------
# 3-7. Entropy
# ---------------------------------------------------------------------------


def test_entropy_at_theta_zero_is_zero():
    assert bernoulli_entropy(0.0) == 0.0


def test_entropy_at_theta_one_is_zero():
    assert bernoulli_entropy(1.0) == 0.0


def test_entropy_at_half_is_one_bit():
    assert bernoulli_entropy(0.5) == pytest.approx(1.0, abs=TOL)


def test_entropy_known_value_at_quarter():
    # H(0.25) = 0.25*2 + 0.75*log2(4/3) = 0.8112781244591328 (hand-derived)
    assert bernoulli_entropy(0.25) == pytest.approx(0.8112781244591328, abs=1e-12)


def test_entropy_is_symmetric_around_half():
    for p in [0.01, 0.1, 0.25, 0.3, 0.45]:
        assert bernoulli_entropy(p) == pytest.approx(bernoulli_entropy(1 - p), abs=1e-12)


def test_entropy_near_boundaries_is_small_positive_and_finite():
    for p in [1e-12, 1e-6, 1 - 1e-6, 1 - 1e-12]:
        h = bernoulli_entropy(p)
        assert math.isfinite(h)
        assert 0.0 < h < 1e-4


def test_entropy_range_and_peak_at_half():
    values = [bernoulli_entropy(i / 100) for i in range(101)]
    assert all(0.0 <= v <= 1.0 + TOL for v in values)
    assert max(values) == pytest.approx(1.0, abs=TOL)
    assert values.index(max(values)) == 50


def test_entropy_increases_toward_half():
    for a, b in [(0.0, 0.1), (0.1, 0.3), (0.3, 0.5)]:
        assert bernoulli_entropy(a) < bernoulli_entropy(b)


@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan")])
def test_entropy_rejects_invalid_probability(bad):
    with pytest.raises(ValueError):
        bernoulli_entropy(bad)


def test_competency_entropy_matches_bernoulli_entropy():
    assert competency_entropy(0.3) == bernoulli_entropy(0.3)


# ---------------------------------------------------------------------------
# 8-9. IDI (placeholder baseline = H(theta))
# ---------------------------------------------------------------------------


def test_idi_expected_values():
    assert idi(0.5) == pytest.approx(1.0, abs=TOL)
    assert idi(0.25) == pytest.approx(0.8112781244591328, abs=1e-12)


def test_idi_boundary_cases():
    assert idi(0.0) == 0.0
    assert idi(1.0) == 0.0
    with pytest.raises(ValueError):
        idi(1.5)


# ---------------------------------------------------------------------------
# 10-11. Difficulty mapping and fit
# ---------------------------------------------------------------------------


def test_difficulty_mapping_is_explicit_and_symmetric():
    assert DIFFICULTY_VALUE == {"easy": 0.25, "medium": 0.5, "hard": 0.75}
    assert difficulty_value(DifficultyLevel.EASY) == 0.25
    assert difficulty_value("  HARD ") == 0.75


def test_difficulty_fit_expected_values():
    assert difficulty_fit(0.5, 0.5) == pytest.approx(1.0, abs=TOL)
    assert difficulty_fit(0.5, 0.75) == pytest.approx(0.75, abs=TOL)
    assert difficulty_fit(0.9, 0.25) == pytest.approx(0.35, abs=TOL)


def test_difficulty_fit_is_symmetric_in_the_gap():
    assert difficulty_fit(0.5, 0.25) == pytest.approx(difficulty_fit(0.5, 0.75), abs=TOL)


def test_difficulty_fit_boundary_cases():
    assert difficulty_fit(0.0, 0.0) == 1.0
    assert difficulty_fit(0.0, 1.0) == 0.0
    assert difficulty_fit(1.0, 0.0) == 0.0
    with pytest.raises(ValueError):
        difficulty_fit(-0.1, 0.5)
    with pytest.raises(ValueError):
        difficulty_fit(0.5, 1.2)


# ---------------------------------------------------------------------------
# 12-13. QScore
# ---------------------------------------------------------------------------


def test_qscore_expected_values_with_equal_weights():
    assert qscore(1.0, 0.75) == pytest.approx(0.875, abs=TOL)
    assert qscore(0.4, 0.6) == pytest.approx(0.5, abs=TOL)


def test_qscore_custom_weights():
    assert qscore(1.0, 0.0, idi_weight=0.8, fit_weight=0.2) == pytest.approx(0.8, abs=TOL)


def test_qscore_boundary_cases():
    assert qscore(0.0, 0.0) == 0.0
    assert qscore(1.0, 1.0) == pytest.approx(1.0, abs=TOL)


def test_qscore_rejects_bad_weights_and_inputs():
    with pytest.raises(ValueError):
        qscore(0.5, 0.5, idi_weight=0.7, fit_weight=0.7)  # sum != 1
    with pytest.raises(ValueError):
        qscore(0.5, 0.5, idi_weight=-0.5, fit_weight=1.5)  # negative weight
    with pytest.raises(ValueError):
        qscore(1.5, 0.5)


def test_ranking_orders_by_qscore_then_question_id():
    ranked = rank_by_qscore([("q-3", 0.5), ("q-1", 0.9), ("q-2", 0.5), ("q-4", 0.1)])
    assert ranked == ["q-1", "q-2", "q-3", "q-4"]  # q-2 before q-3 on the tie


def test_ranking_absorbs_float_noise_in_ties():
    ranked = rank_by_qscore([("b", 0.1 + 0.2), ("a", 0.3)])  # 0.30000000000000004 vs 0.3
    assert ranked == ["a", "b"]


# ---------------------------------------------------------------------------
# 14. Missing metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", [None, "", "impossible", 42])
def test_missing_or_unknown_difficulty_is_never_guessed(label):
    assert difficulty_value(label) is None
    assert difficulty_fit(0.5, difficulty_value(label)) is None


def test_missing_difficulty_gives_no_qscore_and_is_excluded_from_ranking():
    result = score_candidate(difficulty=None, competency_state=_state(0.5))
    assert result.difficulty_fit is None
    assert result.qscore is None
    assert rank_by_qscore([("a", result.qscore), ("b", 0.2)]) == ["b"]


def test_untouched_competency_uses_documented_initial_prior():
    result = score_candidate(difficulty="medium", competency_state=None)
    assert result.theta == THETA_INITIAL
    assert result.entropy == pytest.approx(1.0, abs=TOL)
    assert result.difficulty_fit == pytest.approx(1.0, abs=TOL)
    assert result.qscore == pytest.approx(1.0, abs=TOL)


# ---------------------------------------------------------------------------
# End-to-end pipeline value, hand-computed
# ---------------------------------------------------------------------------


def test_full_pipeline_hand_computed_example():
    # theta=0.25, hard (d=0.75): H=0.8112781244591328, fit=1-0.5=0.5
    # QScore = 0.5*0.8112781244591328 + 0.5*0.5 = 0.6556390622295664
    result = score_candidate(difficulty=DifficultyLevel.HARD, competency_state=_state(0.25))
    assert result.entropy == pytest.approx(0.8112781244591328, abs=1e-12)
    assert result.idi == pytest.approx(0.8112781244591328, abs=1e-12)
    assert result.difficulty_value == 0.75
    assert result.difficulty_fit == pytest.approx(0.5, abs=TOL)
    assert result.qscore == pytest.approx(0.6556390622295664, abs=1e-12)


def test_scoring_does_not_modify_competency_state():
    state = _state(0.4)
    before = state.model_copy()
    score_candidate(difficulty="easy", competency_state=state)
    assert state == before


# ---------------------------------------------------------------------------
# 15-18. Determinism, offline, regression
# ---------------------------------------------------------------------------


def test_repeated_calculations_are_identical():
    runs = [score_candidate("hard", _state(0.37)) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_metrics_need_no_network_or_external_api():
    # Pure functions over plain numbers: no client, key, or service involved.
    assert score_candidate("medium", None).qscore is not None


def test_existing_answer_flow_unaffected_by_new_module():
    start = client.post(
        "/interview/start",
        json={"topic": "Algorithms", "difficulty": "easy", "question_count": 3},
    ).json()
    answer = client.post(
        f"/interview/{start['interview_id']}/answer",
        json={"question_id": start["current_question_id"], "answer_text": "A sufficiently detailed technical answer."},
    )
    assert answer.status_code == 200
    assert answer.json()["competency_update"]["previous_theta"] == pytest.approx(0.5, abs=TOL)


def test_health_still_works():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}