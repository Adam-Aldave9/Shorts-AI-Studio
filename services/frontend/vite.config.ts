import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Proxy targets are env-configurable so the same dev server works both on the host
// (`npm run dev` -> the APIs on localhost's published ports) and inside a container
// (docker-compose.override.yml -> the APIs by compose service name). Defaults keep
// the plain host workflow unchanged.
const planningTarget = process.env.PLANNING_PROXY_TARGET ?? "http://localhost:8000";
const schedulerTarget = process.env.SCHEDULER_PROXY_TARGET ?? "http://localhost:8001";
// Docker Desktop doesn't forward host FS events into the Linux VM, so in-container
// dev must poll to see edits. Off by default (host inotify works fine).
const usePolling = process.env.VITE_USE_POLLING === "true";

// Internal tool: no SSR, fast dev loop (spec §9.1).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: true,
    port: 5173,
    watch: usePolling ? { usePolling: true } : undefined,
    // Mirror the prod reverse proxy so dev is same-origin too: the SPA calls
    // /api/planning and /api/scheduler at :5173, and Vite forwards them to the
    // running services with the /api/<svc> prefix stripped (matching nginx). This is
    // what makes the session cookie first-party in dev as well.
    proxy: {
      "/api/planning": {
        target: planningTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/planning/, ""),
      },
      "/api/scheduler": {
        target: schedulerTarget,
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
