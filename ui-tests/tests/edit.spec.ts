// An edit of a record shows at once in the page: the breadcrumb shows the
// new name. The test uses the project tracker: its project detail page
// has the action "Edit" with the form "Edit project".
import { expect, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";
import { saveAndClose } from "./forms";
import { firstRecordLink } from "./links";

const detail = expected.pages.find((p) => p.name === "project_detail");

test("the breadcrumb shows the new name of a record after an edit", async ({ page }, testInfo) => {
  test.skip(detail === undefined, "The definition has no page project_detail.");
  const pattern = pathPattern(detail?.path ?? "");
  const href = await firstRecordLink(page, "/projects", pattern);
  expect(href, "a link to a project").toBeDefined();
  await page.goto(href ?? "");
  await page.waitForLoadState("networkidle");

  const current = page.locator('nav[aria-label="breadcrumb"] [aria-current="page"]');
  await expect(current).not.toHaveText("");
  const name = `Edited project ${testInfo.project.name}`;
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  const input = sheet.getByRole("textbox", { name: "Name", exact: true });
  await input.fill(name);
  await expect(input).toHaveValue(name);
  await saveAndClose(sheet);
  await expect(current).toHaveText(name);
});
