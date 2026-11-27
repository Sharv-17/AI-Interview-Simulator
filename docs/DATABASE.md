# Database

Production persistence is **PostgreSQL** (JSONB support required) accessed through SQLAlchemy 2 and Alembic.
`JSONB` columns make the schema PostgreSQL-specific; there is no SQLite path. The in-memory
store (`MemoryInterviewStore`) is a separate implementation used for development and tests
and is not a database.

- Models: `backend/app/db/models.py`
- PostgreSQL store: `backend/app/db/postgres_store.py`
- Auth store: `backend/app/db/postgres_auth_store.py`
- Migrations: `backend/migrations/versions/0001`–`0003`
- URL source: the `DATABASE_URL` environment variable only (never `alembic.ini`)

## 1. Tables

### `users`

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | varchar(36) | primary key |
| `email` | varchar(254) | not null, unique `uq_users_email`, stored trimmed and lower-cased |
| `password_hash` | varchar(255) | not null, Argon2id |
| `is_active` | boolean | not null, default true |
| `is_email_verified` | boolean | not null, default false (always false today) |
| `created_at` | timestamptz | not null |
| `updated_at` | timestamptz | not null |

### `auth_sessions`

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | varchar(36) | primary key |
| `user_id` | varchar(36) | not null, FK → `users.id` `ON DELETE CASCADE` |
| `token_hash` | varchar(64) | not null, unique (SHA-256 hex of the cookie token) |
| `created_at` | timestamptz | not null |
| `expires_at` | timestamptz | not null |
| `revoked_at` | timestamptz | nullable |
| `last_used_at` | timestamptz | nullable, write-throttled |

Indexes: `ix_auth_sessions_user_created (user_id, created_at)`, `ix_auth_sessions_expires (expires_at)`.

### `candidates`

| Column | Type | Constraints |
| --- | --- | --- |
| `candidate_id` | varchar(36) | primary key |
| `display_name` | varchar(120) | nullable |
| `external_id` | varchar(120) | nullable, unique |
| `user_id` | varchar(36) | nullable, FK → `users.id` `ON DELETE SET NULL`, unique `uq_candidates_user_id` |
| `created_at` | timestamptz | not null |

`user_id` is nullable so guest candidates exist; PostgreSQL does not compare NULLs in a
unique constraint, so many guests coexist while one account owns at most one candidate.

### `questions`

A copy of the question bank, synced from `backend/data/question_bank.json` at startup.

| Column | Type | Constraints |
| --- | --- | --- |
| `question_id` | varchar(64) | primary key |
| `question_text` | text | not null |
| `topic` | varchar(120) | not null, indexed `ix_questions_topic` |
| `subtopic` | varchar(160) | nullable |
| `difficulty` | varchar(16) | not null |
| `question_type` | varchar(32) | not null |
| `competency` | varchar(160) | not null |
| `estimated_time_seconds` | integer | nullable |
| `review_status` | varchar(40) | nullable |
| `source` | varchar(64) | nullable |
| `tags` | jsonb | not null |
| `expected_concepts` | jsonb | not null |
| `evaluation_criteria` | jsonb | not null |
| `reference_answer` | text | nullable |
| `synced_at` | timestamptz | not null |

`legacy_category` and `previous_id` exist in the JSON bank but are **not** persisted as
columns.

### `interview_sessions`

| Column | Type | Constraints |
| --- | --- | --- |
| `interview_id` | varchar(36) | primary key |
| `candidate_id` | varchar(36) | nullable, FK → `candidates.candidate_id` `ON DELETE RESTRICT` |
| `topic` | varchar(120) | not null |
| `difficulty` | varchar(16) | not null |
| `question_count` | integer | not null, check `>= 1` |
| `current_question` | integer | not null |
| `status` | varchar(16) | not null, check in (`active`, `completed`) |
| `current_question_id` | varchar(64) | nullable, FK → `questions.question_id` |
| `question_started_at` | timestamptz | nullable |
| `question_time_limit_seconds` | integer | nullable |
| `question_grace_seconds` | integer | not null |
| `created_at` | timestamptz | not null |
| `completed_at` | timestamptz | nullable |

Constraints: `ck_interview_status`, `ck_interview_question_count`.
Indexes: `ix_interview_sessions_candidate_created (candidate_id, created_at)`,
`ix_interview_sessions_status (status)`.

### `interview_questions`

One row per question assigned to an interview, in order.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | bigserial | primary key |
| `interview_id` | varchar(36) | not null, FK → `interview_sessions.interview_id` `ON DELETE CASCADE` |
| `sequence` | integer | not null |
| `question_id` | varchar(64) | not null, FK → `questions.question_id` |
| `state` | varchar(16) | not null, check in (`active`, `answered`, `timed_out`) |
| `assigned_at` | timestamptz | not null |
| `closed_at` | timestamptz | nullable |
| `time_limit_seconds` | integer | not null |
| `grace_seconds` | integer | not null |

Unique: `uq_interview_question_sequence (interview_id, sequence)`,
`uq_interview_question_once (interview_id, question_id)`. Check: `ck_interview_question_state`.

### `candidate_answers`

| Column | Type | Constraints |
| --- | --- | --- |
| `answer_id` | varchar(36) | primary key |
| `interview_question_id` | bigint | not null, FK → `interview_questions.id` `ON DELETE CASCADE`, **unique** |
| `interview_id` | varchar(36) | not null, FK → `interview_sessions.interview_id` `ON DELETE CASCADE` |
| `question_id` | varchar(64) | not null (not a foreign key) |
| `answer_text` | text | not null |
| `answer_source` | varchar(16) | `text` or `voice` |
| `submission_reason` | varchar(32) | `candidate_submitted` or `timeout` |
| `language` | varchar(32) | nullable |
| `submitted_at` | timestamptz | not null |
| `elapsed_seconds` | double precision | not null |
| `time_limit_seconds` | integer | not null |
| `grace_seconds` | integer | not null |
| `timed_out` | boolean | not null |
| `evaluation_status` | varchar(16) | not null, check in (`pending`, `completed`, `failed`) |
| `evaluation_error` | varchar(80) | nullable |
| `evaluation_attempts` | integer | not null, default 0 |

Index: `ix_candidate_answers_interview (interview_id)`. The unique
`interview_question_id` enforces "one answer per question".

### `evaluation_results`

| Column | Type | Constraints |
| --- | --- | --- |
| `evaluation_id` | bigserial | primary key |
| `answer_id` | varchar(36) | not null, FK → `candidate_answers.answer_id` `ON DELETE CASCADE`, **unique** |
| `kind` | varchar(16) | not null |
| `evaluator` | varchar(120) | nullable |
| `overall_score` | double precision | not null, check 0–10 |
| `max_score` | double precision | not null |
| `details` | jsonb | not null (full serialized evaluation) |
| `reasoning_summary` | text | nullable, reviewer-only |
| `created_at` | timestamptz | not null |

Unique `answer_id` enforces "one evaluation per answer".

### `competency_history`

One row per evaluated answer; the audit trail of every θ update.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | bigserial | primary key |
| `interview_id` | varchar(36) | not null, FK → `interview_sessions.interview_id` `ON DELETE CASCADE` |
| `candidate_id` | varchar(36) | nullable, FK → `candidates.candidate_id` `ON DELETE RESTRICT` |
| `competency_id` | varchar(160) | not null |
| `answer_id` | varchar(36) | not null, FK → `candidate_answers.answer_id` `ON DELETE CASCADE`, **unique** |
| `question_id` | varchar(64) | not null |
| `previous_theta` | double precision | not null, check 0–1 |
| `new_theta` | double precision | not null, check 0–1 |
| `normalized_score` | double precision | not null |
| `last_score` | double precision | not null |
| `questions_attempted` | integer | not null |
| `recorded_at` | timestamptz | not null |

Indexes: `ix_competency_history_interview_competency (interview_id, competency_id, id)`,
`ix_competency_history_candidate_recorded (candidate_id, recorded_at)`.

### `integrity_events`

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | bigserial | primary key |
| `interview_id` | varchar(36) | not null, FK → `interview_sessions.interview_id` `ON DELETE CASCADE` |
| `question_id` | varchar(64) | nullable |
| `answer_id` | varchar(36) | nullable, FK → `candidate_answers.answer_id` `ON DELETE CASCADE` |
| `event_type` | varchar(40) | not null |
| `source` | varchar(10) | `client` or `server` |
| `client_occurred_at` | timestamptz | nullable, untrusted |
| `client_source` | varchar(64) | nullable |
| `received_at` | timestamptz | not null |
| `duration_ms` | integer | nullable |
| `detail` | jsonb | not null |

Index: `ix_integrity_events_interview_received (interview_id, received_at)`.

## 2. Relationships

```mermaid
erDiagram
    users ||--o| candidates : "owns at most one"
    users ||--o{ auth_sessions : "has sessions"
    candidates ||--o{ interview_sessions : "takes"
    interview_sessions ||--o{ interview_questions : "assigns"
    questions ||--o{ interview_questions : "is asked as"
    interview_questions ||--o| candidate_answers : "answered by"
    candidate_answers ||--o| evaluation_results : "scored by"
    candidate_answers ||--o| competency_history : "updates"
    interview_sessions ||--o{ competency_history : "records"
    interview_sessions ||--o{ integrity_events : "logs"
    candidate_answers ||--o{ integrity_events : "may reference"
```

There are no SQLAlchemy `relationship()` definitions; joins are written explicitly in
`postgres_store.py` and `postgres_auth_store.py`. Foreign keys are declared on the models and
in the migrations, and the unique constraints above are the last line of defence for the
interview rules.

### Delete behaviour

| Delete | Effect |
| --- | --- |
| User | `auth_sessions` cascade; `candidates.user_id` becomes NULL, so interviews survive as guest records |
| Candidate | `RESTRICT` from `interview_sessions` and `competency_history`; a candidate with history cannot be deleted silently |
| Interview | `interview_questions`, `candidate_answers`, `competency_history`, `integrity_events` cascade |
| Answer | `evaluation_results`, `competency_history` row and answer-linked integrity events cascade |
| Question | No delete path; `interview_questions` and `interview_sessions.current_question_id` reference it |

## 3. Migrations

| Revision | Purpose | Reversible |
| --- | --- | --- |
| `0001` initial schema | Creates the eight interview/candidate/question tables with checks, unique constraints and indexes | Yes (drops all) |
| `0002` nullable candidate | Makes `interview_sessions.candidate_id` and `competency_history.candidate_id` nullable for anonymous interviews | Yes — **deletes anonymous rows** on downgrade |
| `0003` users and auth sessions | Adds `users`, `auth_sessions`, `candidates.user_id` + FK + unique; purely additive | Yes — drops auth objects only, keeps candidates and interviews |

Commands (run from `backend/`):

```bash
export DATABASE_URL='postgresql+psycopg://user:password@host:5432/db'
alembic upgrade head
alembic current
alembic downgrade 0002
```

`migrations/env.py` reads `DATABASE_URL` and normalises a bare `postgresql://` URL to
`postgresql+psycopg://`. `alembic.ini` contains no credentials.

## 4. Initialisation and runtime behaviour

- **Startup** (`app/main.py` lifespan → `service.store.startup()`): `PostgresInterviewStore.startup()`
  upserts the question bank into `questions`; a missing or unmigrated schema makes this fail
  at startup. `check_ready()` is separate: it runs `SELECT 1` and backs `GET /health/ready`.
  A misconfigured store (for example `postgres` without `DATABASE_URL`) fails before serving.
- **Question sync** upserts every question from the JSON file; the JSON file remains the
  source of truth. Re-run `backend/scripts/convert_question_bank.py` after editing the CSV;
  a test fails when the JSON is stale.
- **Transactions:** each mutating request runs in one transaction. PostgreSQL takes
  `SELECT … FOR UPDATE NOWAIT` on the interview row; a concurrent writer gets
  `interview_busy` (409, `Retry-After: 1`) instead of waiting. Domain rejections commit
  their deliberate side effects (a timeout mark, an integrity indicator); other exceptions
  roll back.
- **Reports** are assembled by reading the interview, its questions, answers, evaluation
  results, competency state and integrity events.

## 5. Test database

`backend/tests/conftest.py` forces `STORAGE_BACKEND=memory`, `LLM_PROVIDER=mock`,
`ALLOW_MOCK_LLM=true` and removes `DATABASE_URL` before importing the app, so the default
suite never touches a real database.

The PostgreSQL suites (`test_postgres_store.py`, `test_auth_postgres.py`) are opt-in through
`TEST_DATABASE_URL`; without it they skip (39 tests). Each test creates a throw-away schema
(`test_pg_*`, `test_auth_*`) and drops it afterwards; `public` is untouched. A killed run can
leave a schema behind — drop `test_*` schemas by hand if that happens.

## 6. Data lifecycle and privacy notes

- Interviews, answers and reports persist indefinitely; there is no retention job, despite
  the privacy page's configurable `retentionPeriod` text in `src/siteConfig.js`.
- Audio is never written to the database: it is validated, transcribed in memory/temporary
  storage and discarded.
- Session tokens are stored only as SHA-256 hashes. `revoked_at` is a timestamp, so revoked
  sessions remain for audit until the row is deleted.
- Competency history is the only long-term per-candidate performance record. It stores
  estimates, not raw model output beyond `normalized_score`.
- Back up guest interviews before any future guest-claiming or merge change.
