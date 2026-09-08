import { defineConfig, devices } from "@playwright/test";

/**
 * Frontend end-to-end tests. Expects the full stack already running
 * (`docker compose up -d` + seeded), reachable at PLAYWRIGHT_BASE_URL
 * (default http://localhost:3000). CI brings the stack up in a dedicated job.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
