# 0004 — Guests keep id-based access; guest history is never claimed

**Status:** Accepted (implemented)

## Context

Before accounts existed, holding an interview id was the only way to reach an interview, and
the browser kept a list of ids in `localStorage`. Accounts were added later. The tempting
feature — "import the interviews you already did" — cannot be made safe from an id alone,
because any browser can send any id.

## Decision

- A guest interview (no owning candidate, or a candidate with `user_id IS NULL`) keeps the
  original contract: access by interview id, no session required.
- An interview owned by an account requires that account's session. A missing session returns
  `401 authentication_required`; a different account receives `404 Interview not found`
  (never `403`, so existence is not confirmed).
- The same rule applies to candidate-scoped routes (`/candidates/{id}`, its interviews and
  competency history).
- A client-supplied `candidate_id` is **never** authentication. Starting an interview with
  another account's candidate id returns `404`.
- No claiming endpoint exists. Guest ids stay in `localStorage` as display history only and
  are never associated with an account on login or registration.

## Consequences

- The guest journey is unchanged and fully usable without an account.
- Guest history does not follow a user who later registers; the dashboard shows only
  account-owned interviews and says so.
- A future claim feature needs a capability the guest actually possesses. The documented
  design is a one-time `guest_token` (256-bit, SHA-256 stored) returned at creation, plus
  `POST /api/v1/auth/claim-guest` requiring both the session and the token. Pre-existing
  rows have no token and would remain guest records.
- Account deletion (not implemented) would leave interviews intact via
  `candidates.user_id ON DELETE SET NULL`.

## Evidence

- `backend/app/api/auth_deps.py` — `require_interview_access`, `require_candidate_access`,
  `require_candidate_usable`.
- `backend/app/api/candidates.py` — guest routes stay unauthenticated.
- `backend/migrations/versions/0003_users_and_auth_sessions.py` — nullable, unique
  `candidates.user_id`.
- `backend/tests/test_auth.py` — guest journey, cross-account 404, candidate-id bypass.
- `docs/AUTHENTICATION.md` §7 — current behaviour and the safe future design.

## Alternatives considered

- **Claim by id:** would let one user absorb another user's interviews. Rejected.
- **Require an account for every interview:** breaks the product's core guest promise.
- **Auto-associate on login:** silently rewrites ownership of records the account never
  proved it owned.
