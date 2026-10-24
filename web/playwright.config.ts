import { defineConfig } from "@playwright/test";

// Smoke test runs against a combined API+static server (default http://127.0.0.1:8100).
// Start it with:  cd ../api && STATIC_DIR=../web/out uv run uvicorn rainready.main:app --port 8100
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "test-results/smoke.json" }]],
  use: {
    baseURL: process.env.RR_BASE_URL ?? "http://127.0.0.1:8100",
    headless: true,
    viewport: { width: 1400, height: 900 },
    screenshot: "only-on-failure",
  },
});
