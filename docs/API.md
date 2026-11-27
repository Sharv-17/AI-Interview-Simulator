# API Reference

Base path: the backend serves every route below at the root of its own origin (for example
`http://localhost:8000`). The SPA talks to `/api/*`, which the dev server and the production
rewrite strip before forwarding, except `/api/v1/*`, which keeps its prefix.

- Interactive schema: `GET /docs` (Swagger UI) and `GET /openapi.json`.
- `GET /` redirects to `/docs`.
- JSON request and response bodies, except the multipart `POST /interview/{id}/transcribe`.

## 1. Endpoint inventory

### Interview

| Method | Path | Auth | Success |
| --- | --- | --- | --- |
| POST | `/interview/start` | none for guests; an account may only send its own `candidate_id` | `201` interview |
| GET | `/interview/{interview_id}` | interview access rule¹ | `200` interview |
| POST | `/interview/{interview_id}/answer` | interview access rule¹ | `200` scored, `202` saved but not scored |
| POST | `/interview/{interview_id}/answer/retry-evaluation` | interview access rule¹ | `200` / `202` |
| POST | `/interview/{interview_id}/transcribe` | interview access rule¹ | `200` transcript |
| POST | `/interview/{interview_id}/next` | interview access rule¹ | `200` interview |
| POST | `/interview/{interview_id}/integrity-events` | interview access rule¹ | `200` count |
| GET | `/interview/{interview_id}/competency` | interview access rule¹ | `200` map of competency states |
| GET | `/interview/{interview_id}/report` | interview access rule¹ | `200` report |

¹ A guest interview (no owning account) is readable by anyone holding its id. An interview
owned by an account requires that account's session: missing session → `401
authentication_required`, another account → `404 Interview not found`.

### Questions

| Method | Path | Auth | Success |
| --- | --- | --- | --- |
| GET | `/questions` | none | `200` array of `QuestionPublic` |
| GET | `/questions/{question_id}` | none | `200` `QuestionPublic`, `404` `Question not found` |

Query filters for `/questions`: `topic` (string) and `difficulty` (`easy` \| `medium` \|
`hard`). Both are optional and combine as an AND.

### Candidates

| Method | Path | Auth | Success |
| --- | --- | --- | --- |
| POST | `/candidates` | none | `201` candidate; `409` duplicate `external_id` |
| GET | `/candidates/{candidate_id}` | candidate access rule² | `200` candidate |
| GET | `/candidates/{candidate_id}/interviews` | candidate access rule² | `200` array, oldest first |
| GET | `/candidates/{candidate_id}/competency-history` | candidate access rule² | `200` array of updates |

² A guest candidate is readable by id. An account-owned candidate requires that account's
session: missing → `401`, other account → `404 Candidate not found`.

### Accounts (`/api/v1`)

| Method | Path | Auth | Success |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | none | `201` user |
| POST | `/api/v1/auth/login` | none | `200` user + session cookie |
| POST | `/api/v1/auth/logout` | cookie, same-origin | `204` |
| GET | `/api/v1/auth/me` | cookie | `200` user |
| GET | `/api/v1/candidates/me` | cookie | `200` the account's candidate |
| GET | `/api/v1/interviews/me` | cookie | `200` array, oldest first |

### Operational

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | liveness, `{"status":"ok"}` |
| GET | `/health/ready` | `200 {"status":"ok","storage":"postgres"}` or `503 storage_unavailable` |

## 2. Schemas

### Interview

`InterviewStartRequest`

```json
{
  "candidate_id": "optional, max 64 chars",
  "topic": "Python",
  "difficulty": "easy | medium | hard",
  "question_count": 5
}
```

`question_count` is an integer from 1 to 20. `topic` is trimmed and must not be blank.

`InterviewResponse`

```json
{
  "interview_id": "uuid",
  "topic": "Python",
  "difficulty": "medium",
  "question_count": 5,
  "current_question": 1,
  "current_question_id": "SWQ-0123",
  "status": "active | completed",
  "candidate_id": "uuid or null",
  "question_state": "active | evaluation_pending | evaluation_failed | evaluated | timed_out | null",
  "next_action": "answer | retry_evaluation | advance | completed | none",
  "question_started_at": "2026-11-27T10:00:00Z",
  "question_time_limit_seconds": 90,
  "grace_seconds": 15,
  "deadline_at": "2026-11-27T10:01:45Z",
  "seconds_remaining": 62.5
}
```

Timing fields are `null` when no question is current. `seconds_remaining` is capped at zero.

### Answers

`AnswerSubmitRequest`

```json
{
  "question_id": "SWQ-0123",
  "answer_text": "…",
  "answer_source": "text | voice",
  "language": "python",
  "submission_reason": "candidate_submitted | timeout",
  "integrity_events": [
    { "event_type": "paste", "occurred_at": "2026-11-27T10:00:30Z", "source": "answer_box", "duration_ms": null }
  ]
}
```

- `answer_text`: required, non-blank, at most `MAX_ANSWER_CHARS` (default 20,000).
- `language`: optional, max 32 characters; meaningful only for coding questions.
- `integrity_events`: at most `MAX_INTEGRITY_EVENTS_PER_REQUEST` (50) per request.
- `submission_reason`: metadata only; the server decides timing itself.

`AnswerSubmitResponse`

```json
{
  "interview_id": "uuid",
  "question_id": "SWQ-0123",
  "answer_id": "uuid",
  "evaluation_status": "completed | pending | failed",
  "evaluation": { "...": "ConceptualEvaluation or CodingEvaluation, or null" },
  "competency_update": {
    "competency": "Python",
    "previous_theta": 0.5,
    "normalized_score": 0.8,
    "new_theta": 0.545,
    "questions_attempted": 1
  },
  "timing": {
    "question_started_at": "2026-11-27T10:00:00Z",
    "submitted_at": "2026-11-27T10:00:42Z",
    "time_limit_seconds": 90,
    "grace_seconds": 15,
    "elapsed_seconds": 42.0,
    "timed_out": false,
    "submission_reason": "candidate_submitted",
    "integrity_events": []
  },
  "answer_source": "text",
  "retry_allowed": false,
  "evaluation_error": null,
  "next_action": "advance"
}
```

`evaluation` and `competency_update` are only present when `evaluation_status` is
`completed`. Otherwise the endpoint answers `202`, `evaluation_error` carries a safe
`{code, message}`, and `retry_allowed` says whether
`POST /answer/retry-evaluation` may be called.

`retry-evaluation` accepts `{"question_id": "..."}`. It is idempotent: an already-scored
answer returns its stored result without calling the evaluator or updating competency again.
After `1 + MAX_EVALUATION_RETRIES` (default 6) failed attempts, the answer can no longer be
retried and the interview may advance.

`ConceptualEvaluation` (rubric-based, also used for scenario/system_design/debugging)

```json
{
  "question_id": "SWQ-0123",
  "question_type": "conceptual",
  "overall_score": 8.0,
  "max_score": 10,
  "feedback": "…",
  "strengths": ["…"],
  "weaknesses": ["…"],
  "evaluator": "anthropic:claude-sonnet-5-5",
  "evaluation_status": "completed",
  "technical_score": 8,
  "relevance_score": 9,
  "completeness_score": 7,
  "clarity_score": 8,
  "conceptual_understanding_score": 8,
  "correct_concepts": ["…"],
  "missing_concepts": ["…"],
  "incorrect_concepts": []
}
```

`overall_score` is the rounded mean of the five integer criteria. `reasoning_summary` is
stored for reviewers and excluded from candidate responses.

### Transcription

`POST /interview/{id}/transcribe` — `multipart/form-data`:

| Field | Type | Notes |
| --- | --- | --- |
| `question_id` | text | must be the current, unanswered question |
| `audio` | file | WebM, Ogg, MP4/M4A, WAV or MP3, detected from content |

`200`:

```json
{ "interview_id": "uuid", "question_id": "SWQ-0123", "transcript": "…", "duration_seconds": 12.4 }
```

A successful transcription changes no interview state. The pre-check applies the same rules as
answering, so it can still reject the request and mark a question timed out. Errors use
`{"detail": {"code", "message"}}`:

| Status | Code |
| --- | --- |
| 400 | `empty_audio`; a stale/unanswered question check returns the answer API's plain-detail `400`/`409` |
| 413 | `audio_too_large` |
| 415 | `unsupported_audio_format` |
| 422 | `unreadable_audio`, `audio_too_long`, `no_speech_detected` |
| 502 | `transcription_failed` |
| 503 | `transcription_unavailable` |
| 504 | `transcription_timeout` |

### Integrity events

`POST /interview/{id}/integrity-events`

```json
{
  "question_id": "SWQ-0123",
  "events": [
    { "event_type": "copy", "occurred_at": null, "source": "answer_box", "duration_ms": null }
  ]
}
```

`event_type` is one of `copy`, `paste`, `tab_switch`, `focus_loss`, `focus_gain`. `events`
has 1–50 items; `duration_ms` is limited to one day. `question_id` defaults to the current
question. Response: `{"interview_id": "...", "question_id": "...", "recorded": 1}`.

### Competency

`GET /interview/{id}/competency` returns a map keyed by competency id:

```json
{
  "Python": {
    "competency_id": "Python",
    "theta": 0.545,
    "questions_attempted": 1,
    "last_score": 0.8,
    "last_updated": "2026-11-27T10:00:43Z"
  }
}
```

All values are estimates within this interview only.

`competency-history` entries:

```json
{
  "interview_id": "uuid",
  "competency_id": "Python",
  "answer_id": "uuid",
  "question_id": "SWQ-0123",
  "previous_theta": 0.5,
  "new_theta": 0.545,
  "normalized_score": 0.8,
  "questions_attempted": 1,
  "recorded_at": "2026-11-27T10:00:43Z"
}
```

### Questions

`QuestionPublic` deliberately omits the answer key:

```json
{
  "question_id": "SWQ-0123",
  "question_text": "…",
  "topic": "Python",
  "subtopic": "…",
  "difficulty": "medium",
  "question_type": "conceptual | scenario | system_design | debugging | coding",
  "competency": "Python",
  "tags": ["…"]
}
```

`reference_answer`, `expected_concepts` and `evaluation_criteria` are never returned by any
endpoint.

### Candidates

`CandidateCreate`: `{"display_name": "optional, max 120", "external_id": "optional, unique, max 120"}`.

`CandidateView`: `{candidate_id, display_name, external_id, created_at}`.

`InterviewSummary`: `{interview_id, candidate_id, topic, difficulty, question_count,
current_question, status, created_at, completed_at}`.

### Report

`GET /interview/{id}/report` returns:

```json
{
  "interview": { "...": "InterviewSummary" },
  "questions": [
    {
      "sequence": 1, "question_id": "SWQ-0123", "question_text": "…", "topic": "Python",
      "difficulty": "medium", "question_type": "conceptual", "state": "answered",
      "assigned_at": "…", "closed_at": "…", "time_limit_seconds": 90, "grace_seconds": 15
    }
  ],
  "answers": [
    {
      "answer_id": "uuid", "question_id": "SWQ-0123", "answer_text": "…",
      "answer_source": "text", "submission_reason": "candidate_submitted", "language": null,
      "submitted_at": "…", "elapsed_seconds": 42.0, "time_limit_seconds": 90,
      "grace_seconds": 15, "timed_out": false, "evaluation_status": "completed",
      "evaluation_attempts": 1, "evaluation_error": null, "evaluator": "…",
      "evaluation": { "...": "…" }, "reasoning_summary": "…", "competency_update": { "...": "…" }
    }
  ],
  "competency": { "Python": { "...": "CompetencyState" } },
  "integrity_events": [
    {
      "event_type": "paste", "source": "client", "question_id": "SWQ-0123",
      "answer_id": "uuid", "client_occurred_at": "…", "received_at": "…",
      "duration_ms": null, "detail": {}
    }
  ],
  "integrity_summary": { "paste": 1, "focus_loss": 2 }
}
```

The report contains answers, scores, timing and integrity counters. It never contains
`reference_answer`, `expected_concepts` or `evaluation_criteria`.

### Accounts

`register`: `{"email": "…", "password": "…", "display_name": "optional"}`.

`login`: `{"email": "…", "password": "…"}`.

`UserResponse`:

```json
{
  "user_id": "uuid",
  "email": "ada@example.com",
  "is_active": true,
  "is_email_verified": false,
  "candidate_id": "uuid",
  "created_at": "2026-11-26T12:00:00Z"
}
```

The session token is only in the `Set-Cookie` header, never in JSON. Registration does not
sign the caller in. See [AUTHENTICATION.md](AUTHENTICATION.md) for the cookie contract.

## 3. Status and error codes

| Status | When |
| --- | --- |
| 200 | Read or successful mutation |
| 201 | Interview started, candidate created, account registered |
| 202 | Answer saved but not scored (`evaluation_status` pending/failed) |
| 204 | Logout |
| 400 | Not the current question, unsupported question type |
| 401 | `authentication_required` (missing/expired/revoked session, inactive account), `invalid_credentials` |
| 403 | `csrf_rejected`; `account_inactive` (login with the correct password for a disabled account) |
| 404 | Interview, candidate or question not found |
| 409 | Duplicate answer, question not answered, deadline passed, evaluation pending/exhausted, interview not active/busy, email already registered |
| 413 / 415 / 422 | Audio size/format, transcription validation, request validation |
| 429 | `rate_limited` with `Retry-After` |
| 502 / 503 / 504 | Transcription failed/unavailable/timeout, `storage_unavailable` |

Error shapes:

```jsonc
{ "detail": "Interview not found" }                                  // legacy plain string
{ "detail": { "code": "evaluation_pending", "message": "..." } }     // coded
{ "detail": [ { "loc": ["body","question_count"], "msg": "..." } ] }  // 422 validation
```

Coded domain errors: `question_deadline_passed`, `evaluation_pending`, `no_answer_recorded`,
`evaluation_retries_exhausted`, `interview_busy`, `csrf_rejected`, `authentication_required`,
`invalid_credentials`, `account_inactive`, `email_already_registered`, `rate_limited`,
`storage_unavailable`.

## 4. Caching and CORS

- Every response under `/api/v1/` is sent with `Cache-Control: no-store` and
  `Pragma: no-cache`, including errors.
- The backend registers no `CORSMiddleware`. Calling it from another origin requires adding
  CORS with credentials and explicit origins. The supported deployment keeps the browser on
  one origin through a proxy; see [AUTHENTICATION.md](AUTHENTICATION.md#8-environment-variables).
- Cookie-authenticated state-changing requests are origin-checked (`Sec-Fetch-Site`,
  `Origin`). `login` and `register` are not cookie-authenticated and are therefore not
  origin-checked.
