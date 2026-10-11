import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev (`npm run dev`), /api is proxied to the backend just like nginx does in compose,
// so the browser always sees a single origin (DECISIONS D-017). Assumes the backend is on
// localhost:8000 (the compose default); edit here if you run it elsewhere.
const apiTarget = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: apiTarget, changeOrigin: true } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
