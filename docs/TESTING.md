# Testing

The backend has a substantial pytest suite. The frontend has no test framework: its
verification is linting, a production build and a launch checklist.

## 1. Running the backend suite

From `backend/` with the project virtualenv active:

```bash
python -m pytest -q              # full suite, in-memory storage, mock LLM
python -m pytest -q -rs          # include skip reasons
python -m pytest -q tests/test_auth.py
python -m pytest -q -k competency -v
```

Measured on 2026-11-27 (Windows, Python 3.11 virtualenv in `../.venv`):

```
451 tests collected
412 passed, 39 skipped, 1 warning in 25.00s
```

The 39 skips are the opt-in PostgreSQL modules, skipped with
`TEST_DATABASE_URL is not set (PostgreSQL integration tests are opt-in)`.

### PostgreSQL suites

```bash
TEST_DATABASE_URL='postgresql+psycopg://user:password@host:5432/scratch' \
  python -m pytest -q tests/test_postgres_store.py tests/test_auth_postgres.py
```

Each test creates and drops its own schema (`test_pg_*`, `test_auth_*`), so `public` is never
touched. A database that may be wiped is required. `tests/test_auth_postgres.py` also runs
`alembic upgrade 0002 → head → downgrade 0002 → upgrade head` inside a throw-away schema and
asserts that a pre-auth guest candidate and its interview survive.

The project previously recorded a real PostgreSQL run (PostgreSQL 18.7 on Neon): 12 passed
in 8 m 36 s, with the migration cycle and cleanup verified. That run is historical evidence,
not part of the current local result.

## 2. How the suite is isolated

`tests/conftest.py` runs before any application import and forces:

```python
STORAGE_BACKEND = "memory"
LLM_PROVIDER = "mock"
ALLOW_MOCK_LLM = "true"
AUTH_COOKIE_SECURE = "false"
```

It also removes `DATABASE_URL`, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from the
environment, so a developer's shell cannot make the default run touch a real database or a
paid API. Tests use `fastapi.testclient.TestClient` and the in-memory store; LLM behaviour is
supplied by fake providers or the deterministic mock.

## 3. Test files and coverage map

| File | Area |
| --- | --- |
| `test_interview.py` | Interview API end to end: start, read, answer, advance, report, validation |
| `test_answer_lifecycle.py` | Record-then-evaluate, duplicate rejection, retries, failure states |
| `test_evaluation.py` | Evaluator dispatch by question type, score aggregation |
| `test_llm_evaluation.py` | Rubric prompt/schema, strict validation, provider error mapping, retries |
| `test_competency.py` | θ initialisation, EMA updates (α = 0.15), clamping, per-interview isolation |
| `test_adaptive_metrics.py` | H(θ), IDI, difficulty fit, QScore, tie ordering, invalid inputs |
| `test_adaptive_selection.py` | Cold start vs adaptive choice, QScore ranking, tie-breaking |
| `test_rotation.py` | Candidate-aware cooldown rotation and least-recently-assigned tiers |
| `test_progression.py` | Next-question rules, completion by count and exhaustion |
| `test_timer_integrity.py` | Per-question limit, grace period, server-authoritative timing |
| `test_deadlines_and_integrity.py` | Late/duplicate/not-current handling, indicators, report counters |
| `test_questions.py` | Question API, filters, answer-key redaction |
| `test_question_bank_v2.py` | Bank integrity, counts, review gating, CSV/JSON freshness |
| `test_voice.py` | Audio validation, format detection, transcription errors, no state change |
| `test_auth.py` | Registration/login/logout, hashing, cookies, expiry, revocation, CSRF, ownership, guest contract |
| `test_auth_postgres.py` | Same auth behaviour on PostgreSQL + migration cycle (opt-in) |
| `test_postgres_store.py` | Interview persistence, locking, change replay, competency history (opt-in) |

Names follow `test_<behaviour>_<condition>` and are intended to read as assertions.

## 4. What is verified, and what is not

**Covered**

- Domain rules and their HTTP mapping, including status codes and coded errors.
- Adaptive mathematics and selector mechanics with seeded random generators.
- Answer-key redaction on every public question response.
- Guest journeys alongside account journeys, and cross-account isolation.
- Migration reversibility for the auth tables (PostgreSQL only).
- Voice error taxonomy with fake transcription clients.

**Not covered**

- Live Anthropic/OpenAI calls. Provider request/response shapes are tested against mocked
  HTTP; no key is used in CI or locally.
- Real `faster-whisper` transcription quality, latency or model download.
- Browser behaviour: timer display, auto-submit, recording, integrity capture, routing.
- Load, concurrency beyond the row-lock tests, and performance.
- Accessibility.
- The frontend build is not part of pytest.

## 5. Frontend checks

From `backend/frontend/`:

```bash
npm run lint        # ESLint
npm run build       # Vite production build
npm run check:launch  # deployment checklist
```

`check:launch` is expected to fail until `src/siteConfig.js` placeholders and the
`vercel.json` backend domain are replaced; a failure there is a real finding, not a flaky
check. There are no component or end-to-end tests.

## 6. Adding tests

- Put backend tests in `backend/tests/`, use a module-level `TestClient(app)` as
  `test_interview.py` does (or the `client` fixture defined in `test_auth.py`), and never
  require a network call.
- For selector behaviour, pass a `random.Random(seed)` so assertions are deterministic.
- For timing, pass an explicit `now`/`at` timestamp rather than sleeping.
- For PostgreSQL-specific behaviour, add to the opt-in modules and create a schema per test.
- Changing `EMA_ALPHA`, QScore weights, difficulty values or `STREAK_LIMIT` requires updating
  both `test_competency.py`/`test_adaptive_metrics.py` and
  [MATHEMATICAL_SPEC.md](MATHEMATICAL_SPEC.md).
