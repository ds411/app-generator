// The list pages and the detail pages show records: the Next.js app runs
// with the seed records, and the React app with its mock records.
import { expect, test } from "@playwright/test";

import { expected, pathPattern, UNKNOWN_ID } from "./expected";
import { firstRecordLink } from "./links";

for (const target of expected.pages.filter((p) => p.params.length)) {
  const parent = target.path.slice(0, target.path.indexOf("/{")) || "/";

  test(`the page ${parent} links to records of the page ${target.name}`, async ({ page }) => {
    const href = await firstRecordLink(page, parent, pathPattern(target.path));
    expect(href, `a link to ${target.path} on ${parent}`).toBeDefined();

    const response = await page.goto(href ?? "");
    expect(response?.status()).toBeLessThan(400);
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Nothing here yet", { exact: true })).toHaveCount(0);
  });
}

for (const target of expected.pages.filter((p) => p.detail)) {
  test(`the page ${target.name} with an unknown ID shows the not-found page`, async ({ page }) => {
    test.skip(expected.binding !== "nextjs", "The React app has no server that sets the status.");
    const response = await page.goto(target.path.replace(/\{[^}]+\}/g, UNKNOWN_ID));
    expect(response?.status()).toBe(404);
    await expect(page.locator("h1")).toHaveText("This page does not exist");
    for (const label of target.recordActions) {
      await expect(page.getByRole("button", { name: label })).toHaveCount(0);
    }
  });
}
