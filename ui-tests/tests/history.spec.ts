// The change log of a record (ADR 0040): a change of a task shows as an
// entry in the tab "History" of the task detail page, and the restore of
// the entry gives the task its old title back. The test uses the project
// tracker, and the third task of the task list. The restore gives the
// task its title again at the end, so that the screenshots of the pages
// do not change.
import { expect, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";
import { recordLink } from "./links";

const detail = expected.pages.find((p) => p.name === "task_detail");

test("a change of a task shows in its history, and the restore gives the old title back", async ({ page }, testInfo) => {
  test.skip(detail === undefined, "The definition has no page task_detail.");
  const href = await recordLink(page, "/tasks", pathPattern(detail?.path ?? ""), 2);
  expect(href, "a link to the third task").toBeDefined();
  await page.goto(href ?? "");
  await page.waitForLoadState("networkidle");

  const heading = page.locator("h1");
  await expect(heading).not.toHaveText("");
  const original = (await heading.innerText()).trim();
  const title = `${original} (${testInfo.project.name})`;
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  // A translatable title has an input for each language: the first is the default language.
  await sheet.getByRole("textbox", { name: /^Title( \(.+\))?$/ }).first().fill(title);
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  await expect(heading).toHaveText(title);

  await page.getByRole("tab", { name: "History", exact: true }).click();
  const history = page.getByRole("list", { name: "History", exact: true });
  const entry = history.locator("li[data-action=changed]").filter({ hasText: title }).first();
  await expect(entry).toBeVisible();
  await expect(entry).toContainText("Title");
  await expect(entry).toContainText(original);

  await entry.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(heading).toHaveText(original);
  await expect(history.locator("li[data-action=restored]").first()).toContainText(title);
});
