import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dev server proxies /api to the FastAPI backend so the frontend can use
// relative URLs and never hits CORS in development.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Build into the repo-root `public/` so Vercel's FastAPI runtime serves the
  // SPA (and the pre-baked /boundaries/*.json) as static CDN assets, while the
  // FastAPI function handles /api/*.
  build: {
    outDir: '../public',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
