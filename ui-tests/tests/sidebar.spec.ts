// The sidebar fills the height of a page that is longer than the screen:
// it stays on the screen when the user scrolls, and its background fills
// the full height of the page. The test uses a short screen, so that the
// dashboard is longer than the screen.
import { expect, test } from "@playwright/test";

test("the sidebar fills the height of a long page", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 400 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const column = page.locator('[data-slot="sidebar"]').first();
  const container = column.locator('[data-slot="sidebar-container"]');
  await expect(container).toBeVisible();

  // The dashboard can render its widgets after the network is idle (for
  // example under load), so wait until the page is longer than the screen.
  const scrollHeight = () => page.evaluate(() => document.documentElement.scrollHeight);
  await expect.poll(scrollHeight, { message: "the page is longer than the screen" }).toBeGreaterThan(400);

  // The column with the background is as high as the page. A widget that
  // loads its data later makes the page longer, so compare the two heights
  // until the layout is stable.
  const shortfall = async () => {
    const columnBox = await column.boundingBox();
    return (await scrollHeight()) - (columnBox?.height ?? 0);
  };
  await expect.poll(shortfall, { message: "the sidebar is as high as the page" }).toBeLessThanOrEqual(1);
  const inner = column.locator('[data-slot="sidebar-inner"]');
  const background = await inner.evaluate((element) => getComputedStyle(element).backgroundColor);
  await expect(column).toHaveCSS("background-color", background);

  // After a scroll to the end, the sidebar is still on the screen, at its full height.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const box = await container.boundingBox();
  expect(box?.y ?? -1).toBe(0);
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(400);
});
