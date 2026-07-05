import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Internal tool: no SSR, fast dev loop (spec §9.1).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: true,
    port: 5173,
    // Mirror the prod reverse proxy so dev is same-origin too: the SPA calls
    // /api/planning and /api/scheduler at :5173, and Vite forwards them to the
    // running services with the /api/<svc> prefix stripped (matching nginx). This is
    // what makes the session cookie first-party in dev as well.
    proxy: {
      "/api/planning": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/planning/, ""),
      },
      "/api/scheduler": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/scheduler/, ""),
        // Keep the SSE status stream flowing (no buffering) in dev.
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => proxyReq.setHeader("connection", "keep-alive"));
        },
      },
    },
  },
});
