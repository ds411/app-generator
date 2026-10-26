// An event runs its operation after a change of a record (ADR 0031). The
// test uses the project tracker: a new status of a task runs the
// operation record_completion of the event `changed`. Its hand-written
// code (examples/project-tracker/extensions/) sets the completion time of
// a done task, and clears it for other tasks, and the task detail page
// shows the time. The test uses the second task of the task board, and
// gives it its status again at the end, so that the screenshots of the
// pages do not change.
import { expect, type Locator, type Page, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";
import { recordLink } from "./links";

const detail = expected.pages.find((p) => p.name === "task_detail");

/** Open the form "Edit task", select a status, and save. Return the status before the change. */
async function setStatus(page: Page, status: string): Promise<string> {
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  const select = sheet.getByRole("combobox", { name: "Status", exact: true });
  const before = (await select.innerText()).trim();
  await select.click();
  await page.getByRole("option", { name: status, exact: true }).click();
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  return before;
}

/** Return the value of a field in the sections of the detail page. */
function fieldValue(page: Page, label: string): Locator {
  return page.locator("dt", { hasText: new RegExp(`^${label}$`) }).locator("xpath=following-sibling::dd[1]");
}

test("a new status of a task runs its event: the task gets or loses its completion time", async ({ page }) => {
  test.skip(detail === undefined, "The definition has no page task_detail.");
  const href = await recordLink(page, "/tasks", pathPattern(detail?.path ?? ""), 1);
  expect(href, "a link to the second task").toBeDefined();
  await page.goto(href ?? "");
  await page.waitForLoadState("networkidle");

  const completedAt = fieldValue(page, "Completed at");
  const original = await setStatus(page, "In review");
  // A status other than done clears the time. A change from In review to
  // In review is no change, so the test starts with another status then.
  if (original === "In review") {
    await setStatus(page, "In progress");
  }
  await expect(completedAt).toHaveText("—");
  await setStatus(page, "Done");
  await expect(completedAt).not.toHaveText("—");
  if (original !== "Done") {
    await setStatus(page, original);
    await expect(completedAt).toHaveText("—");
  }
});
