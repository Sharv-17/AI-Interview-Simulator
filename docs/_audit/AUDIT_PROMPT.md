# Documentation Audit Checklist

Reusable checklist for auditing this repository's documentation against its implementation.
It is documentation-only: never change application code, migrations, dependencies or
configuration to make the docs "true". If the code and the docs disagree, the code wins and
the documentation records the discrepancy.

Derived from the supplied documentation-audit kit, adapted to this repository. The kit's
`KICKOFF.md` (a Claude Code handoff that stops after reconnaissance) is intentionally not
included; an audit is expected to finish with updated documentation, not a plan.

## 1. Ground rules

- Read the implementation before writing a claim. Source of truth: `backend/app/`,
  `backend/migrations/`, `backend/frontend/src/`, `backend/tests/`, `backend/data/`,
  `backend/.env.example`.
- Do not modify `backend/` or `backend/frontend/src/` code. Findings stay findings.
- Preserve existing substantive documentation; merge, do not overwrite with a template.
- Never print or commit secrets. `.env` files are read-only inputs at most.
- Do not commit, push or deploy.

## 2. Inventory

| Document | Purpose |
| --- | --- |
| `README.md` | Landing page, setup, status, doc index |
| `docs/ARCHITECTURE.md` | Components, flows, diagrams |
| `docs/API.md` | Endpoints, schemas, errors |
| `docs/DATABASE.md` | Tables, keys, constraints, migrations |
| `docs/AUTHENTICATION.md` | Sessions, cookies, CSRF, ownership |
| `docs/MATHEMATICAL_SPEC.md` | Adaptive-engine mathematics |
| `docs/FRONTEND.md` | Routes, components, state |
| `docs/TESTING.md` | Suite layout, coverage, gaps |
| `docs/DEVELOPMENT.md` | Setup, env vars, deployment |
| `docs/decisions/` | ADRs |
| `backend/frontend/SETUP.md` | Frontend file map and deployment checklist |

## 3. Verify each claim

- **Endpoints:** compare `docs/API.md` with `backend/app/api/*.py` route decorators, request
  models in `app/schemas/`, and `app/api/errors.py`. Check the `/api/v1` prefix on auth and
  account routes.
- **Database:** compare `docs/DATABASE.md` with `app/db/models.py` and all Alembic revisions.
  Check nullability, uniques, checks, indexes, delete behaviour and downgrade semantics.
- **Adaptive engine:** confirm `EMA_ALPHA`, `THETA_INITIAL`, `DIFFICULTY_VALUE`, QScore
  weights and `STREAK_LIMIT` in code and tests. Confirm whether IDI is independent or an
  alias of entropy. Confirm the selector actually calls `score_candidate`.
- **Auth:** confirm cookie flags, TTL, CSRF checks, rate-limit counters, ownership responses
  (401 vs 404) and which routes are origin-checked.
- **Frontend:** compare routes with `src/App.jsx`, API paths with `src/api/client.js`, and
  local storage keys with `src/lib/recentSessions.js`.
- **Tests:** run the suite and quote the real counts; do not reuse an old number without
  re-running. Note skipped suites and why.
- **Commands and env vars:** every command must exist in a script or be runnable; every
  variable must be read by `app/config.py` or `import.meta.env`.

## 4. Checks

```bash
cd backend && python -m pytest -q
cd backend/frontend && npm run lint && npm run build
git diff --check
git status --short
```

Link and claim checks: every relative Markdown link must resolve to a file or an existing
heading anchor; every file path mentioned in backticks should exist. Mermaid diagrams have no
automated validator in this repository — review them by hand for balanced `subgraph`/`end`,
valid node ids and quoted labels.

## 5. Red flags to search for

- "will", "planned", "to be implemented", "currently in development" describing something that
  now exists (or the reverse: a planned feature described as done).
- "AI generates questions" — false: the bank is static.
- "communication analysis", "speaker pace", "filler words" — not implemented.
- "completed", "validated", "proven" attached to the adaptive model — it is unvalidated.
- Old default limits: the timer is not simply "90 seconds"; it is the question's estimated
  time plus `ANSWER_GRACE_SECONDS`.
- Any claim that a guest can claim or import history into an account.
- Stale statements in module docstrings (for example "H/IDI/QScore not implemented yet");
  report them as code-comment findings rather than editing code.
