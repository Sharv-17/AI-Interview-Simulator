# 0003 — Questions come from a reviewed static bank, not runtime generation

**Status:** Accepted (implemented)

## Context

The original plan described an AI generating each interview question from role, experience
and previous performance. The implementation needed reproducible interviews, an answer key
for rubric scoring, and a way to keep unvalidated or unservable questions away from
candidates.

## Decision

- Questions live in `backend/data/question_bank.csv` and are converted to
  `question_bank.json` by `scripts/convert_question_bank.py`. The JSON is the runtime source
  of truth and is copied into the `questions` table at startup.
- The bank contains 827 questions across 20 topics, three difficulties and five question
  types, with `reference_answer`, `expected_concepts`, `evaluation_criteria`,
  `estimated_time_seconds` and `review_status`.
- Only `review_status = reviewed` questions are selectable (707 of 827).
  `needs_manual_review` (100) and `requires_coding_evaluation` (20) stay lookup-able but are
  never asked. Coding questions are gated because no execution sandbox exists; they would
  score zero.
- The selector chooses among eligible bank questions; no component generates question text at
  request time.

## Consequences

- Interviews are reproducible and scores are comparable within the same question set.
- The bank is finite: after enough interviews a candidate can exhaust the unseen questions of
  a topic, at which point cooldown rotation reuses the least recently assigned ones.
- Reviewed *hard* questions are scarce in some topics (none in Networking and Software Design
  & Practices), so the selector falls back to other difficulties.
- New questions must be authored and reviewed offline; the JSON must be regenerated and a
  test enforces freshness.
- Rubric evaluation can rely on per-question reference material, which runtime generation
  would have to produce as well.

## Evidence

- `backend/data/question_bank.csv`, `backend/data/question_bank.json`,
  `backend/scripts/convert_question_bank.py`.
- `backend/app/schemas/question.py` — `ReviewStatus`, `Question.is_servable`,
  `QuestionPublic` (no answer key).
- `backend/app/services/question_selector.py` — filters on `is_servable`.
- `backend/tests/test_question_bank_v2.py`, `tests/test_questions.py`.

## Alternatives considered

- **Runtime LLM generation:** no reproducibility, no stable answer key, unvetted difficulty,
  and a second paid call per question.
- **Serving all bank questions:** would include unreviewed and coding questions that cannot
  be scored fairly.
