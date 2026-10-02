import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative asset paths: the same build is served at the pages.dev root and,
// through the personal site's proxy, under mingslab.com/pulse_database/.
// `npm run dev` forwards api/* to `wrangler pages dev` (functions/ + D1) on :8788.
export default defineConfig({
  base: "./",
  plugins: [react()],
  // leaflet + chart.js + react in one ~170 kB (gzip) bundle is fine here
  build: { chunkSizeWarningLimit: 700 },
  server: {
    proxy: { "/api": "http://localhost:8788" },
  },
});
