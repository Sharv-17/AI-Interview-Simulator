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
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
