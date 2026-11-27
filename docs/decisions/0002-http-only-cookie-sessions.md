# 0002 — Server-side sessions in HttpOnly cookies, not tokens in storage

**Status:** Accepted (implemented)

## Context

Accounts were added on top of an existing guest application where the browser stored only
interview ids in `localStorage`. The guest flow had to keep working unchanged, the SPA is
served from the same origin as its API through a proxy, and no token may be readable by
JavaScript or replayable from a database dump.

## Decision

- A login creates a row in `auth_sessions` with a random 256-bit token
  (`secrets.token_urlsafe(32)`).
- Only the SHA-256 hex of the token is stored; the raw token exists solely in the cookie.
- The cookie is `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` by default (disabled only for
  plain-HTTP development), host-only unless `AUTH_COOKIE_DOMAIN` is set.
- Every authenticated request re-reads the session row and checks `expires_at`,
  `revoked_at` and the account's `is_active`. Expiry is absolute; `last_used_at` is refreshed
  at most once per `AUTH_SESSION_TOUCH_SECONDS`.
- Logout sets `revoked_at` and clears the cookie; sessions are never deleted on logout.
- No token is returned in JSON, stored in `localStorage` or read by application code.

## Consequences

- The frontend must call the API on its **own site**. A `SameSite=Lax` cookie is not sent
  cross-site, so a `*.vercel.app` UI calling a custom API domain cannot authenticate. The
  supported deployment proxies `/api` through the UI host.
- Cookie-authenticated state changes need CSRF protection, implemented as `Sec-Fetch-Site`
  and `Origin` checks in `enforce_csrf` plus the SameSite cookie.
- Each request costs one indexed session read; a token-signature scheme would avoid it but
  would lose immediate revocation.
- `AUTH_ALLOWED_ORIGINS` must list the UI origin when a proxy makes `Origin` differ from the
  API `Host`.

## Evidence

- `backend/app/api/auth.py` — cookie set/clear, no token in the response body.
- `backend/app/api/auth_deps.py` — `session_token`, `enforce_csrf`, ownership dependencies.
- `backend/app/services/auth_service.py`, `session_tokens.py` — hashing, expiry, revocation.
- `backend/app/db/models.py` — `auth_sessions` columns and indexes.
- `docs/AUTHENTICATION.md` — full contract and deployment checklist.

## Alternatives considered

- **JWT in `localStorage`:** readable by any XSS, no immediate revocation, and the guest app
  already worked without client-side credentials.
- **JWT in an HttpOnly cookie:** still needs revocation infrastructure; an opaque row gives
  it directly and is simpler to reason about.
- **Signed cookies without server state:** cannot revoke a stolen session or disable an
  account immediately.
