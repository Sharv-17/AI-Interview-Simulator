# Mathematical Specification (Stage 3.7)

Pipeline: `θ → H(θ) → IDI → DifficultyFit → QScore`

Code: `backend/app/services/adaptive_metrics.py` (pure functions) and
`backend/app/services/competency_state.py` (θ). Tests:
`backend/tests/test_adaptive_metrics.py`.

**None of these formulas have been empirically validated.** Apart from θ,
they are implementation hypotheses.They are used by the question selector (section 6) but are not validated experimentally.

## Status of each component

| Component | Status | Notes |
|---|---|---|
| θ (competency estimate) | **Research definition** (project design) | Implemented in Stage 3.5, unchanged |
| H(θ) | Implementation assumption | Bernoulli baseline |
| IDI | **Proposed baseline** — project definition still open | Placeholder `IDI = H(θ)` |
| DifficultyFit | **Proposed baseline** | `1 − |θ − d|` |
| QScore | **Proposed baseline** | Equal-weight sum, weights not tuned |
| Empirical validation | **None** | |

## Notation

- `θ ∈ [0,1]` — *estimated* competency level for one competency (not a
  measure of true ability).
- `S ∈ [0,1]` — normalized answer score, `S = overall_score / 10`, clamped.
- `α = 0.15` — fixed EMA constant (project design).
- `d ∈ [0,1]` — numeric question difficulty (see mapping below).

## 1. θ (research definition, Stage 3.5)

```
θ_initial = 0.5
θ_new = (1 − α)·θ_old + α·S,   α = 0.15,   clamped to [0,1]
```
Example: θ_old = 0.5, 8/10 → S = 0.8 → θ_new = 0.545. Second answer 4/10 →
θ = 0.85·0.545 + 0.15·0.4 = 0.52325.

## 2. H(θ) — Bernoulli entropy baseline

```
H(θ) = −θ·log₂θ − (1−θ)·log₂(1−θ)        (bits)
```
- Range `[0,1]`; `H(0) = H(1) = 0` (handled by the limit; `log₂(0)` is never
  evaluated); maximum `H(0.5) = 1`; symmetric `H(θ) = H(1−θ)`.
- Inputs outside `[0,1]` or NaN raise `ValueError` (never silently clamped).
- Test value: `H(0.25) = 0.8112781244591328`.

**Assumption / limitation.** A single θ is not a probability distribution.
Treating θ as `P(success)` is an *operational choice*; it is not evidence
that competency is Bernoulli-distributed. Entropy here measures how
undetermined the estimate is, not the candidate's true uncertainty.

## 3. IDI — proposed placeholder (definition still open)

```
IDI(θ) = H(θ)
```
- Input θ; output `[0,1]`.
- Meaning: how much uncertainty remains about this competency, i.e. how much
  there is to learn by probing it.
- Why useful for selection: favours competencies we know least about.
- **Limitations:** depends only on θ — ignores how many answers produced θ
  and ignores the candidate question. A real IDI will likely need one or both.
- Replaceable by editing one function (`idi`).

## 4. DifficultyFit — proposed baseline

Difficulty mapping (explicit assumption; dataset labels are *not*
empirically calibrated):

| label | d |
|---|---|
| easy | 0.25 |
| medium | 0.50 |
| hard | 0.75 |

```
DifficultyFit(θ, d) = 1 − |θ − d|
```
- 1.0 when difficulty equals the competency estimate; falls linearly with the
  gap. With the default mapping the minimum is 0.25.
- Missing or unknown difficulty → `None` (never guessed).
- **Assumption:** θ and d are commensurable on one `[0,1]` scale (higher =
  harder / more competent), and questions near the candidate's level are most
  suitable. This is motivated by the general idea that items near a person's
  ability are most informative (cf. IRT item information), but θ is an EMA of
  normalized scores, not an IRT ability, so this is a heuristic, not a
  derivation. The linear form was chosen because it has no free parameters.

## 5. QScore — proposed baseline

```
QScore = w_idi·IDI + w_fit·DifficultyFit,   w_idi = w_fit = 0.5
```
- Components already in `[0,1]`, so no extra normalization. Output `[0,1]`.
- Weights: non-negative, sum to 1 (validated). Equal weights express "no prior
  preference" — they are **not tuned** and not a validated result.
- Missing data: if DifficultyFit is `None`, QScore is `None`; no component is
  fabricated. For a competency with no recorded state, the Stage 3.5 prior
  `θ = 0.5` is used (the model's defined initial state).
- Ties: candidates are ordered by QScore descending (compared after rounding to
  12 decimals to absorb float noise), then by `question_id` ascending.
  Unscorable (`None`) candidates are excluded from the ranking.
- IDI is competency-level and DifficultyFit is question-level, so the two
  components are not redundant.

## Worked example

θ = 0.25, question hard (d = 0.75):
`H = 0.81128`, `IDI = 0.81128`, `Fit = 1 − 0.5 = 0.5`,
`QScore = 0.5·0.81128 + 0.5·0.5 = 0.65564`.

## 6. How the selector uses these metrics (Phase 1)

Code: `backend/app/services/question_selector.py`. Nothing here changes the formulas above.

**Eligible candidates.** Same topic, not yet asked in this interview, and servable
(`review_status` is `reviewed`). `needs_manual_review` and `requires_coding_evaluation`
questions are never eligible.

**Cold start (first question).** With no competency history the interview's requested
`difficulty` picks the question (`baseline_score`: topic match, then difficulty match;
ties keep bank order). θ keeps its research prior of 0.5.

**Adaptive mode (every later question).** For each eligible question *q* with competency
*c* and difficulty value *d* (easy .25 / medium .5 / hard .75):

    θ_c    = current estimate for c  (0.5 if c has no history; invalid values are ignored -> 0.5)
    IDI    = H(θ_c)
    Fit    = 1 − |θ_c − d|
    QScore = 0.5·IDI + 0.5·Fit

Candidates are ranked by QScore (descending), ties broken by `question_id` (ascending), so
the result is deterministic and independent of storage order. There is no randomness.

**What each metric does to the choice.**
- *DifficultyFit* chooses the difficulty: it is highest when *d* is closest to θ, so a
  rising θ moves the interview from medium toward hard, and a falling θ toward easy.
- *IDI = H(θ)* is a property of the competency, not of the question. It only changes the
  ranking when eligible questions belong to *different* competencies: a less-certain
  competency (θ near 0.5) outranks a nearly-certain one (θ near 0 or 1) at equal
  fit. In an interview that covers a single competency IDI is the same for every
  candidate and does not affect the order. (Today competency = category, and an
  interview covers one category, so IDI has no effect on the order there.)
- The requested interview difficulty affects only the first question.

**Anti-streak guard.** If the last 3 questions had the same difficulty and a different
difficulty is available, only those are considered. So the selector never asks more than 3
same-difficulty questions in a row while an alternative exists. The limit of 3 is an
implementation assumption. It is a hard constraint, not a QScore effect: it can override
the QScore ranking.

**Fallbacks.** No history -> baseline. Competency with no state -> prior 0.5. Invalid θ ->
prior 0.5 (warning logged). Nothing scorable -> baseline ordering. No eligible question
-> none (the interview completes).

**Observed behaviour (8-question simulation, System Design, requested medium, placeholder
evaluator).** A candidate scoring 3/10 each time had difficulty sequence M M M E M M M E
(θ 0.47 -> 0.354). A candidate scoring 8/10 each time had M M M H H H M H (θ 0.545 -> 0.718).
Because α = 0.15 makes θ move slowly, adaptation within a short interview is gradual,
and some switches (the lone E above) come from the anti-streak guard rather than from θ.

## Open questions for the research design

1. The intended definition of IDI (it should likely use evidence count and/or
   the question, not θ alone).
2. Whether difficulty labels need empirical calibration.
3. How QScore weights should be chosen (and validated).
4. Whether a Bernoulli view of θ is adequate, or competency should be
   represented as a distribution (e.g. Beta) so entropy is principled.
5. Whether a competency should be a category (current) or a subcategory. A finer
   competency would let IDI influence question order within one interview.   