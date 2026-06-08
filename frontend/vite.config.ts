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
  },
});
