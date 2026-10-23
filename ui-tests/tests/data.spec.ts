// The list pages and the detail pages show records: the Next.js app runs
// with the seed records, and the React app with its mock records.
import { expect, test } from "@playwright/test";

import { expected, pathPattern, UNKNOWN_ID } from "./expected";

for (const target of expected.pages.filter((p) => p.params.length)) {
  const parent = target.path.slice(0, target.path.indexOf("/{")) || "/";

  test(`the page ${parent} links to records of the page ${target.name}`, async ({ page }) => {
    await page.goto(parent);
    await page.waitForLoadState("networkidle");
    const pattern = pathPattern(target.path);
    const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
    const records = hrefs.filter((href) => pattern.test(href));
    expect(records.length, `links to ${target.path} on ${parent}`).toBeGreaterThan(0);

    const response = await page.goto(records[0]);
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
