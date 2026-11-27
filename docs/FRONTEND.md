# Frontend

React 19 single-page application built with Vite, in `backend/frontend/`. It talks only to
its own origin; a proxy forwards `/api` to FastAPI, so the session cookie stays first-party
and no CORS configuration is needed.

Run it with `npm run dev` (port 5173) and build it with `npm run build`. Deployment notes
are in [SETUP.md](../backend/frontend/SETUP.md) and
[DEVELOPMENT.md](DEVELOPMENT.md#9-deployment).

## 1. Routes

`src/App.jsx` defines every route inside a shared `Layout` (header, footer, outlet).

| Path | Component | Guard | Purpose |
| --- | --- | --- | --- |
| `/` | `HomeRoute` → `Login` or redirect | none | Sign-in form for a guest; a signed-in account is sent to `/dashboard` |
| `/login` | `LoginRoute` → `Login` | none | Sign in; honours `location.state.from` after authentication |
| `/register` | `RegisterRoute` → `Register` | none | Create an account (then signs in) |
| `/guest` | `Home` | none | Marketing home page and guest entry point |
| `/dashboard` | `Dashboard` | `RequireAuth` | Account profile, interview history, competency progress |
| `/start` | `Start` | none | Interview setup; sends the account's candidate id when signed in |
| `/interview/:id` | `Interview` | none | Question room: timer, voice, answer, feedback |
| `/report/:id` | `Report` (lazy) | none | Full report; explains a `401` with a sign-in link |
| `/privacy`, `/terms` | `Privacy`, `Terms` | none | Legal pages fed by `src/siteConfig.js` |
| `*` | `NotFound` | none | Unknown URL |

Only `/dashboard` redirects a guest (to `/login` with `state.from = /dashboard`). Interview
and report routes are intentionally unguarded: a guest interview must stay openable from a
link, and an account-owned one answers `401`, which the page renders as "Sign in to continue
this interview" with a link back to the same interview.

`Report` is lazy-loaded because it pulls in Recharts; the rest of the app does not.

## 2. Components and modules

| File | Role |
| --- | --- |
| `src/main.jsx` | Mounts React, router and `SessionProvider` |
| `src/App.jsx` | Routes, guards, session-loading state |
| `src/components/Layout.jsx` | Header/footer, navigation, sign-out |
| `src/components/SessionProvider.jsx` | Loads `/auth/me` + `/candidates/me`, exposes sign-in/out/refresh |
| `src/components/AuthShell.jsx` | Two-column layout for login and registration |
| `src/components/EvaluationPanel.jsx` | Criterion scores, feedback, strengths/weaknesses |
| `src/components/ScoreChart.jsx` | Per-question bar chart on the report |
| `src/pages/Home.jsx` | Landing page, topics, device-local recent interviews |
| `src/pages/Start.jsx` | Topic/difficulty/count form, starts the interview |
| `src/pages/Interview.jsx` | Question, countdown, answer box, voice recorder, evaluation, advance |
| `src/pages/Report.jsx` | Summary, chart, answers, competency table, integrity counts, print |
| `src/pages/Dashboard.jsx` | History table and per-area progress |
| `src/pages/Login.jsx`, `Register.jsx` | Credential forms and validation copy |
| `src/pages/Privacy.jsx`, `Terms.jsx`, `NotFound.jsx` | Static pages |
| `src/hooks/useCountdown.js` | Ticking seconds to a timestamp |
| `src/hooks/useVoiceRecorder.js` | MediaRecorder wrapper, max duration, blob output |
| `src/hooks/useIntegrityMonitor.js` | Buffers copy/paste/tab-switch/focus-loss events |
| `src/hooks/usePageTitle.js` | Sets `document.title` |
| `src/lib/session.js` | `SessionContext` and `useSession()` |
| `src/lib/recentSessions.js` | `ais.recentSessions` in `localStorage` (guest ids only) |
| `src/lib/format.js` | Labels and formatting helpers |
| `src/lib/auth.js` | Password rule and form validators mirroring the backend |
| `src/siteConfig.js` | Site identity, legal text values, answer/recording limits |

There is no Redux/Zustand/Query layer. State is local component state plus one session
context; server data is fetched on mount.

## 3. Session and API integration

`src/api/client.js` is the only HTTP boundary:

- `BASE_URL` is `VITE_API_BASE_URL` or `/api`; a trailing slash is removed.
- Every request uses `credentials: 'same-origin'`. The `HttpOnly` cookie is never read by
  JavaScript and no token is stored anywhere.
- Error bodies are normalised to `ApiError {status, code, message}` for the three backend
  shapes (plain string, coded object, Pydantic array).
- `submitAnswer`, `retryEvaluation` and `advance` retry once after one second when the
  backend reports `interview_busy`.

`SessionProvider` calls `GET /api/v1/auth/me` on mount, then `GET /api/v1/candidates/me`.
`401` means guest; a network failure is also treated as guest so the guest flow never breaks
because accounts are down. `signOut` only reports success after the server confirms the
session is gone; if logout fails, the still-valid session is kept rather than showing a
false signed-out state.

Account API calls use the `/v1/...` prefix (`/api/v1/...` after the proxy keeps it); guest
routes omit it because the proxy strips `/api`.

## 4. Interview room behaviour

`Interview.jsx` is the most stateful screen.

1. **Load** — `GET /interview/{id}`; if completed, replace-navigate to the report. A changed
   `current_question_id` resets the answer, result, voice flag and integrity buffer, then
   loads the question text from `GET /questions/{id}`.
2. **Timer** — `computeDeadlines` turns `seconds_remaining`, `grace_seconds` and
   `deadline_at` into local timestamps; `useCountdown` renders the clock. With zero seconds
   nominal left the UI says "Over time" and counts the grace period.
3. **Auto-submit** — when the nominal timer hits zero, a one-shot effect submits the text
   already typed with `submission_reason: "timeout"`. If the box is empty, nothing is
   submitted; the question times out server-side.
4. **Expiry** — when the grace period ends, recording stops, integrity events are flushed
   and the interview is reloaded to pick up the server's `timed_out` state.
5. **Integrity** — `useIntegrityMonitor` captures `copy`, `paste`, `tab_switch`, `focus_loss`
   (never clipboard content). Up to 50 events ride along with the answer; the rest are
   flushed to `/integrity-events`. Failures are ignored on purpose.
6. **Voice** — `useVoiceRecorder` records up to 60 s; the blob goes to `/transcribe`; the
   transcript is appended to the answer box and the answer is later sent with
   `answer_source: "voice"`. Recording and transcription time count against the question
   timer.
7. **Evaluation** — the response is rendered in `EvaluationPanel`. A `202` shows the retry
   action when `retry_allowed`; `next_action` drives whether "Next question" or "Finish" is
   offered.
8. **Leaving** — a `beforeunload` warning appears while an unsent non-empty answer exists.

## 5. Dashboard

`Dashboard.jsx` reads the account's history from `/api/v1/interviews/me` and every scored
answer from `/candidates/{id}/competency-history`.

Because θ is per interview and resets to 0.50, progress is computed **per area from the most
recent interview only**:

- level = last `new_theta` in that interview;
- change = last θ minus the first `previous_theta`, shown only when that interview has at
  least two scored answers for the area (otherwise `—` with an explanation);
- total answers across interviews is displayed separately.

The section labels every value as an estimate and never claims improvement from one answer.
A failed progress request renders its own alert instead of looking like "no data".

## 6. Styling and assets

- One global stylesheet, `src/index.css`; no CSS framework or CSS-in-JS.
- Fonts are self-hosted through `@fontsource-variable/archivo` and
  `@fontsource-variable/source-serif-4`.
- Icons come from `lucide-react`.
- `index.html` carries the title/description/favicons; `public/` holds the favicon set and
  `_redirects` for hosts that use it.
- Utility classes used across pages: `container`, `section`, `table`, `alert alert-error`,
  `btn btn-primary`, `muted`, `small`, `meter`.
- `ErrorBoundary` is not implemented; a render error surfaces as a blank page.

## 7. Loading, empty and error states

| Surface | Loading | Empty | Error |
| --- | --- | --- | --- |
| Session | "Loading your account" | guest | network failure treated as guest |
| Topics (`Start`, `Home`) | disabled select (`Start`); section hidden (`Home`) | no topics listed | `Start` shows an alert; `Home` ignores the error |
| Interview | "Loading interview" | "No question available" with a link to `/start` | `401` sign-in panel, otherwise the error message |
| Report | "Loading report" | sections are omitted when empty | `401` sign-in panel, otherwise "Report not available" |
| Dashboard | `-` placeholders | "no interviews yet" copy | history alert and a separate progress alert |
| Evaluation | busy buttons | `202` retry panel | inline alert, `409` refreshes state |

## 8. Build and configuration

| Command | Effect |
| --- | --- |
| `npm run dev` | Vite dev server on 5173 with the `/api` proxy |
| `npm run build` | Production bundle in `dist/` (the report chunk is separate) |
| `npm run preview` | Serves `dist/` without the API proxy |
| `npm run lint` | ESLint over the project |
| `npm run check:launch` | Deployment checklist (fails while `TODO_` values remain) |

`vite.config.js` keeps `changeOrigin: false` on purpose: the backend's CSRF check compares
`Origin` with `Host`, so rewriting the host makes a same-origin sign-out look cross-site.

`src/siteConfig.js` currently contains `TODO_` placeholders for the domain, operator,
contact email, policy date, governing law, AI provider, database host and retention period.
Until they are filled in, the legal pages display placeholders and `check:launch` fails.

## 9. Known frontend limitations

- No automated tests, no TypeScript, no visual regression coverage.
- React StrictMode double-invokes effects in development, so some GET requests appear twice
  in the network panel. This is expected in dev builds, not in production.
- In practice, signing out from `/dashboard` can land on `/login`: the layout navigates to
  `/`, but the still-mounted guard redirects to `/login` as the session clears.
- The device-local guest list (`ais.recentSessions`) is capped at 10 entries and can be
  cleared, but never synced to an account.
- Audio recording support depends on `MediaRecorder`; unsupported browsers hide recording
  and keep the text flow.
- `axios` is declared in `package.json` but not imported anywhere; the client uses `fetch`.
