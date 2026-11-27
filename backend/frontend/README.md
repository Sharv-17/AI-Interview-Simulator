# Frontend (React + Vite)

The React 19 single-page app for the AI Interview Simulator. It is served from its own origin
and proxies `/api` to the FastAPI backend, so the session cookie stays first-party.

## Run it

```bash
npm install
npm run dev        # http://localhost:5173, expects the API on http://localhost:8000
```

## Build and check

```bash
npm run lint
npm run build
npm run check:launch   # deployment checklist; fails while TODO_ placeholders remain
```

## Where to read more

- [SETUP.md](SETUP.md) — file map, routes, account behaviour, same-origin deployment.
- [../../docs/FRONTEND.md](../../docs/FRONTEND.md) — architecture, state, interview-room
  behaviour, error states.
- [../../docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md) — full local setup, environment
  variables and deployment requirements.

## Configuration

- `VITE_API_BASE_URL` (default `/api`) must stay relative in the supported deployment.
- `src/siteConfig.js` holds site identity and legal values, plus `MAX_RECORDING_SECONDS` and
  `MAX_ANSWER_CHARS`, which must match the backend settings.
- `vite.config.js` keeps `changeOrigin: false` because the backend's CSRF check compares the
  request `Origin` with its `Host`.
