// The live updates (ADR 0051): a change of a record in one browser shows
// in the open view of another browser at once, without a reload. The test
// uses the project tracker: a second browser adds a task on the page of a
// project, renames it on the page of the task, and deletes it. The task
// board of the first browser shows each change in less than LIVE_LIMIT_MS.
// The new task is done, so that it is in a short column of the board.
import { expect, type Page, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";
import { saveAndClose } from "./forms";
import { firstRecordLink } from "./links";

/** The longest time from the end of a change in one browser to the view of another browser. */
const LIVE_LIMIT_MS = 2_000;

const board = expected.pages.find((p) => p.name === "task_board");
const project = expected.pages.find((p) => p.name === "project_detail");
const detail = expected.pages.find((p) => p.name === "task_detail");
const live = expected.live?.includes("Task") ?? false;

/** Open the board, and wait until its stream of the live updates is open. */
async function openBoard(page: Page): Promise<void> {
  const stream = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/live"));
  await page.goto(board?.path ?? "/");
  expect((await stream).status()).toBe(200);
  await expect(page.locator('section[aria-label="Done"]')).toBeVisible();
}

test("a change of a task in one browser shows at once on the board of another browser", async ({ page, browser }, testInfo) => {
  test.skip(!live || !board || !project || !detail, "The app has no live tasks, or not the pages of the test.");
  await openBoard(page);

  const other = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
    colorScheme: testInfo.project.use.colorScheme,
    locale: "en-US",
    timezoneId: "UTC",
  });
  const editor = await other.newPage();
  try {
    const title = `Live task ${testInfo.project.name} ${Date.now()}`;
    const href = await firstRecordLink(editor, "/projects", pathPattern(project?.path ?? ""));
    expect(href, "a link to a project").toBeDefined();
    await editor.goto(href ?? "");
    // The stream of the live updates does not count for the idle network.
    await editor.waitForLoadState("networkidle");
    await editor.getByRole("button", { name: "New task", exact: true }).first().click();
    const form = editor.getByRole("dialog");
    // The title is translatable: the first field is the title in English.
    await form.getByRole("textbox", { name: /^Title/ }).first().fill(title);
    const status = form.getByRole("combobox", { name: "Status", exact: true });
    // Under load, the list can ignore a click that comes too soon after it opens: try again
    // until the list closes with the value.
    await expect(async () => {
      if (!(await editor.getByRole("listbox").isVisible())) {
        await status.click({ timeout: 2_000 });
      }
      await editor.getByRole("option", { name: "Done", exact: true }).click({ timeout: 2_000 });
      await expect(status).toHaveText("Done", { timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    // One click only: a second click would add a second task.
    await form.getByRole("button", { name: "Create task", exact: true }).click();
    await expect(form).toBeHidden();
    await expect(page.getByText(title, { exact: true })).toBeVisible({ timeout: LIVE_LIMIT_MS });

    // The tab of the tasks of the project links to the new task.
    await editor.getByRole("tab", { name: "Tasks" }).click();
    await editor.getByRole("link", { name: title, exact: true }).first().click();
    await expect.poll(() => new URL(editor.url()).pathname).toMatch(pathPattern(detail?.path ?? ""));
    await editor.waitForLoadState("networkidle");
    await editor.getByRole("button", { name: "Edit", exact: true }).first().click();
    const sheet = editor.getByRole("dialog");
    const renamed = `${title} renamed`;
    await sheet.getByRole("textbox", { name: /^Title/ }).first().fill(renamed);
    await saveAndClose(sheet);
    await expect(page.getByText(renamed, { exact: true })).toBeVisible({ timeout: LIVE_LIMIT_MS });
    await expect(page.getByText(title, { exact: true })).toBeHidden();

    await editor.getByRole("button", { name: "Delete", exact: true }).first().click();
    await editor.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();
    await expect(editor.getByText("The task is deleted.")).toBeVisible();
    await expect(page.getByText(renamed, { exact: true })).toBeHidden({ timeout: LIVE_LIMIT_MS });
  } finally {
    await other.close();
  }
});
