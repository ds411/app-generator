// The manual order of a table and a board (ADR 0039), in the apps of
// tests/fixtures/invoices.yaml: a row of the steps table moves by drag and
// drop and with the arrow keys on its handle, and a card of the steps board
// moves to another column. scripts/order_ui_test.py starts an app and runs
// this file with APPGEN_ORDER_TEST=1. With APPGEN_ORDER_RELOAD=1, the test
// reloads the page and checks that the order stays: the mock data of the
// React app does not keep a change. The table is busy (`aria-busy`) while
// it saves a move, and the test waits for the save of each move before the
// next one.
import { expect, type Locator, type Page, test } from "@playwright/test";

test.skip(!process.env.APPGEN_ORDER_TEST, "Only for the apps of tests/fixtures/invoices.yaml.");

const reload = process.env.APPGEN_ORDER_RELOAD === "1";

/** Return the titles of the rows of the steps table: the column after the handle. */
function rowTitles(page: Page): Promise<string[]> {
  return page.locator("tbody tr").locator("td:nth-child(2)").allInnerTexts();
}

/** Return the ranks of the rows of the steps table (the last column), or null for no rank. */
async function rowRanks(page: Page): Promise<(number | null)[]> {
  const texts = await page.locator("tbody tr").locator("td:nth-child(4)").allInnerTexts();
  return texts.map((text) => (/\d/.test(text) ? Number(text.replace(/\D/g, "")) : null));
}

/**
 * Return the ranks after a move of the second row to the top, as the apps
 * compute them (ADR 0039): the middle value between 0 and the rank of the
 * row after it, else 1024, 2048, and so on for all rows.
 */
function ranksAfterMove(ranks: readonly (number | null)[]): (number | null)[] {
  const list = [ranks[1] ?? null, ranks[0] ?? null, ...ranks.slice(2)];
  const high = list[1];
  if (high !== null && high !== undefined && high >= 2) return [Math.floor(high / 2), ...list.slice(1)];
  return list.map((_, index) => (index + 1) * 1024);
}

/** Wait until the steps table saved the last move: the table is not busy. */
async function saved(page: Page): Promise<void> {
  await expect(page.locator("table")).not.toHaveAttribute("aria-busy", "true");
}

/** Return the titles of the cards of a column of the steps board. */
function cardTitles(column: Locator): Promise<string[]> {
  return column.locator('[data-slot="card-title"]').allInnerTexts();
}

test("a row of the table moves by drag and drop and with the arrow keys", async ({ page }) => {
  await page.goto("/steps");
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(5);
  const [first, second, third, fourth, fifth] = await rowTitles(page);
  // The third row goes before the first row.
  await rows.nth(2).dragTo(rows.nth(0));
  await expect.poll(() => rowTitles(page)).toEqual([third, first, second, fourth, fifth]);
  await saved(page);
  // The last row goes up one place.
  await rows.nth(4).getByRole("button", { name: "Move the row" }).press("ArrowUp");
  let moved = [third, first, second, fifth, fourth];
  await expect.poll(() => rowTitles(page)).toEqual(moved);
  await saved(page);
  // Each move of the second row to the top halves the rank of the first row,
  // until no integer is free and the rows get 1024, 2048, and so on.
  const renumbered = [1024, 2048, 3072, 4096, 5120];
  let ranks = await rowRanks(page);
  for (let move = 0; move < 15 && JSON.stringify(ranks) !== JSON.stringify(renumbered); move++) {
    await rows.nth(1).getByRole("button", { name: "Move the row" }).press("ArrowUp");
    moved = [moved[1] ?? "", moved[0] ?? "", ...moved.slice(2)];
    ranks = ranksAfterMove(ranks);
    await expect.poll(async () => [await rowTitles(page), await rowRanks(page)]).toEqual([moved, ranks]);
    await saved(page);
    // The handle of the moved row keeps the focus of the keyboard while the
    // table loads the rows again. (A renumber saves the rows one at a time,
    // so the moved row goes down and up again, and loses the focus.)
    if (JSON.stringify(ranks) !== JSON.stringify(renumbered)) {
      await expect(rows.nth(0).getByRole("button", { name: "Move the row" })).toBeFocused();
    }
  }
  expect(ranks).toEqual(renumbered);
  if (reload) {
    await page.reload();
    await expect(rows).toHaveCount(5);
    expect(await rowTitles(page)).toEqual(moved);
    expect(await rowRanks(page)).toEqual(renumbered);
  }
});

test("a card of the board moves before a card of another column", async ({ page }) => {
  await page.goto("/steps/board");
  const todo = page.locator('section[aria-label="Todo"]');
  const doing = page.locator('section[aria-label="Doing"]');
  await expect(doing.locator('[data-slot="card-title"]').first()).toBeVisible();
  const before = await cardTitles(todo);
  const [card] = await cardTitles(doing);
  const cards = page.locator("[draggable]");
  await cards.filter({ hasText: card }).dragTo(todo.locator("[draggable]").first());
  // The card goes before the first card of the column.
  await expect.poll(() => cardTitles(todo)).toEqual([card, ...before]);
  expect(await cardTitles(doing)).not.toContain(card);
  if (reload) {
    await page.reload();
    await expect(todo.locator('[data-slot="card-title"]').first()).toBeVisible();
    expect(await cardTitles(todo)).toEqual([card, ...before]);
  }
});
