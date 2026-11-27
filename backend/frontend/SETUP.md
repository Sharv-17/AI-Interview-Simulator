# Frontend setup

All paths below are relative to the repository root (`AI-Interview-Simulator/`).
The frontend lives in `backend/frontend/`, where your Vite project already is.

## 1. What is in this folder

The application is already in place. The Vite starter files it replaced (`src/App.css`,
`src/assets/`, `public/icons.svg`) are not part of the project, so nothing has to be deleted
before running it.

## 2. File map

Every file below exists in the repository; the table explains what each one does.

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
| `backend/frontend/src/pages/Home.jsx` | `/guest` (landing page) |
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
The example file sets `STORAGE_BACKEND=postgres`, so also set `DATABASE_URL` and run
`alembic upgrade head`; alternatively set `STORAGE_BACKEND=memory` to skip PostgreSQL (data is
lost on restart). See [../../docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md).

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

## 4. Accounts, guest access and routing

### Routes

| Route | Page | Purpose |
|---|---|---|
| `/` | `src/App.jsx` | Sign-in form for a guest, dashboard for a signed-in account |
| `/login` | `src/pages/Login.jsx` | Email and password form, password toggle, link to registration, Continue as Guest |
| `/register` | `src/pages/Register.jsx` | Full name, email, password and confirmation, Terms and Privacy links, Continue as Guest |
| `/guest` | `src/pages/Home.jsx` | The home page and the guest interview entry point |
| `/dashboard` | `src/pages/Dashboard.jsx` | Protected: name, email, interview history, reports, sign out |
| `/start` | `src/pages/Start.jsx` | Interview setup, open to guests and accounts |
| `/interview/:id`, `/report/:id` | unchanged | Existing interview and report links |

`/dashboard` is the only guarded route, and `/` shows the sign-in form instead of redirecting. Interview and report links are never redirected to the sign-in page: a guest interview has to stay openable from its link, and a report that belongs to an account answers `401`, which the report page explains with a sign-in link.

### How sign-in works

- `POST /api/v1/auth/login` sets an `HttpOnly`, `Secure`, `SameSite=Lax` cookie. The session token never reaches JavaScript and is never written to `localStorage`.
- The browser talks to its own origin only. `vite.config.js` forwards `/api/v1/*` with the prefix kept and `/api/*` with it stripped; `vercel.json` does the same in production. That keeps the cookie first-party and avoids CORS preflight.
- `src/components/SessionProvider.jsx` asks `GET /api/v1/auth/me` on load and after sign-in or sign-out. A `401` means guest. `src/lib/session.js` exposes `useSession()`.
- CSRF protection stays on: the backend checks `Sec-Fetch-Site` and `Origin`, so `AUTH_ALLOWED_ORIGINS` must list the frontend origin (see section 5).
- Every `/api/v1/*` response, including errors, carries `Cache-Control: no-store`.

### Registration and the candidate record

The form keeps its name field and sends it as `display_name`. The backend stores it on the candidate created with the account, in the same transaction (`AuthStore.create_user`), so registration never creates a second candidate and never re-points an existing one.

### Account interviews

`src/pages/Start.jsx` takes the account's candidate id from `GET /api/v1/candidates/me` and sends it as `candidate_id`. Guests keep sending no `candidate_id`, so cooldown, adaptive selection, scoring and timer behaviour are unchanged. Interviews started this way appear in `GET /api/v1/interviews/me`, which is what the dashboard lists.

Guest interviews remain in the browser list from `src/lib/recentSessions.js` and are not claimed by an account. The dashboard says so, and it never mixes the two lists.

### Endpoints used

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/v1/auth/register` | `{email, password, display_name?}` | `201` user; `409` if the email is taken |
| `POST /api/v1/auth/login` | `{email, password}` | `200` user plus session cookie; `401 invalid_credentials`; `429 rate_limited` |
| `POST /api/v1/auth/logout` | empty | `204`, clears the cookie |
| `GET /api/v1/auth/me` | none | `200` user or `401` |
| `GET /api/v1/candidates/me` | none | `200` the account's candidate or `401` |
| `GET /api/v1/interviews/me` | none | `200` interviews of that candidate, oldest first |

Passwords must be 12 to 128 characters; `src/lib/auth.js` mirrors that rule and the error copy.

## 5. Deploy with the same-origin proxy

1. Fill in every `TODO_` value in `src/siteConfig.js`.
2. Deploy the backend and give it a domain, for example `api.your-domain.com`.
3. Configure the backend environment:
   - `AUTH_COOKIE_SECURE=true`
   - `AUTH_ALLOWED_ORIGINS=https://www.your-domain.com` (comma separated for more origins). Behind the proxy the request host is the API host while `Origin` is the frontend, so without this value sign-out and other state-changing calls are rejected.
   - Leave `AUTH_COOKIE_DOMAIN` unset: the cookie is set on your proxied origin and must stay host-only.
   - Leave `AUTH_TRUST_PROXY=false` unless the backend is reachable only through your proxy. While it is false, rate limiting counts all proxied traffic as one address.
4. In `backend/frontend/vercel.json`, replace `https://api.your-domain.com` in both rewrites with the real backend origin. Order matters: `/api/v1/*` keeps its prefix (accounts), `/api/*` strips it (guest API), and the last rule serves `index.html` while excluding `/api/`.
5. Create `backend/frontend/.env.production` with `VITE_API_BASE_URL=/api`.
6. Run `npm run check:launch`. It also checks the rewrite order and the `/api/v1` cache header.
7. Run `npm run build` and deploy the `dist/` folder together with `vercel.json`, on Vercel or any host that supports rewrites. Confirm it loads over HTTPS.
8. On a preview deployment, sign in and inspect cookies in DevTools: exactly one session cookie, `HttpOnly`, `Secure`, `SameSite=Lax`, on your own domain. Reload the page and confirm `/api/v1/auth/me` returns `200`, then sign out and confirm it returns `401`.
9. Voice answers travel through the same proxy. The backend allows 10 MiB audio uploads, but Vercel rejects request bodies below that, so keep voice answers short or lower `MAX_AUDIO_UPLOAD_BYTES`.
