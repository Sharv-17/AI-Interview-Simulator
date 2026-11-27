# 0005 — Question cooldown is scoped by candidate and topic

**Status:** Accepted (implemented)

## Context

Adaptive ranking alone can re-serve the same questions across a candidate's interviews: the
bank is finite and QScore depends mostly on difficulty. Repeating a question the candidate
has already seen inflates practice value and makes progress hard to interpret.

## Decision

- Before ranking, the selector receives `encountered`: a map of `question_id → most recent
  assignment time` for the same `candidate_id` **and** the interview's topic.
- Priority: never-assigned questions first; when none remain, the least recently assigned
  questions; seen questions are never excluded permanently.
- Every assignment counts, whether or not it was answered (abandoned and timed-out
  interviews included).
- No new table is introduced. PostgreSQL derives history from existing `interview_questions`
  rows joined through `interview_sessions`; the in-memory store derives it from its sessions.
- Anonymous interviews have no candidate and therefore no history; cooldown does not apply.
- `encountered` only reorders candidates after servability, no-repeat-within-interview,
  the anti-streak guard and the requested initial difficulty have been applied.

## Consequences

- A returning candidate sees fresh questions first, then the oldest ones again.
- `POST /interview/{id}/next` needs one extra history read (PostgreSQL) or a session scan
  (memory). `GET /interview/{id}` does not.
- Cooldown cannot improve an anonymous interview, which is the price of not requiring an
  account.
- Deleting a candidate is restricted while interviews exist, so history cannot disappear
  silently.

## Evidence

- `backend/app/services/question_selector.py` — `Encountered`, `_cold_start_choice`,
  `_adaptive_choice`, `select_next_question`.
- `backend/app/services/interview_engine.py` — `encountered` passed into each session.
- `backend/app/services/interview_store.py` — `_question_history` for the memory store.
- `backend/app/db/postgres_store.py` — history query through `interview_sessions` and
  `interview_questions`.
- `backend/app/services/interview_service.py` — `edit(..., with_history=True)` only when
  advancing.
- `backend/tests/test_rotation.py`.

## Alternatives considered

- **Global (all candidates) history:** would starve popular questions for new candidates.
- **Dedicated `question_history` table:** duplicates data that `interview_questions` already
  holds, and needs a migration plus backfill.
- **Permanent exclusion:** eventually leaves a topic with no eligible question.
