"""Mathematical foundations for the adaptive-interview research model.

    theta -> H(theta) -> IDI -> DifficultyFit -> QScore

Every function here is PURE and DETERMINISTIC: no randomness, no I/O, no
database, no LLM, no mutation of competency state.
app/services/question_selector.py calls these functions to rank candidate questions.

READ THIS BEFORE TRUSTING ANY NUMBER (status of each definition)
----------------------------------------------------------------
* theta (competency estimate) .... RESEARCH DEFINITION (project design).
  Implemented in app/services/competency_state.py (Stage 3.5), unchanged:
  theta_new = (1 - alpha) * theta_old + alpha * S, alpha = 0.15.
* H(theta) ........................ IMPLEMENTATION ASSUMPTION. Bernoulli
  entropy baseline. A single theta is not itself a distribution; treating
  it as P(success) is an operational choice, not a claim that competency
  is Bernoulli-distributed.
* IDI ............................. PROPOSED BASELINE. The project has not
  yet formally defined IDI. The placeholder here is the minimal one
  (IDI = H(theta)) so it can be swapped for the real definition by
  replacing ONE function.
* DifficultyFit ................... PROPOSED BASELINE. 1 - |theta - d| with an
  explicit categorical difficulty mapping. Not claimed optimal.
* QScore .......................... PROPOSED BASELINE. Equal-weight sum of
  IDI and DifficultyFit. Weights are NOT tuned.
* EMPIRICAL VALIDATION ............ NONE. No experiment has validated any
  baseline above. They are implementation hypotheses.

See docs/MATHEMATICAL_SPEC.md for notation, ranges, limitations, examples.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union

from app.schemas.competency import THETA_INITIAL, CompetencyState

# ---------------------------------------------------------------------------
# Constants (all documented assumptions; replace here, not at call sites)
# ---------------------------------------------------------------------------

# Categorical difficulty label -> numeric difficulty d on the same [0,1]
# scale as theta (higher = harder / more competent).
# ASSUMPTION: evenly spaced and symmetric about 0.5, so "medium" aligns with
# the neutral initial theta. The dataset's easy/medium/hard labels are NOT
# empirically calibrated; this mapping inherits that weakness.
DIFFICULTY_VALUE: Dict[str, float] = {
    "easy": 0.25,
    "medium": 0.50,
    "hard": 0.75,
}

# Baseline QScore weights. Equal weights = "no prior preference" assumption.
# NOT tuned on data.
DEFAULT_IDI_WEIGHT = 0.5
DEFAULT_FIT_WEIGHT = 0.5

_WEIGHT_SUM_TOLERANCE = 1e-9
_TIE_ROUNDING_DIGITS = 12


def _require_unit_interval(name: str, value: float) -> None:
    """Raise ValueError unless value is a finite number in [0, 1]."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or math.isnan(value):
        raise ValueError(f"{name} must be a number in [0, 1], got {value!r}")
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")


# ---------------------------------------------------------------------------
# 1. Shannon entropy H(theta)  -- Bernoulli baseline
# ---------------------------------------------------------------------------


def bernoulli_entropy(p: float) -> float:
    """Shannon entropy (in bits) of a Bernoulli(p) variable.

        H(p) = -p*log2(p) - (1-p)*log2(1-p)

    Range: [0, 1] bits. H(0) = H(1) = 0 (by the limit x*log2(x) -> 0, so
    log2(0) is never evaluated). Maximum H(0.5) = 1. Symmetric: H(p) = H(1-p).

    Raises ValueError if p is NaN or outside [0, 1] (never silently clamps:
    an invalid probability here indicates an upstream bug).
    """
    _require_unit_interval("p", p)
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)


def competency_entropy(theta: float) -> float:
    """H(theta): entropy of the competency estimate under the Bernoulli baseline.

    OPERATIONAL BASELINE: interprets theta as P(success) and (1 - theta) as
    P(failure). This is NOT evidence that competency is Bernoulli-distributed.
    Interpretation: how uncertain the model is about the candidate on this
    competency (1 bit at theta = 0.5, 0 at the extremes).
    """
    return bernoulli_entropy(theta)


# ---------------------------------------------------------------------------
# 2. IDI  -- PROPOSED BASELINE (project definition still open)
# ---------------------------------------------------------------------------


def idi(theta: float) -> float:
    """IDI placeholder: IDI = H(theta).

    STATUS: the project has not formally defined IDI. This is the minimal,
    transparent stand-in so the pipeline is testable end to end.

    Input : theta in [0, 1] (competency estimate).
    Output: [0, 1] (inherits entropy range, in bits).
    Meaning: how much uncertainty remains about this competency, i.e. how
      much there is to learn by probing it. Useful for question selection
      because it favours competencies we know least about.
    Limitations: depends on theta only -- ignores how many answers produced
      theta, and ignores the question itself. A real IDI will likely need
      one or both. To change the definition, replace only this function.
    """
    return competency_entropy(theta)


# ---------------------------------------------------------------------------
# 3. Difficulty fit  -- PROPOSED BASELINE
# ---------------------------------------------------------------------------


def difficulty_value(label: Union[str, Enum, None]) -> Optional[float]:
    """Map a categorical difficulty label to numeric d in [0, 1].

    Accepts a DifficultyLevel enum, a string (case/whitespace-insensitive),
    or None. Returns None for missing or unrecognised labels -- difficulty
    is never guessed or defaulted.
    """
    if isinstance(label, Enum):
        label = label.value
    if not isinstance(label, str):
        return None
    return DIFFICULTY_VALUE.get(label.strip().lower())


def difficulty_fit(theta: float, d: Optional[float]) -> Optional[float]:
    """DifficultyFit = 1 - |theta - d|.

    Inputs : theta in [0, 1]; d in [0, 1] (see DIFFICULTY_VALUE), or None.
    Output : 1.0 when difficulty exactly matches the competency estimate,
      decreasing linearly with the gap. In [0, 1] in general; with the default
      mapping (d in [0.25, 0.75]) the minimum is 0.25.
    Returns None if d is None (missing metadata -> cannot be scored).

    ASSUMPTION: theta and d are commensurable on one [0, 1] scale where higher
      means harder / more competent, and a question is most suitable when its
      difficulty is near the candidate's estimate. Motivated by the general
      idea that questions near a person's ability level are most informative
      (cf. item information in IRT), but theta here is an EMA of normalised
      scores, not an IRT ability, so this is a heuristic, not a derivation.
      The linear form was chosen because it has no free parameters.
    """
    _require_unit_interval("theta", theta)
    if d is None:
        return None
    _require_unit_interval("d", d)
    return 1.0 - abs(theta - d)


# ---------------------------------------------------------------------------
# 4. QScore  -- PROPOSED BASELINE
# ---------------------------------------------------------------------------


def qscore(
    idi_value: float,
    fit_value: Optional[float],
    idi_weight: float = DEFAULT_IDI_WEIGHT,
    fit_weight: float = DEFAULT_FIT_WEIGHT,
) -> Optional[float]:
    """QScore = idi_weight * IDI + fit_weight * DifficultyFit.

    Inputs : IDI in [0, 1], DifficultyFit in [0, 1] (or None), weights >= 0
      that sum to 1 (validated).
    Output : [0, 1]; higher = more attractive candidate question.
    Weighting: equal by default (no-prior assumption). NOT tuned on data and
      NOT a validated research result.
    Missing data: if DifficultyFit is None the question cannot be scored and
      None is returned -- no component is ever fabricated.
    """
    _require_unit_interval("idi_value", idi_value)
    for name, w in (("idi_weight", idi_weight), ("fit_weight", fit_weight)):
        _require_unit_interval(name, w)
    if abs((idi_weight + fit_weight) - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise ValueError("idi_weight + fit_weight must equal 1")
    if fit_value is None:
        return None
    _require_unit_interval("fit_value", fit_value)
    return idi_weight * idi_value + fit_weight * fit_value


# ---------------------------------------------------------------------------
# Convenience: score one candidate question, with every component visible
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateScore:
    """All intermediate values for one candidate question (explainability)."""

    theta: float
    entropy: float
    idi: float
    difficulty_value: Optional[float]
    difficulty_fit: Optional[float]
    qscore: Optional[float]


def score_candidate(
    difficulty: Union[str, Enum, None],
    competency_state: Optional[CompetencyState] = None,
    idi_weight: float = DEFAULT_IDI_WEIGHT,
    fit_weight: float = DEFAULT_FIT_WEIGHT,
) -> CandidateScore:
    """Compute theta -> H -> IDI -> DifficultyFit -> QScore for one question.

    competency_state is read-only here (never modified). If the question's
    competency has not been touched yet (None), the documented Stage 3.5
    prior THETA_INITIAL = 0.5 is used -- that is the model's defined initial
    state, not fabricated data.
    """
    theta = THETA_INITIAL if competency_state is None else competency_state.theta
    _require_unit_interval("theta", theta)

    entropy = competency_entropy(theta)
    idi_value = idi(theta)
    d = difficulty_value(difficulty)
    fit = difficulty_fit(theta, d)
    return CandidateScore(
        theta=theta,
        entropy=entropy,
        idi=idi_value,
        difficulty_value=d,
        difficulty_fit=fit,
        qscore=qscore(idi_value, fit, idi_weight, fit_weight),
    )


def rank_by_qscore(scored: Sequence[Tuple[str, Optional[float]]]) -> List[str]:
    """Order question IDs by QScore, highest first. Pure. Used by question_selector.

    Ties (equal after rounding to 12 decimals, to absorb float noise) are
    broken by question_id ascending, so the same input always gives the same
    order. Entries whose QScore is None are EXCLUDED, never given a default.
    """
    scorable = [(qid, round(q, _TIE_ROUNDING_DIGITS)) for qid, q in scored if q is not None]
    scorable.sort(key=lambda item: (-item[1], item[0]))
    return [qid for qid, _ in scorable]