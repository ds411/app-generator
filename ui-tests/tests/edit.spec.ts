// An edit of a record shows at once in the page: the breadcrumb shows the
// new name. The test uses the project tracker: its project detail page
// has the action "Edit" with the form "Edit project".
import { expect, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";

const detail = expected.pages.find((p) => p.name === "project_detail");

test("the breadcrumb shows the new name of a record after an edit", async ({ page }, testInfo) => {
  test.skip(detail === undefined, "The definition has no page project_detail.");
  const pattern = pathPattern(detail?.path ?? "");
  await page.goto("/projects");
  await page.waitForLoadState("networkidle");
  const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
  const href = hrefs.find((h) => pattern.test(h));
  expect(href, "a link to a project").toBeDefined();
  await page.goto(href ?? "");
  await page.waitForLoadState("networkidle");

  const current = page.locator('nav[aria-label="breadcrumb"] [aria-current="page"]');
  await expect(current).not.toHaveText("");
  const name = `Edited project ${testInfo.project.name}`;
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  await sheet.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  await expect(current).toHaveText(name);
});
