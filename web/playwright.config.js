// @ts-check
import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against a real backend + Postgres + Redis (docker compose up, or the host
 * dev servers) -- these are end-to-end tests through the actual browser, not
 * component tests. See e2e/README.md for what's covered and what isn't.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
