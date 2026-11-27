# Account authentication

Backend accounts for the AI Interview Simulator, added **without changing** the guest
interview experience, the candidate identity model, adaptive question selection, the
candidate-aware cooldown rotation, timers or evaluation.

Guest interviews still need no account. Registered accounts add an identity on top of
the same candidate mechanism.

---

## 1. What exists before this work (findings)

| Question | Answer found in the code |
| --- | --- |
| How is a guest candidate created? | `POST /candidates` inserts a row in `candidates` (uuid4 `candidate_id`), or an interview starts with **no candidate at all** (`candidate_id` is nullable, migration `0002`). |
| Does a guest have a secret? | **No.** There is no guest credential anywhere in the schema or the frontend. |
| Can the backend verify guest ownership? | **No.** A `candidate_id` (or `interview_id`) is a bare identifier; holding it is the only thing that grants access. |
| How are interviews linked to a candidate? | `interview_sessions.candidate_id` (nullable, `ON DELETE RESTRICT`). Nothing else. |
| Does the frontend store guest identity? | Only `ais.recentSessions` in `localStorage` (a list of interview ids for display). That is browser history, **not** proof of server-side ownership. |
| Where do interviews live? | PostgreSQL (`interview_sessions`, `interview_answers`, …) or the in-memory store for development. `localStorage` only mirrors ids. |

The React client never sends a `candidate_id`: every interview it starts is anonymous.
Candidate-aware behaviour (cooldown rotation, competency history) is exercised through
the API contract, not through the current UI.

**Consequence:** a client-supplied `candidate_id` can never be treated as authentication.
Nothing in this change does that.

---

## 2. What is implemented, and what is not

Implemented:

- users, authentication sessions, Argon2id password hashing;
- `POST /api/v1/auth/register`, `/login`, `/logout`, `GET /api/v1/auth/me`;
- `GET /api/v1/candidates/me`, `GET /api/v1/interviews/me`;
- server-side session expiry and revocation, opaque cookies, CSRF origin checks;
- login/registration rate limiting, email normalization, duplicate protection;
- ownership checks for account-owned interviews, with guests unchanged.

**Not implemented — and not claimed anywhere in the API:**

- email verification (no verification email is sent; `is_email_verified` is always
  `false` at registration and only a real flow may change it);
- password recovery or password change (there is no endpoint, and no reset token table);
- guest-to-account history claiming (§7);
- two-factor authentication, device management, account deletion;
- a distributed rate limiter (§6).

---

## 3. Data model

Migration `migrations/versions/0003_users_and_auth_sessions.py` (revision `0003`, revises
`0002`) is purely additive.

```
users
  id                VARCHAR(36)  PK
  email             VARCHAR(254) NOT NULL, UNIQUE (uq_users_email)   -- stored normalized
  password_hash     VARCHAR(255) NOT NULL                            -- Argon2id, never plaintext
  is_active         BOOLEAN      NOT NULL DEFAULT true
  is_email_verified BOOLEAN      NOT NULL DEFAULT false
  created_at        TIMESTAMPTZ  NOT NULL
  updated_at        TIMESTAMPTZ  NOT NULL

candidates
  user_id           VARCHAR(36)  NULL, FK -> users(id) ON DELETE SET NULL, UNIQUE
                                   (uq_candidates_user_id)

auth_sessions
  id           VARCHAR(36) PK
  user_id      VARCHAR(36) NOT NULL, FK -> users(id) ON DELETE CASCADE
  token_hash   VARCHAR(64) NOT NULL, UNIQUE        -- SHA-256 hex of the opaque token
  created_at   TIMESTAMPTZ NOT NULL
  expires_at   TIMESTAMPTZ NOT NULL
  revoked_at   TIMESTAMPTZ NULL
  last_used_at TIMESTAMPTZ NULL
  INDEX (user_id, created_at), INDEX (expires_at)
```

Design notes:

- **The relationship is `candidates.user_id`, nullable.** Guest candidates keep
  `user_id = NULL`; PostgreSQL does not compare NULLs in a unique constraint, so any
  number of guest candidates coexist, while a user can own **at most one** candidate.
- **Candidate ids are unchanged and still the identity used everywhere.** Nothing was
  re-keyed from `candidate_id` to `user_id`; interviews keep pointing at candidates, so
  cooldown history, competency history and reports behave exactly as before.
- `ON DELETE SET NULL` on `candidates.user_id`: removing an account would leave the
  candidate and its interviews intact (they simply become guest records again) instead
  of cascading into interview history.
- Interview rows are never rewritten by any migration. `0003.downgrade()` drops only
  `auth_sessions`, the new `candidates.user_id` column, and `users`.

### Migration

```bash
cd backend
DATABASE_URL='postgresql+psycopg://user:pass@host:5432/db' alembic upgrade head
```

`alembic heads` reports `0003`. `alembic upgrade head` is safe on a database that
already holds guest candidates and interviews: every statement is `CREATE`/`ALTER ADD`.

Rollback: `alembic downgrade 0002` removes the auth tables and the column, and keeps
every candidate and interview row.

---

## 4. API

All account endpoints live under `/api/v1`. The existing API (`/interview/*`,
`/candidates/*`, `/questions`) is unchanged and still needs no session.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | none | create account + its candidate |
| POST | `/api/v1/auth/login` | none | verify credentials, open a session cookie |
| POST | `/api/v1/auth/logout` | cookie | revoke the session, clear the cookie |
| GET | `/api/v1/auth/me` | cookie | the signed-in account |
| GET | `/api/v1/candidates/me` | cookie | the account's own candidate |
| GET | `/api/v1/interviews/me` | cookie | the account's interview history |

### `POST /api/v1/auth/register`

```json
{ "email": "Ada@Example.com", "password": "correct horse battery staple" }
```

`201`:

```json
{
  "user_id": "…",
  "email": "ada@example.com",
  "is_active": true,
  "is_email_verified": false,
  "candidate_id": "…",
  "created_at": "2026-11-26T12:00:00Z"
}
```

The email is trimmed and lower-cased before it is stored and compared. Registration
creates the user **and** its candidate in one transaction. It does **not** open a
session (call `/login`) and does not send any email.

Errors: `409 email_already_registered`, `422` (invalid email / password policy),
`429 rate_limited` with `Retry-After`.

> Registration reveals that an address is taken — unavoidable for a sign-up form, and
> the reason the *login* response is generic instead.

### `POST /api/v1/auth/login`

```json
{ "email": "ada@example.com", "password": "correct horse battery staple" }
```

`200` with the same body as `/register`, plus

```
Set-Cookie: ais_session=<opaque token>; HttpOnly; SameSite=lax; Path=/; Max-Age=604800[; Secure]
```

The raw token is **never** in the JSON body. Errors: `401 invalid_credentials`
(identical for an unknown email and a wrong password, after the same Argon2 cost),
`403 account_inactive`, `429 rate_limited`.

### `POST /api/v1/auth/logout`

`204`, revokes the session row (`revoked_at`) and clears the cookie. Idempotent: no
session, or a second call, is still `204`. Rejected with `403 csrf_rejected` when the
request is cross-site (§6).

### `GET /api/v1/auth/me`

`200` with the account body, or `401 authentication_required` when the cookie is
missing, expired, revoked, or its account is inactive.

### `GET /api/v1/candidates/me`, `GET /api/v1/interviews/me`

The candidate id comes **from the session**, never from the client, so these cannot be
pointed at somebody else's data. `401` without a session.

### Error shape

Newer endpoints reuse the project's coded error body:

```json
{ "detail": { "code": "invalid_credentials", "message": "Incorrect email or password." } }
```

Legacy errors keep their plain-string `detail`. No error ever contains a password, a
hash, a token, a session id, a database message or an email address.

---

## 5. Session security

- **Token**: 32 bytes from `secrets.token_urlsafe` (256 bits). Stored as SHA-256 hex;
  the raw value exists only in the cookie. A database dump therefore cannot be replayed.
  A fast hash is correct here because the token is already high-entropy random data.
- **Server-side authority**: every request re-reads `auth_sessions`. The cookie's
  `Max-Age` is browser convenience only; expiry, revocation and account status are
  enforced in `AuthService.authenticate`.
- **Expiry**: absolute (`AUTH_SESSION_TTL_SECONDS`, default 7 days). Using a session
  never extends `expires_at`; only `last_used_at` is refreshed, and at most once per
  `AUTH_SESSION_TOUCH_SECONDS` so a session is not a write on every request.
- **Revocation**: `logout` revokes one session; `AuthService.revoke_all_sessions` is the
  hook an account-security response uses. Sessions are never deleted, so a replayed
  cookie is distinguishable from an unknown one.
- **Disabling an account** invalidates its live sessions (the session is revoked the
  next time it is presented).
- **Cookie**: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` unless
  `AUTH_COOKIE_SECURE=false`, host-only unless `AUTH_COOKIE_DOMAIN` is set.
- Authentication tokens are **never** put in `localStorage`; the API does not emit them
  in JSON at all.

### Password policy

Documented, deliberately short (NIST SP 800-63B style): **12–128 characters**, no
composition rules, no forced rotation, no "must contain a symbol". Unicode is accepted.
Hashing is Argon2id via `argon2-cffi` with `time_cost=3`, `memory_cost=64 MiB`,
`parallelism=4`, `hash_len=32`, `salt_len=16` (~80 ms/hash).

---

## 6. Abuse protection

- **Rate limiting** (`app/services/rate_limit.py`): sliding window, in-process.
  Failed logins are counted per normalized email (`AUTH_LOGIN_RATE_LIMIT_ATTEMPTS`,
  default 10 / 5 min) and per client address (`AUTH_LOGIN_IP_RATE_LIMIT_ATTEMPTS`,
  default 50 / 5 min); a successful login clears the email counter. Registrations are
  counted per address (`AUTH_REGISTER_RATE_LIMIT_ATTEMPTS`, default 20 / hour).
  Exceeding either returns `429` with `Retry-After`.
  **Limitation:** counters live in the process. Behind multiple workers the effective
  limit multiplies, and a restart clears them. A shared counter (Redis/table) is the next
  step; documented rather than pretended.
- **Enumeration**: login answers `401 invalid_credentials` for both unknown emails and
  wrong passwords, and does the same Argon2 work in both cases (a dummy hash is verified
  when the email is unknown). An inactive account is only reported after a correct
  password.
- **CSRF**: the session cookie is `SameSite=Lax`, so browsers do not attach it to
  cross-site POSTs. On top of that, cookie-authenticated state-changing requests check
  `Sec-Fetch-Site` and `Origin`   (`enforce_csrf`), rejecting anything not same-origin or
  listed in `AUTH_ALLOWED_ORIGINS` with `403 csrf_rejected`. Reverse proxies must not
  strip `Origin`.
  `login` and `register` are not cookie-authenticated (they *create* the session), so
  they are not origin-checked; login-CSRF is therefore only mitigated by the browser's
  SameSite handling. A frontend on another origin must set `AUTH_ALLOWED_ORIGINS` and
  send `credentials: "include"` with the correct CORS configuration; extending the
  origin check to those two routes is the natural follow-up once the UI origin is fixed.
- **No fallback authentication**: there is no header-based identity, no "trusted"
  candidate id, no debug bypass. A missing session is a guest, and a guest cannot reach
  account-owned interviews.
- **Logging**: no password, token or hash is logged. Only aggregate events
  ("Account created") and exception types.

---

## 7. Guest identity and history claiming

### Current behaviour (unchanged)

| Request | Interview is a guest interview | Interview belongs to an account |
| --- | --- | --- |
| No cookie | allowed, as before | `401 authentication_required` |
| Cookie of the owner | not applicable | allowed |
| Cookie of another account | not applicable | `404 Interview not found` |

- Guest interviews (anonymous, or a candidate created by `POST /candidates`) keep the
  existing contract: holding the interview id is enough. Nothing about the guest journey
  was made harder — `POST /interview/start`, answering, advancing and reading the report
  work without a session, and `tests/test_auth.py` asserts that end to end.
- An account-owned interview requires its account. Guests get `401`, other accounts get
  `404` (never `403`, so the endpoint does not confirm that somebody else's interview
  exists).
- A client-supplied `candidate_id` still cannot be used to *become* someone: starting an
  interview with an account's candidate id returns `404 Candidate not found` for guests
  and for other accounts.

### Claiming is deliberately not implemented

There is no secure way to prove ownership of a **pre-existing** guest candidate: the
only artefact that exists is an id in `localStorage`, and any browser could send any id.
Implementing a "claim" endpoint on that basis would hand one user another user's
interviews — exactly what the task forbids.

Safe design for a later change (requires the frontend too):

1. When an anonymous interview (or guest candidate) is created, generate a 256-bit
   `guest_token`, return it **once** in the creation response, store only its SHA-256
   hash on the candidate/interview row.
2. The frontend stores the token next to `ais.recentSessions` (it is a capability, not a
   login, so it is not an authentication authority).
3. `POST /api/v1/auth/claim-guest` requires a session **and** the token; it verifies the
   hash, checks the candidate is not already owned by another account, and links it in
   one transaction (idempotent when it is already owned by the caller).
4. Existing guest rows have no token, so they are **not** claimable — they stay guest
   records. That is the documented migration strategy for pre-auth history: no silent
   reassignment, no data loss, no guessable-id ownership.

Because step 1 changes the guest creation contract, it belongs in a change that also
updates the frontend. Until then, `candidate_id` is never trusted as ownership.

---

## 8. Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUTH_SESSION_TTL_SECONDS` | `604800` (7 days) | absolute session lifetime |
| `AUTH_SESSION_COOKIE_NAME` | `ais_session` | cookie name |
| `AUTH_COOKIE_SECURE` | `true` | `false` only for plain-HTTP development |
| `AUTH_COOKIE_SAMESITE` | `lax` | `lax` or `strict` |
| `AUTH_COOKIE_DOMAIN` | *(unset)* | host-only when unset (recommended) |
| `AUTH_SESSION_TOUCH_SECONDS` | `60` | write throttle for `last_used_at` |
| `AUTH_LOGIN_RATE_LIMIT_ATTEMPTS` | `10` | failed logins per email per window |
| `AUTH_LOGIN_IP_RATE_LIMIT_ATTEMPTS` | `50` | failed logins per address per window |
| `AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | window for the two above |
| `AUTH_REGISTER_RATE_LIMIT_ATTEMPTS` | `20` | registrations per address per window |
| `AUTH_REGISTER_RATE_LIMIT_WINDOW_SECONDS` | `3600` | window for registration |
| `AUTH_ALLOWED_ORIGINS` | *(empty)* | comma-separated extra origins accepted for CSRF checks; empty means same-origin only |
| `AUTH_TRUST_PROXY` | `false` | honour `X-Forwarded-For` for rate-limit keys |

No secret is required: session tokens are random, not signed. Nothing here belongs in
`localStorage`, and no key is ever committed.

### CORS and cookie scope (deployment-critical)

The backend has **no `CORSMiddleware`**, and `backend/frontend/SETUP.md` only tells an
operator to add one by hand. Two separate things must both be right:

1. **CORS.** `app.your-domain.com` calling `api.your-domain.com` is a cross-origin
   request: without CORS middleware the browser blocks it. It must be configured with
   `allow_credentials=True` and an explicit origin list — never `allow_origins=["*"]`
   with credentials. The cookie is `HttpOnly`, so `credentials: "include"` on the
   client and `Access-Control-Allow-Credentials: true` on the server are both required.
2. **Same-site.** `SameSite` is about the registrable domain, not the origin.
   `www.your-domain.com` + `api.your-domain.com` are the **same site**, so
   `SameSite=Lax` works. A `*.vercel.app` frontend calling a custom API domain is
   **cross-site**: browsers will not attach a `Lax` cookie to those requests, so the
   current configuration cannot authenticate it. The safe answer is to serve the API
   under the same site (proxy `/api/*` through the frontend's host), which also removes
   the CORS requirement entirely.

`AUTH_COOKIE_SAMESITE` accepts only `lax` or `strict` today. Cross-site cookies would
need `SameSite=None; Secure` (plus CORS credentials); that value is deliberately not
supported until a deployment actually requires it, because it weakens the CSRF
protection that `Lax` provides for free.

**Deployment checklist**

- serve over HTTPS with `AUTH_COOKIE_SECURE=true` (the default);
- serve the UI and the API from the **same site**, or add CORS with
  `allow_credentials=True` and explicit origins plus `SameSite=None` support (see above);
- set `AUTH_ALLOWED_ORIGINS` if the UI is served from a different origin than the API
  (and set CORS credentials correctly for that origin);
- run `alembic upgrade head` before starting the new code;
- keep one worker, or accept per-worker rate limits until a shared counter exists;
- back up guest interviews before any future claim/merge change.

---

## 9. Local development

```bash
cd backend
python -m venv ../.venv && ../.venv/Scripts/pip install -r requirements.txt   # Windows
export STORAGE_BACKEND=memory          # accounts + interviews in memory, lost on restart
export AUTH_COOKIE_SECURE=false        # plain HTTP on localhost
uvicorn app.main:app --reload
```

With `STORAGE_BACKEND=postgres` (or `DATABASE_URL` set), accounts and sessions are stored
in PostgreSQL and survive restarts; run `alembic upgrade head` first.

---

## 10. Tests

```bash
cd backend
pytest -q                                  # everything on the in-memory backend
TEST_DATABASE_URL='postgresql+psycopg://…/scratch' pytest -q tests/test_auth_postgres.py
```

`tests/test_auth.py` (in-memory, runs by default) covers registration, duplicate and
normalized emails, invalid input, hash storage, login success/failure/inactive/
enumeration parity, cookie attributes, expiry, revocation, logout, disabled accounts,
CSRF rejection, ownership isolation, candidate-id bypass attempts, and the guest journey.

`tests/test_auth_postgres.py` (opt-in via `TEST_DATABASE_URL`) repeats the store and
ownership behaviour against PostgreSQL **and** runs `alembic upgrade 0002 → head →
downgrade 0002 → upgrade head` inside a throw-away schema, asserting a pre-auth guest
candidate survives with `user_id IS NULL` and that an existing interview row is still
there. Each test creates and drops its own schema, so `public` is never touched; without
`TEST_DATABASE_URL` the module skips.

### Verified against a real PostgreSQL (2026-11-26)

| Item | Result |
| --- | --- |
| Server | PostgreSQL **18.7** (Neon), user `neondb_owner` |
| Command | `TEST_DATABASE_URL=<test db> pytest -q tests/test_auth_postgres.py` |
| Suite | **12 passed** in 8 m 36 s |
| Migration | `0002 → head → 0002 → head`, guest candidate and interview row intact, `public` untouched |
| Lifecycle | **42/42** runtime checks (register, login, cookie flags, `/auth/me`, owned interview + report, invalid credentials, enumeration parity, cross-account 404s, guest compatibility, CSRF 403, logout/replay, expiry, disabled account, 429 + `Retry-After`, persistence) |
| Cleanup | all throw-away schemas dropped by the suite |

`test_display_name_lands_on_the_one_linked_candidate` was added with the registration
change that stores an optional `display_name` on the account's own candidate row: it
asserts the name and the `user_id` on that row and that no second candidate exists.

One real defect was found and fixed by this run: `PostgresAuthStore.create_user` inserted
the candidate row before the user row (the models have no ORM relationship), which raised
`candidates_user_id_fkey` and would have made **registration fail on PostgreSQL**. It now
flushes the user first; both rows still commit or roll back together.

A killed test process leaves its `test_auth_*` schema behind (the module fixture is the
only cleanup path). They are inert and named `test_auth_*`, but they should be dropped by
hand after an interrupted run.

---

## 11. Frontend integration (implemented)

The React app in `backend/frontend` uses this API:

1. `src/api/client.js` sends every request with `credentials: 'same-origin'`; the session
   arrives as an `HttpOnly` cookie and is never read or stored by application code.
2. `src/components/SessionProvider.jsx` calls `GET /api/v1/auth/me` on load (401 means
   guest) and after sign-in/sign-out; `src/lib/session.js` exposes `useSession()`.
3. `POST /api/v1/auth/logout` clears the session. Registration calls `/register` and
   then `/login`, because registration does not open a session. No verification email is
   sent, so the UI does not promise one.
4. The browser talks to its own origin only: `vite.config.js` and `vercel.json` proxy
   `/api/v1/*` with the prefix kept and `/api/*` with it stripped. `Origin` and the cookie
   therefore stay first-party, which is what the CSRF check expects once
   `AUTH_ALLOWED_ORIGINS` lists the frontend origin.
5. The dashboard reads `GET /api/v1/candidates/me` (name) and
   `GET /api/v1/interviews/me` (history); it never reads a candidate id from storage.
6. `src/pages/Start.jsx` sends the account's candidate id from `/candidates/me`; guests
   send none. `ais.recentSessions` stays guest-only and no session value is stored in
   `localStorage`.
7. Guest claim is still not available (§7); nothing pretends to import guest history.
8. Every `/api/v1/*` response is sent with `Cache-Control: no-store`, including errors.
