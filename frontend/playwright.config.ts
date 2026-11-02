import { defineConfig } from "@playwright/test";

// Acceptance flow against the real backend (python -m agentqa ui on 8700, serving the built app at /app).
export default defineConfig({
  testDir: "e2e",
  timeout: 10 * 60 * 1000,
  retries: 0,
  use: {
    baseURL: process.env.AGENTQA_BASE_URL ?? "http://127.0.0.1:8700",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
});
