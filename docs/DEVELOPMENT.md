# Development

Everything needed to run, change and deploy the project. Commands assume the repository root
(`AI-Interview-Simulator/`); backend commands assume `backend/`.

## 1. Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Python | 3.11+ | backend, tests, migrations |
| Node.js + npm | 20+ | frontend build and dev server |
| PostgreSQL | with JSONB support | persistent storage (optional locally) |
| Git | any recent | version control |

The backend's `requirements.txt` pins minimum versions: `fastapi>=0.111`, `uvicorn[standard]>=0.29`,
`pydantic>=2.6`, `pytest>=8`, `httpx>=0.27`, `python-multipart>=0.0.9`, `sqlalchemy>=2.0`,
`alembic>=1.13`, `psycopg[binary]>=3.1`, `argon2-cffi>=23.1`. `requirements-whisper.txt` adds
`faster-whisper>=1.0` for voice answers.

## 2. Install

```bash
# Backend (virtualenv at the repository root is the convention used here)
python -m venv .venv
# Windows:      .venv/Scripts/activate
# macOS/Linux:  source .venv/bin/activate
pip install -r backend/requirements.txt
pip install -r backend/requirements-whisper.txt   # optional: voice answers

# Frontend
cd backend/frontend
npm install
```

`backend/package.json` exists and declares a Node `argon2` dependency. The backend is Python
and uses `argon2-cffi`; that file is not used by the application and is not required to run
anything. `npm install` for the application belongs in `backend/frontend/`.

## 3. Environment variables

The backend reads configuration from the process environment (`app/config.py`). Local
development usually loads a file: `uvicorn app.main:app --reload --env-file .env`. Copy
`backend/.env.example` to `backend/.env` and edit it. Never commit `.env`.

### Storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `STORAGE_BACKEND` | *(empty)* | `memory` or `postgres`. Empty means "postgres if `DATABASE_URL` is set", otherwise startup fails |
| `DATABASE_URL` | *(empty)* | `postgresql+psycopg://user:password@host:5432/db`; a bare `postgresql://` is normalised for Alembic |

`memory` keeps interviews in the process: development and tests only, lost on restart.

### AI evaluation

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | *(empty)* | `anthropic` or `openai_compatible`; `mock` exists for tests |
| `ALLOW_MOCK_LLM` | `false` | required to use `LLM_PROVIDER=mock` |
| `LLM_TIMEOUT_SECONDS` | `30` | per HTTP call |
| `LLM_MAX_ATTEMPTS` | `3` | evaluation attempts with backoff |
| `LLM_RETRY_BASE_SECONDS` | `0.5` | exponential backoff base (capped at 8 s) |
| `LLM_MAX_TOKENS` | `1500` | Anthropic response budget |
| `MAX_EVALUATION_RETRIES` | `5` | client-triggered retries after the first attempt |
| `ANTHROPIC_API_KEY` | *(empty)* | required for `anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | model id sent to Anthropic |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | override for a proxy |
| `OPENAI_API_KEY` | *(empty)* | required for `openai_compatible` |
| `OPENAI_MODEL` | *(empty)* | required for `openai_compatible` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | any compatible server |

Without a configured provider, answers are still saved but not scored
(`evaluation_status: pending`, HTTP 202). There is no heuristic fallback.

### Timing, limits and integrity

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANSWER_GRACE_SECONDS` | `15` | accepted lateness after the nominal limit |
| `MAX_ANSWER_CHARS` | `20000` | answer text limit (mirror in `src/siteConfig.js`) |
| `FAST_SUBMISSION_CHARS_PER_SECOND` | `25.0` | typing faster than this flags an indicator (only for answers ≥ 200 chars) |
| `MAX_AUDIO_UPLOAD_BYTES` | `10485760` | largest accepted audio upload (10 MiB) |
| `MAX_RECORDING_SECONDS` | `60` | longest accepted recording (mirror in `src/siteConfig.js`) |
| `TRANSCRIPTION_TIMEOUT_SECONDS` | `60` | server wait before 504 |
| `WHISPER_MODEL_SIZE` | `base.en` | `faster-whisper` model name |

The per-question time limit is **not** an environment variable: it is the question's
`estimated_time_seconds`, falling back to the constant
`DEFAULT_QUESTION_TIME_LIMIT_SECONDS = 90` in `app/config.py`. Integrity caps (50 events per
request, 2000 per interview) are constants.

### Accounts

See [AUTHENTICATION.md](AUTHENTICATION.md#8-environment-variables) for the full list:
`AUTH_SESSION_TTL_SECONDS`, `AUTH_SESSION_COOKIE_NAME`, `AUTH_COOKIE_SECURE`,
`AUTH_COOKIE_SAMESITE`, `AUTH_COOKIE_DOMAIN`, `AUTH_SESSION_TOUCH_SECONDS`, the four
rate-limit settings, `AUTH_ALLOWED_ORIGINS` and `AUTH_TRUST_PROXY`.

Local plain-HTTP development needs `AUTH_COOKIE_SECURE=false`; the default is `true`.

### Frontend

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api` | must stay relative for the same-origin proxy |

## 4. Run locally

Two terminals:

```bash
# 1) backend
cd backend
STORAGE_BACKEND=memory AUTH_COOKIE_SECURE=false \
  uvicorn app.main:app --reload --port 8000
# with a real file: uvicorn app.main:app --reload --env-file .env

# 2) frontend
cd backend/frontend
npm run dev        # http://localhost:5173
```

Useful URLs: `/health`, `/health/ready`, `/docs`, `/openapi.json`.

The dev proxy forwards `/api/v1/*` unchanged (accounts) and strips `/api` for everything
else (interview/candidates/questions). `changeOrigin` is false because the backend's CSRF
check compares `Origin` and `Host`.

## 5. Database and migrations

```bash
cd backend
export DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/interview_sim'
alembic upgrade head
alembic current      # expect 0003
alembic downgrade 0002
```

Schema, constraints and the ER diagram: [DATABASE.md](DATABASE.md). Migrations are additive
by convention; `0002`'s downgrade deletes anonymous rows because the older schema cannot hold
them.

On startup with PostgreSQL the app upserts `data/question_bank.json` into `questions` (a
missing schema fails startup); `GET /health/ready` separately runs a real `SELECT 1` query.
The JSON file stays the source of truth.

## 6. Question bank workflow

1. Edit `backend/data/question_bank.csv`.
2. Regenerate the runtime file:

   ```bash
   cd backend
   python scripts/convert_question_bank.py
   ```

3. Run `python -m pytest -q tests/test_question_bank_v2.py` — it fails when the JSON is out
   of date or the bank invariants break.
4. Only `review_status = reviewed` questions are ever selected. `needs_manual_review` and
   `requires_coding_evaluation` remain lookup-able but unservable.

## 7. Code conventions

- **Layering:** HTTP → service → store → domain. Do not put interview rules in routers, SQL
  in the domain, or formulas in the store.
- **Errors:** raise a typed domain error and map it in `api/errors.py`. Never return raw
  exception text, provider output or database messages.
- **Secrets:** read them from the environment only; never log them, never include them in an
  error, never commit them.
- **Guest contract:** a guest interview must keep working with no session, and a
  client-supplied `candidate_id` is never authentication.
- **Numbers:** treat adaptive constants and the EMA coefficient as documented research
  decisions. Changing one requires a docs and tests update.
- **Docs:** if a change alters an endpoint, table, route, environment variable or rule,
  update the matching document in `docs/`.

## 8. Checks before proposing a change

```bash
cd backend && python -m pytest -q
cd backend/frontend && npm run lint && npm run build
git diff --check
```

The PostgreSQL suites are not part of the default run; run them when touching
`postgres_store.py`, `postgres_auth_store.py`, models or migrations.

## 9. Deployment

The supported shape is one site: static frontend plus a proxied API.

1. Deploy FastAPI behind HTTPS (any ASGI host) with `alembic upgrade head` applied and
   `STORAGE_BACKEND=postgres` + `DATABASE_URL` set.
2. Serve the UI and API from the **same site**. `backend/frontend/vercel.json` rewrites
   `/api/v1/*` (prefix kept) and `/api/*` (prefix stripped) to the backend origin and falls
   back to `index.html` for client routes. Replace `https://api.your-domain.com` with the real
   origin.
3. Set `AUTH_COOKIE_SECURE=true`, leave `AUTH_COOKIE_DOMAIN` unset, and list the UI origin in
   `AUTH_ALLOWED_ORIGINS` (the proxy makes `Origin` differ from the API `Host`).
4. Fill every `TODO_` in `backend/frontend/src/siteConfig.js`; `npm run check:launch` fails
   while any remain.
5. Build the frontend (`npm run build`) and deploy `dist/` with `vercel.json`.
6. Verify on the deployed origin: sign-in sets one `HttpOnly`, `Secure`, `SameSite=Lax`
   cookie; reload keeps the session; sign-out returns `401` on `/api/v1/auth/me`; an
   account-owned report opens only for its owner; a guest interview still opens without an
   account.
7. Keep one worker, or accept per-worker rate limits until a shared counter exists. Hosts
   often cap request bodies below the backend's 10 MiB audio allowance, so check the host's
   limit or lower `MAX_AUDIO_UPLOAD_BYTES`.

Do **not** put the API on a different *site* (for example a `*.vercel.app` UI calling a
custom API domain): a `SameSite=Lax` cookie is not sent cross-site, so authentication would
silently fail. Cross-site cookies would require `SameSite=None; Secure`, CORS with
credentials and a deliberate security review.

## 10. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Startup: "No storage configured" | Set `DATABASE_URL` or `STORAGE_BACKEND=memory` |
| Startup: "STORAGE_BACKEND=postgres requires DATABASE_URL" | Set the URL or change the backend |
| Answers save but never score (202) | `LLM_PROVIDER`/key missing, provider unreachable, or output invalid; inspect `evaluation_error.code` and retry |
| `llm_not_configured` mentioning the mock | `LLM_PROVIDER=mock` requires `ALLOW_MOCK_LLM=true`; use it only for tests |
| Sign-out returns 403 `csrf_rejected` | The proxy rewrote `Host`; keep `changeOrigin: false` or list the origin in `AUTH_ALLOWED_ORIGINS` |
| Session lost after reload | Cookie is `Secure` on plain HTTP, or the frontend calls a different site/origin; set `AUTH_COOKIE_SECURE=false` locally |
| `question_deadline_passed` unexpectedly | The question's `estimated_time_seconds` may be short; check `deadline_at` and the server clock |
| `interview_busy` repeatedly | Another request holds the row lock; the client retries once after one second |
| Alembic: "DATABASE_URL is not set" | Export it in the shell running Alembic (`alembic.ini` holds no URL) |
| Frontend calls hit the wrong path | `/api/v1/*` keeps the prefix, `/api/*` strips it; account calls need `/v1/...` in the client |
| `check:launch` fails | Expected while `TODO_` values remain in `siteConfig.js` or `vercel.json` |
