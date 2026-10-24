// Each action shows one time on a page: a page or a view does not show an
// action that the top bar also has. The test uses the project tracker:
// its top bar, its task board, and its project detail page have the
// action "New task".
import { expect, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";

for (const name of ["task_board", "project_detail"]) {
  const target = expected.pages.find((p) => p.name === name);

  test(`the page ${name} shows the action "New task" one time`, async ({ page }) => {
    test.skip(target === undefined, `The definition has no page ${name}.`);
    let path = target?.path ?? "/";
    if (target?.params.length) {
      const parent = path.slice(0, path.indexOf("/{")) || "/";
      await page.goto(parent);
      await page.waitForLoadState("networkidle");
      const pattern = pathPattern(path);
      const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
      path = hrefs.find((href) => pattern.test(href)) ?? path;
    }
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "New task", exact: true })).toHaveCount(1);
  });
}
