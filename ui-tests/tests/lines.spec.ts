// A lines editor (ADR 0035): the form "Edit project" of the project
// tracker edits the budget lines of a project. The test adds three lines,
// sees the planned cost of the lines before the save, and saves the
// project with its lines in one request. The form shows the three new
// lines when it opens again. The budget lines show on no page, so the
// screenshots of the pages do not change.
import { expect, type Locator, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";
import { firstRecordLink } from "./links";

const detail = expected.pages.find((p) => p.name === "project_detail");

/** The new lines: an item and an amount. The amounts add up to 2000. */
const LINES = [
  ["Design", "1200"],
  ["Hosting", "300.5"],
  ["Testing", "499.5"],
] as const;

/** Return the number of a currency text, for example 1234.5 for "$1,234.50". */
function amount(text: string): number {
  return Number(text.replace(/[^0-9.-]/g, ""));
}

/** Return the value of the planned cost below the lines editor. */
function plannedCost(editor: Locator): Locator {
  return editor.locator("dt", { hasText: /^Planned cost$/ }).locator("xpath=following-sibling::dd[1]");
}

/**
 * Add a row to the lines editor, and wait until the editor has `total`
 * rows. Under load, a click can come before the app is ready and add no
 * row, so the click repeats until the row is there.
 */
async function addLine(editor: Locator, rows: Locator, total: number): Promise<void> {
  await expect(async () => {
    if ((await rows.count()) < total) {
      await editor.getByRole("button", { name: "Add a line", exact: true }).click();
    }
    await expect(rows).toHaveCount(total, { timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
}

test("the edit form of a project adds three budget lines and saves them", async ({ page }) => {
  test.skip(detail === undefined, "The definition has no page project_detail.");
  const href = await firstRecordLink(page, "/projects", pathPattern(detail?.path ?? ""));
  expect(href, "a link to a project").toBeDefined();
  await page.goto(href ?? "");
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  const editor = sheet.getByRole("group", { name: "Budget lines" });
  await expect(editor).toBeVisible();
  const rows = editor.locator("tbody tr").filter({ has: page.locator("input") });
  const count = await rows.count();
  const before = amount(await plannedCost(editor).innerText());

  // Each new line is a row. A row without values gives errors, and the
  // remove button removes it.
  for (const [index, [item, value]] of LINES.entries()) {
    await addLine(editor, rows, count + index + 1);
    await editor.getByLabel(`Item, line ${count + index + 1}`, { exact: true }).fill(item);
    await editor.getByLabel(`Amount, line ${count + index + 1}`, { exact: true }).fill(value);
  }
  await addLine(editor, rows, count + LINES.length + 1);
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(editor.getByText("Enter a value.").first()).toBeVisible();
  await editor.getByRole("button", { name: `Remove line ${count + LINES.length + 1}`, exact: true }).click();
  await expect(rows).toHaveCount(count + LINES.length);
  await expect(editor.getByText("Enter a value.")).toHaveCount(0);
  await expect.poll(async () => amount(await plannedCost(editor).innerText())).toBeCloseTo(before + 2000, 2);

  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();

  // The form reads the lines of the project again: the new lines are there.
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await expect(rows).toHaveCount(count + LINES.length);
  const items = await rows.evaluateAll((list) =>
    list.map((row) => (row.querySelector("input") as HTMLInputElement | null)?.value ?? ""),
  );
  expect(items).toEqual(expect.arrayContaining(LINES.map(([item]) => item)));
  await expect.poll(async () => amount(await plannedCost(editor).innerText())).toBeCloseTo(before + 2000, 2);
});
