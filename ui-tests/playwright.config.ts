// The Playwright UI tests of the generated front ends (Next.js and React).
// scripts/smoke_test.py --ui starts an app, writes expected/<binding>.json, and runs
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
  // APPGEN_UI_OUTPUT names another folder, so that the checks of two apps
  // can run at the same time. Playwright empties the folder first.
  outputDir: process.env.APPGEN_UI_OUTPUT || "test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  // The approved screenshots: approved/<binding>/<mode>/<page>.png. A
  // page fails when more than 0.1 % of its pixels differ.
  snapshotPathTemplate: "{testDir}/../approved/{arg}{ext}",
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.001, animations: "disabled", caret: "hide" },
  },
  use: {
    baseURL: process.env.APPGEN_BASE_URL ?? "http://localhost:3000",
    launchOptions: { executablePath },
    // The charts (Recharts) do not animate when the system asks for
    // reduced motion, so the screenshots show the charts at their end
    // state. The apps keep the animation for other users.
    contextOptions: { reducedMotion: "reduce" },
    // A fixed locale and time zone keep the screenshots the same on each machine.
    locale: "en-US",
    timezoneId: "UTC",
  },
  // One project for each color mode. The apps follow the mode of the
  // system (`ui.theme.default_mode: system`).
  projects: [
    { name: "light", use: { ...devices["Desktop Chrome"], colorScheme: "light" } },
    { name: "dark", use: { ...devices["Desktop Chrome"], colorScheme: "dark" } },
  ],
});
