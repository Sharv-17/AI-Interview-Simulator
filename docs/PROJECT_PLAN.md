# Project Plan

Status of the project as implemented on 2026-11-27. Every "complete" item below is backed by
source code and tests; anything aspirational is under [Remaining work](#7-remaining-work).

## 1. Vision

Give students and job seekers realistic technical-interview practice that adapts to their
performance and explains its scores, without requiring an account, an interviewer or a
scheduled session.

## 2. Objectives

1. Run a complete interview (setup → questions → answers → report) in the browser.
2. Choose each next question from the candidate's estimated competency rather than a fixed
   list, while keeping the interview fair and explainable.
3. Score free-text answers against a per-question rubric and show specific feedback.
4. Enforce a per-question time budget server-side and record integrity indicators for review.
5. Keep guest interviews frictionless and add optional accounts with persistent history.
6. Keep every number honest: label estimates, never fabricate a score, never present a
   hypothesis as a validated result.

## 3. Functional requirements

| ID | Requirement | Status |
| --- | --- | --- |
| FR-1 | Start an interview with topic, starting difficulty and 1–20 questions | Implemented |
| FR-2 | Serve questions from a reviewed bank, never exposing the answer key | Implemented |
| FR-3 | Accept typed answers, with optional voice recording and transcript review | Implemented |
| FR-4 | Reject duplicate, late and not-current submissions | Implemented |
| FR-5 | Evaluate a free-text answer against a rubric and store five criterion scores | Implemented |
| FR-6 | Update a per-competency estimate once per evaluated answer | Implemented |
| FR-7 | Select the next question adaptively (QScore, cooldown, anti-streak) | Implemented |
| FR-8 | Auto-complete the interview after the requested question count or when the topic is exhausted | Implemented |
| FR-9 | Show a report with per-question scores, feedback, timing, competency and integrity counts | Implemented |
| FR-10 | Track time server-side with a grace period; mark timeouts | Implemented |
| FR-11 | Record copy/paste/tab/focus events as indicators only | Implemented |
| FR-12 | Register, sign in, sign out, restore a session from a cookie | Implemented |
| FR-13 | Protect account-owned interviews and reports from other accounts | Implemented |
| FR-14 | Show account history and per-area competency progress | Implemented |
| FR-15 | Generate interview questions with an LLM at runtime | **Not implemented** (static bank) |
| FR-16 | Analyse speaking rate, filler words and pauses | **Not implemented** |
| FR-17 | Run behavioural or role-play interviews | **Not implemented** |
| FR-18 | Execute and test coding answers | **Not implemented** (no sandbox; coding questions gated out) |
| FR-19 | Email verification and password recovery | **Not implemented** |
| FR-20 | Claim a guest interview into an account | **Not implemented** by design; see [AUTHENTICATION.md](AUTHENTICATION.md#7-guest-identity-and-history-claiming) |

## 4. Non-functional requirements

| Area | Position |
| --- | --- |
| Privacy | No audio stored or logged; no clipboard content; only question context and answer text sent to the LLM; no candidate identity sent |
| Security | Argon2id hashes, hashed session tokens, HttpOnly/SameSite cookies, CSRF origin checks, parameterised SQL, answer key redaction |
| Integrity of data | One answer, one evaluation, one competency update per question, enforced by domain rules, row locks and unique constraints |
| Explainability | Every adaptive component is a named function with documented assumptions; intermediate values are exposed in tests and scorer objects |
| Honesty | Scores cannot be produced without a working evaluator; estimates are labelled as estimates |
| Portability | PostgreSQL is the only production store; the in-memory store exists for tests and local work |
| Performance | Not benchmarked. No load test exists; the design is synchronous and single-interview scoped |

## 5. Completed milestones

| Milestone | What was delivered |
| --- | --- |
| Question bank and retrieval | 827-question CSV → JSON pipeline, repository, public/private question schemas, review-status gating |
| Answer lifecycle | Record-then-evaluate, duplicate protection, retries, timing metadata, progression rules |
| Rubric evaluation | Provider abstraction (Anthropic, OpenAI-compatible), strict JSON schema, bounded retries, typed failures, backend-computed overall score |
| Competency state | Per-interview θ with EMA (α = 0.15), persisted `competency_history` |
| Timer and integrity | Per-question limit plus grace, server-authoritative timing, client and server indicators |
| Adaptive selection | H(θ), IDI, DifficultyFit, QScore, cold start, cooldown rotation, anti-streak guard, id-ordered tie groups with a seeded random final choice |
| Voice answers | Audio validation from content, format detection, transcription service with timeouts, transcript review |
| PostgreSQL persistence | 10-table schema, Alembic revisions 0001–0003, transactional change replay, question sync at startup |
| Accounts | Registration, login, logout, `/me`, ownership checks, rate limiting, CSRF |
| Frontend SPA | Login-first routing, guest flow, interview room with timer/voice/integrity, report, dashboard, legal pages |
| Dashboard progress | Account history plus per-area estimate from the newest interview and in-interview movement |

## 6. Partially completed

- **Adaptive model:** all components exist and are tested, but none is empirically validated.
  IDI is a placeholder (`IDI = H(θ)`), difficulty labels are uncalibrated, weights are
  untuned. See [MATHEMATICAL_SPEC.md](MATHEMATICAL_SPEC.md).
- **Voice:** transcription exists; quality is unmeasured, the provider is an optional
  install, and no communication metrics are derived from the audio.
- **Deployment:** same-origin proxy rules are documented and the dev-proxy flow was
  exercised, but no deployed environment has been checked; `vercel.json` and
  `src/siteConfig.js` still hold placeholder values, so a launch checklist run fails by
  design.
- **Retention:** the privacy page states that interview data is deleted after
  `retentionPeriod`, but no retention job exists. Either the copy or a deletion job must
  change before launch.
- **Rate limiting:** in-process. Behind several workers the effective limit multiplies; a
  restart clears counters.
- **Reports:** complete for a single interview. There is no cross-interview comparison because
  θ resets per interview.
- **Question coverage:** reviewed *hard* questions are scarce in some topics, so the selector
  falls back to other difficulties.

## 7. Remaining work

Ordered by dependency and value:

1. **Real evaluator verification.** Exercise the Anthropic and OpenAI-compatible providers
   against live APIs, measure latency and failure rates, and record the results.
2. **Calibrate or replace the adaptive baseline.** Collect answer data, test whether QScore
   ordering beats random or difficulty-only selection, and only then claim adaptation works.
3. **Question generation** (if still wanted): generate candidates offline, review them, and
   add them to the bank. Runtime generation would make scores non-reproducible.
4. **Communication metrics** from the existing transcript/audio: speaking duration is already
   returned; rate, pauses and filler words would need explicit, documented definitions.
5. **Guest-history claiming**, using the capability-token design in
   [AUTHENTICATION.md](AUTHENTICATION.md#7-guest-identity-and-history-claiming). Requires a
   frontend change and a migration for the token hash.
6. **Account lifecycle:** email verification, password reset, account deletion, session
   listing/revocation UI.
7. **Distributed rate limiting** (shared store) before running multiple workers.
8. **Coding-question sandbox** with resource limits, then re-review the 20 gated coding
   questions.
9. **Deployment hardening:** real domains, proxy body limit for audio, CORS decision if the
   API ever leaves the frontend's site, and a load test.
10. **Frontend tests** (component/integration) — currently none.

## 8. Known limitations

- The backend cannot observe the browser; the timer display, auto-submit and tab/focus
  events are client-reported. The server independently validates timing but cannot detect a
  client that never reports anything.
- An interview that is never revisited stays `active`; there is no expiry or cleanup job.
- Anonymous interviews have no history, so cooldown rotation cannot apply to them.
- A guest interview or guest candidate is readable by anyone who knows its id. This is the
  documented guest contract, not an accident.
- `estimated_time_seconds` varies by question type (scenario up to 240 s, system design up
  to 900 s), so long questions can legitimately consume the whole budget; timeouts are
  flagged, not blocked.
- The in-memory store loses everything on restart; it is selected explicitly.
- No license file exists.

## 9. Future enhancements (not scheduled)

- Company- or role-specific interview tracks built from the same bank.
- Reviewer/coach view over a shared report link with explicit consent.
- Per-question analytics (difficulty vs. observed score) once enough data exists.
- Export of a report as PDF beyond the browser print dialog.
- Accessibility audit and keyboard-only interview flow.
- Internationalisation of the UI copy.
