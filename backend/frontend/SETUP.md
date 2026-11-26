# Frontend setup

All paths below are relative to the repository root (`AI-Interview-Simulator/`).
The frontend lives in `backend/frontend/`, where your Vite project already is.

## 1. Delete these Vite starter files

```
backend/frontend/src/App.css
backend/frontend/src/assets/            (whole folder: hero.png, react.svg, vite.svg)
backend/frontend/public/icons.svg
```

## 2. Put each file in place

Replace the file if it already exists, create it if it does not.

| File | What it does |
|---|---|
| `backend/frontend/index.html` | Page title, description, favicon links |
| `backend/frontend/vite.config.js` | Forwards `/api` to the backend on port 8000 |
| `backend/frontend/package.json` | Adds the `check:launch` script |
| `backend/frontend/.env.example` | Template for the production API URL |
| `backend/frontend/vercel.json` | Page routing on Vercel |
| `backend/frontend/public/_redirects` | Page routing on Netlify / Cloudflare Pages |
| `backend/frontend/public/favicon.svg` | Favicon |
| `backend/frontend/public/favicon.ico` | Favicon for older browsers |
| `backend/frontend/public/apple-touch-icon.png` | Icon for phone home screens |
| `backend/frontend/scripts/prelaunch-check.mjs` | Launch checklist script |
| `backend/frontend/src/main.jsx` | App entry, router |
| `backend/frontend/src/App.jsx` | Routes |
| `backend/frontend/src/index.css` | All styles |
| `backend/frontend/src/siteConfig.js` | Your name, email, domain etc. **Fill in before launch** |
| `backend/frontend/src/api/client.js` | Every call to the backend |
| `backend/frontend/src/lib/format.js` | Formatting helpers |
| `backend/frontend/src/lib/recentSessions.js` | Remembers recent interviews in the browser |
| `backend/frontend/src/hooks/useCountdown.js` | Question timer |
| `backend/frontend/src/hooks/useIntegrityMonitor.js` | Copy / paste / tab-switch notes |
| `backend/frontend/src/hooks/useVoiceRecorder.js` | Microphone recording |
| `backend/frontend/src/hooks/usePageTitle.js` | Browser tab titles |
| `backend/frontend/src/components/Layout.jsx` | Header and footer |
| `backend/frontend/src/components/AuthShell.jsx` | Two-column layout used by the sign-in and registration pages |
| `backend/frontend/src/components/EvaluationPanel.jsx` | Score and feedback block |
| `backend/frontend/src/components/ScoreChart.jsx` | Bar chart on the report |
| `backend/frontend/src/pages/Home.jsx` | `/` |
| `backend/frontend/src/pages/Start.jsx` | `/start` |
| `backend/frontend/src/pages/Interview.jsx` | `/interview/:id` |
| `backend/frontend/src/pages/Report.jsx` | `/report/:id` |
| `backend/frontend/src/pages/Login.jsx` | `/login` |
| `backend/frontend/src/pages/Register.jsx` | `/register` |
| `backend/frontend/src/lib/auth.js` | Availability flag and form validators |
| `backend/frontend/src/pages/Privacy.jsx` | `/privacy` |
| `backend/frontend/src/pages/Terms.jsx` | `/terms` |
| `backend/frontend/src/pages/NotFound.jsx` | Any unknown URL |

## 3. Run it locally (in this order)

**Terminal 1: backend** (from the repository root)

```bash
cd backend
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-whisper.txt   # optional: only needed for voice answers
cp .env.example .env                       # Windows: copy .env.example .env
```

Open `backend/.env` and set `LLM_PROVIDER` and its API key. Without them, answers are saved but not scored.

```bash
uvicorn app.main:app --reload --env-file .env
```

Check http://localhost:8000/health shows `{"status":"ok"}`.

**Terminal 2: frontend** (from the repository root)

```bash
cd backend/frontend
npm install
npm run dev
```

Open http://localhost:5173.

## 4. Sign-in pages, guest access and the missing auth API

### Routes

| Route | Page | Purpose |
|---|---|---|
| `/login` | `src/pages/Login.jsx` | Email and password form, password visibility toggle, link to registration, Continue as Guest |
| `/register` | `src/pages/Register.jsx` | Full name, email, password and confirmation, Terms and Privacy links, Continue as Guest |

Both routes sit inside the normal layout. The header gained one "Sign in" link; the footer and the `/`, `/start`, `/interview/:id`, `/report/:id`, `/privacy` and `/terms` routes are unchanged. No route is guarded and nothing redirects to `/login`; a guest can open `/start` directly, as before.

### Current authentication status (important)

The backend has **no authentication endpoints**. `POST /candidates`, `/interview/*` and `/questions` are the whole API, and `app/schemas/candidate.py` says: "Candidates are lightweight records: there is no login in this backend."

So the frontend does **not** fake authentication:

- The forms validate locally (required fields, email shape, password confirmation) and never send credentials anywhere.
- A valid submission shows a notice that accounts are not available yet. Nothing is stored and no signed-in state is claimed.
- No request is made to an invented URL, and no response shape is assumed.
- `src/lib/auth.js` holds `accountsAvailable = false`. When the API below exists, flip it and replace the notice handlers in the two pages with real `api` calls.

Because there is no account system, there is deliberately no "Remember me" checkbox and no "Forgot password" link: neither could work, and no recovery workflow exists. Logout is likewise not implemented.

### Guest flow (unchanged)

- Guest interviews need no account. `/start` calls `POST /interview/start` without a `candidate_id`, exactly as before.
- Guest history is the list of interview IDs kept in this browser by `src/lib/recentSessions.js`. The sign-in pages never read, write or clear it, and never create a candidate.
- Opening `/login` or `/register` creates no anonymous candidate and starts no interview, so no identity is regenerated by visiting them.
- Continue as Guest simply navigates to `/start`.

### Candidate history and account linking

The backend cannot associate a guest's past interviews with an account: interviews store `candidate_id`, but nothing verifies ownership of a candidate, and there is no link or merge operation. Guest history therefore stays in the browser, and signing in (once supported) will not import it. When linking is added it must be a server-validated, idempotent operation that only the owning session can call, so one candidate's history can never be attached to another account.

### Proposed minimum API contract

Implement this on the backend before turning the forms on:

| Endpoint | Request | Response |
|---|---|---|
| `POST /auth/register` | `{full_name, email, password}` | `201 {candidate_id, full_name, email}` plus an `HttpOnly` session cookie; `409 email_taken` |
| `POST /auth/login` | `{email, password}` | `200 {candidate_id, full_name, email}` plus session cookie; `401 invalid_credentials` |
| `POST /auth/logout` | empty | `204`, clears the cookie |
| `GET /auth/me` | — | `200 {candidate_id, full_name, email}` or `401` |
| `POST /auth/claim-guest` | `{guest_candidate_id}` (authenticated) | `200 {linked_interviews: n}`; idempotent |

Requirements that go with it:

- Sessions in `HttpOnly`, `Secure`, `SameSite=Lax` cookies. Never return the session token in the body and never put it in `localStorage`.
- `candidate_id` must come from the session on every authenticated request, never from the request body.
- Passwords hashed with a slow algorithm (argon2id or bcrypt); never logged.
- A documented password policy, mirrored in `src/lib/auth.js` (today there is none, so the form only checks presence and confirmation).
- Rate limiting on `/auth/login` and `/auth/register`, and errors that do not reveal whether an email exists.
- `claim-guest` must reject a `guest_candidate_id` that is already linked to an account.

## 5. Before you launch

1. Fill in every `TODO_` value in `src/siteConfig.js`.
2. Deploy the backend and give it a domain, for example `api.your-domain.com`.
3. Allow your frontend domain in the backend. In `backend/app/main.py`, after `app = FastAPI(...)`, add:

   ```python
   import os
   from fastapi.middleware.cors import CORSMiddleware

   app.add_middleware(
       CORSMiddleware,
       allow_origins=[o.strip() for o in os.environ.get("FRONTEND_ORIGINS", "").split(",") if o.strip()],
       allow_methods=["GET", "POST"],
       allow_headers=["Content-Type"],
   )
   ```

   and set `FRONTEND_ORIGINS=https://your-domain.com` in the backend's environment.
4. Create `backend/frontend/.env.production` containing `VITE_API_BASE_URL=https://api.your-domain.com`.
5. Run `npm run check:launch`. It must print "Launch checklist passed".
6. Run `npm run build` and deploy the `dist/` folder. Connect your custom domain in the host's settings and confirm it loads over HTTPS.
7. Add sign-in to the report endpoints before real users arrive: the backend has no authentication, so anyone with an interview link can read that report. See section 4.
