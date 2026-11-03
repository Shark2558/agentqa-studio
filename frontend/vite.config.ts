/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app is served by the backend at /app; in development Vite proxies the API to the backend on 8700.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8700", changeOrigin: false, ws: true } },   // ws: the Live View socket (M1.3)
  },
  // Current browsers understand light-dark() and nested selectors; without these targets the CSS minifier lowers
  // light-dark() into a variable trick that stops following the data-accent attribute (M1.2-UI).
  build: { outDir: "dist", emptyOutDir: true, cssTarget: ["chrome123", "edge123", "firefox120", "safari17.5"] },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
    globals: false,
  },
});
