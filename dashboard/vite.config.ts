import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by the backend at /dashboard/. In dev, `npm run dev` proxies the admin APIs
// to a backend on :8000, so the browser only ever talks to one origin.
export default defineConfig({
  base: "/dashboard/",
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: { outDir: "dist", assetsInlineLimit: 0 },
});
