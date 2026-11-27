# 0001 — Competency estimate is a per-interview EMA with α = 0.15

**Status:** Accepted (implemented, not empirically validated)

## Context

Question selection needs a numeric estimate of how well the candidate is doing on each
competency. It must react to recent answers without swinging on a single score, must work
from the first answer (no pre-populated history), and must be explainable and testable.

## Decision

For each competency touched by an evaluated answer, keep `θ ∈ [0,1]` and update it with an
exponential moving average:

```
θ_new = (1 − α)·θ_old + α·S        S = overall_score / 10 (clamped)
α = EMA_ALPHA = 0.15
θ_initial = 0.5, result clamped to [0,1]
```

`α` is a fixed research-design constant, not an environment variable. Competencies are
created lazily on first use, and state is owned by one interview
(`CompetencyStateStore` per `InterviewSession`), never shared globally.

## Consequences

- Adaptation is gradual: with α = 0.15, one answer moves θ by at most 0.075 from the neutral
  prior. In an 8-question interview, difficulty changes are therefore modest — observed
  sequences in [MATHEMATICAL_SPEC.md](../MATHEMATICAL_SPEC.md) move between easy/medium/hard
  only a few times, and some switches come from the anti-streak guard rather than θ.
- θ resets to 0.5 at every new interview. It is **not** a longitudinal ability measure, so
  the dashboard must not compare θ across interviews; it reports the newest interview only.
- Changing α changes the product's behaviour. It requires updating the constant, the tests,
  `MATHEMATICAL_SPEC.md` and this record.

## Evidence

- `backend/app/schemas/competency.py` — `EMA_ALPHA = 0.15`, `THETA_INITIAL = 0.5`.
- `backend/app/services/competency_state.py` — `apply_ema`, lazy initialisation, clamping.
- `backend/app/services/interview_engine.py` — one `CompetencyStateStore` per session;
  `apply_evaluation` updates it exactly once per answer.
- `backend/tests/test_competency.py` — asserts the formula and the 0.545 example.

## Alternatives considered

- **Plain average of all answers:** ignores recency and moves slowly in long interviews.
- **Last score only:** noisy; one bad answer would dominate selection.
- **IRT / Beta distribution:** more principled, but needs calibration data and a model the
  project does not have. Entropy is therefore the Bernoulli stand-in documented in
  [MATHEMATICAL_SPEC.md](../MATHEMATICAL_SPEC.md#2-h%CE%B8--bernoulli-entropy-baseline), not a
  derived posterior.
