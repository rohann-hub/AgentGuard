import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by the backend at /dashboard/ by default. Vercel builds with DASHBOARD_BASE=/ (see
// vercel.json). In dev, `npm run dev` proxies the admin APIs to a backend on :8000.
export default defineConfig({
  base: process.env.DASHBOARD_BASE ?? "/dashboard/",
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: { outDir: "dist", assetsInlineLimit: 0 },
});
