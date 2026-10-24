// The breadcrumb of a page in the menu uses the label of the menu item.
// The test uses the project tracker: the menu item of the page task_board
// says "Task board", and the page title is "Tasks".
import { expect, test } from "@playwright/test";

import { expected } from "./expected";

const board = expected.pages.find((p) => p.name === "task_board");

test("the breadcrumb of the task board uses the label of the menu", async ({ page }) => {
  test.skip(board === undefined, "The definition has no page task_board.");
  await page.goto(board?.path ?? "/");
  await page.waitForLoadState("networkidle");
  const current = page.locator('nav[aria-label="breadcrumb"] [aria-current="page"]');
  await expect(current).toHaveText("Task board");
  await expect(page.getByRole("link", { name: "Task board", exact: true }).first()).toBeVisible();
});
