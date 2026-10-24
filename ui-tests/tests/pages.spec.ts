// Each page of the definition opens in both color modes, without errors,
// and looks like its approved screenshot.
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

import { type ExpectedPage, expected, modeOf, pathPattern, UNKNOWN_ID } from "./expected";
import { firstRecordLink } from "./links";

const SCREENSHOTS = fileURLToPath(new URL(`../screenshots/${expected.binding}/`, import.meta.url));
/** The today of the browser: the center of the mock and seed dates (BASE_DATE). */
const TODAY = new Date("2026-01-05T12:00:00Z");

/**
 * Return a path of a page with path parameters: the first link to the
 * page on its parent page, else the page with an ID that does not exist.
 */
async function samplePath(page: Page, target: ExpectedPage): Promise<string> {
  const parent = target.path.slice(0, target.path.indexOf("/{")) || "/";
  const href = await firstRecordLink(page, parent, pathPattern(target.path));
  return href ?? target.path.replace(/\{[^}]+\}/g, UNKNOWN_ID);
}

for (const target of expected.pages) {
  test(`the page ${target.name} opens`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    // The pages show dates relative to today. A fixed today near the
    // mock and seed dates keeps the screenshots the same on each day.
    await page.clock.setFixedTime(TODAY);
    const path = target.params.length ? await samplePath(page, target) : target.path;

    const response = await page.goto(path);
    expect(response?.status()).toBeLessThan(400);
    if (target.detail) {
      // The name of the record is the only main heading. The page title is a small label.
      await page.waitForLoadState("networkidle");
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.locator("h1")).not.toHaveText(target.title);
      await expect(page.locator("main").getByText(target.title, { exact: true }).first()).toBeVisible();
    } else {
      await expect(page.locator("h1").first()).toHaveText(target.title);
    }
    await page.waitForLoadState("networkidle");

    const mode = modeOf(testInfo.project.name);
    mkdirSync(`${SCREENSHOTS}${mode}`, { recursive: true });
    await page.screenshot({ path: `${SCREENSHOTS}${mode}/${target.name}.png`, fullPage: true });
    expect(errors).toEqual([]);
    // Compare the page with its approved screenshot in
    // ui-tests/approved/<binding>/<mode>/ (see CONTRIBUTING.md).
    await expect(page).toHaveScreenshot([expected.binding, mode, `${target.name}.png`], { fullPage: true });
  });
}
