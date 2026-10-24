// Each page of the definition opens in both color modes, without errors.
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

import { type ExpectedPage, expected, modeOf, pathPattern, UNKNOWN_ID } from "./expected";

const SCREENSHOTS = fileURLToPath(new URL(`../screenshots/${expected.binding}/`, import.meta.url));

/**
 * Return a path of a page with path parameters: the first link to the
 * page on its parent page, else the page with an ID that does not exist.
 */
async function samplePath(page: Page, target: ExpectedPage): Promise<string> {
  const parent = target.path.slice(0, target.path.indexOf("/{")) || "/";
  await page.goto(parent);
  await page.waitForLoadState("networkidle");
  const pattern = pathPattern(target.path);
  const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
  return hrefs.find((href) => pattern.test(href)) ?? target.path.replace(/\{[^}]+\}/g, UNKNOWN_ID);
}

for (const target of expected.pages) {
  test(`the page ${target.name} opens`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
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
  });
}
