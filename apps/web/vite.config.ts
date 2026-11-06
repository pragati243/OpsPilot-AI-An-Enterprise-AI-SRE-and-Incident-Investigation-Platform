import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Not 5173: another project on this dev machine already holds it.
    // strictPort so a silent fallback never drifts out of sync with the
    // backend's CORS allowlist (app/core/config.py::cors_allow_origins).
    port: 5180,
    strictPort: true,
  },
})
