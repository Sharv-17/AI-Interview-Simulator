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
| `backend/frontend/src/components/EvaluationPanel.jsx` | Score and feedback block |
| `backend/frontend/src/components/ScoreChart.jsx` | Bar chart on the report |
| `backend/frontend/src/pages/Home.jsx` | `/` |
| `backend/frontend/src/pages/Start.jsx` | `/start` |
| `backend/frontend/src/pages/Interview.jsx` | `/interview/:id` |
| `backend/frontend/src/pages/Report.jsx` | `/report/:id` |
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

## 4. Before you launch

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
7. Add sign-in to the report endpoints before real users arrive: the backend has no authentication, so anyone with an interview link can read that report.
