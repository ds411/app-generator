// The Playwright UI tests of the generated front ends (Next.js and React).
// scripts/smoke_test.py --ui starts an app, writes expected.json, and runs
// these tests with APPGEN_BASE_URL.
import { defineConfig, devices } from "@playwright/test";

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.APPGEN_BASE_URL ?? "http://localhost:3000",
    launchOptions: { executablePath },
  },
  // One project for each color mode. The apps follow the mode of the
  // system (`ui.theme.default_mode: system`).
  projects: [
    { name: "light", use: { ...devices["Desktop Chrome"], colorScheme: "light" } },
    { name: "dark", use: { ...devices["Desktop Chrome"], colorScheme: "dark" } },
  ],
});
