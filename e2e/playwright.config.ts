import { defineConfig } from "@playwright/test";

// Runs inside the official Playwright image on the compose network of an isolated stack
// (scripts/e2e.sh): BASE_URL is the nginx frontend, MAILPIT_URL that stack's Mailpit.
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1, // tests are independent (unique events/emails), but one worker keeps timing honest
  retries: 0, // a flaky E2E test is a failing E2E test
  reporter: [["list"], ["junit", { outputFile: process.env.JUNIT_FILE ?? "/reports/e2e.xml" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://frontend",
    timezoneId: "UTC",
    locale: "en-US",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  outputDir: "/tmp/playwright-results",
});
