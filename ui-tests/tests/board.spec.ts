// The board view shows all its columns, or a horizontal scroll bar that
// shows that the board scrolls. The page itself does not scroll to the
// side. The test uses the task board of the project tracker.
import { expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";

const board = expected.pages.find((p) => p.name === "task_board");

async function checkBoard(page: Page): Promise<void> {
  await page.goto(board?.path ?? "/");
  await page.waitForLoadState("networkidle");
  const area = page.locator('[data-slot="scroll-area"]').filter({ has: page.locator("section[aria-label]") });
  await expect(area).toHaveCount(1);
  const columns = area.locator("section[aria-label]");
  await expect(columns.first()).toBeVisible();
  const areaBox = await area.boundingBox();
  const lastBox = await columns.last().boundingBox();
  expect(areaBox).not.toBeNull();
  expect(lastBox).not.toBeNull();
  const fits = (lastBox?.x ?? 0) + (lastBox?.width ?? 0) <= (areaBox?.x ?? 0) + (areaBox?.width ?? 0) + 1;
  const scrollBar = area.locator('[data-slot="scroll-area-scrollbar"][data-orientation="horizontal"]');
  if (!fits) {
    await expect(scrollBar).toBeVisible();
    expect((await scrollBar.boundingBox())?.height ?? 0).toBeGreaterThan(0);
  }
  // The board scrolls inside its area: the page is not wider than the screen.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("the board shows all columns or a visible scroll bar on a 1280 px screen", async ({ page }) => {
  test.skip(board === undefined, "The definition has no page task_board.");
  await page.setViewportSize({ width: 1280, height: 800 });
  await checkBoard(page);
});

test("the board fits or scrolls with a visible scroll bar on a narrow screen", async ({ page }) => {
  test.skip(board === undefined, "The definition has no page task_board.");
  await page.setViewportSize({ width: 390, height: 800 });
  await checkBoard(page);
});
