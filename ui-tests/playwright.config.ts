// The Playwright UI tests of the generated front ends (Next.js and React).
// scripts/smoke_test.py --ui starts an app, writes expected.json, and runs
// these tests with APPGEN_BASE_URL.
import { existsSync } from "node:fs";
import { chromium, defineConfig, devices } from "@playwright/test";

// The Chromium of the tests: PLAYWRIGHT_CHROMIUM_EXECUTABLE, else the
// Chromium that Playwright installs (`playwright install chromium`).
// If Playwright has not installed its Chromium, use the Chromium of the
// environment: Claude Code cloud sessions have one at SYSTEM_CHROMIUM,
// with a version that can differ from the version of Playwright.
const SYSTEM_CHROMIUM = "/opt/pw-browsers/chromium";

function chromiumExecutable(): string | undefined {
  const fromEnv = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  if (fromEnv) return fromEnv;
  if (existsSync(chromium.executablePath())) return undefined;
  return existsSync(SYSTEM_CHROMIUM) ? SYSTEM_CHROMIUM : undefined;
}

const executablePath = chromiumExecutable();

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
