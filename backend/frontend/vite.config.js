import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development, requests to /api/* are forwarded to the FastAPI backend on port 8000,
// so the browser never needs CORS. In production, set VITE_API_BASE_URL (see .env.example).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Account routes live under /api/v1/* on the backend and must keep that prefix.
      // Object order decides which prefix matches first, so this rule comes before /api.
      // changeOrigin must stay false: the backend's CSRF check compares the request
      // `Origin` with the request `Host`. Rewriting Host to :8000 makes a same-origin
      // sign-out look cross-site, so it is rejected with 403, the session is never
      // revoked, and the next reload signs the user back in.
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
