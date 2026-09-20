"""Pydantic models for the competency state.

Every value here is an ESTIMATED competency level inferred from
observed answer performance — never an objective measure of the
candidate's true ability. See app/services/competency_state.py for how
these estimates are computed and updated.

Only theta (competency state) estimation is implemented at this stage.
Shannon entropy H(theta), IDI, DifficultyFit, and the final QScore are
NOT implemented yet — they belong to later stages of the research
architecture (theta -> H(theta) -> IDI -> DifficultyFit -> QScore).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

THETA_MIN = 0.0
THETA_MAX = 1.0
THETA_INITIAL = 0.5

# Fixed research design constant for the EMA update below. Do not change.
EMA_ALPHA = 0.15


class CompetencyState(BaseModel):
    """Estimated competency state for one competency, within one interview.

    theta is updated after each evaluated answer touching this
    competency using:

        theta_new = (1 - alpha) * theta_old + alpha * S

    where S is the answer's normalized score in [0,1] and
    alpha = EMA_ALPHA = 0.15.
    """

    competency_id: str
    theta: float = Field(..., ge=THETA_MIN, le=THETA_MAX)
    questions_attempted: int = Field(..., ge=0)
    last_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    last_updated: datetime


class CompetencyUpdate(BaseModel):
    """What changed in one competency after one evaluated answer.

    This describes a single update event — the before/after theta and
    the score that produced it — and is returned alongside the answer
    evaluation. It is not itself the persisted state; see
    CompetencyState above for that.
    """

    competency: str
    previous_theta: float = Field(..., ge=THETA_MIN, le=THETA_MAX)
    normalized_score: float = Field(..., ge=0.0, le=1.0)
    new_theta: float = Field(..., ge=THETA_MIN, le=THETA_MAX)
    questions_attempted: int = Field(..., ge=0)