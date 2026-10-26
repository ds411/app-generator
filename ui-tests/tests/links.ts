// Links to records on a list page. The React app renders its list after
// the network is idle, and under load (for example with the three checks
// in parallel) this can take some time, so the helpers wait for a link.
import type { Page } from "@playwright/test";

/** Milliseconds to wait for a link to a record. */
const LINK_TIMEOUT = 10_000;

/** Return the hrefs of the links on the page that match the pattern. */
async function matchingLinks(page: Page, pattern: RegExp): Promise<string[]> {
  const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
  return hrefs.filter((href) => pattern.test(href));
}

/**
 * Open the parent page and return the first link that matches the
 * pattern, or undefined when no link shows in LINK_TIMEOUT.
 */
export async function firstRecordLink(page: Page, parent: string, pattern: RegExp): Promise<string | undefined> {
  return recordLink(page, parent, pattern, 0);
}

/**
 * Open the parent page and return the link to the record at an index
 * (0 is the first record) that matches the pattern, or undefined when the
 * page does not show the link in LINK_TIMEOUT.
 */
export async function recordLink(page: Page, parent: string, pattern: RegExp, index: number): Promise<string | undefined> {
  await page.goto(parent);
  await page.waitForLoadState("networkidle");
  const deadline = Date.now() + LINK_TIMEOUT;
  for (;;) {
    // A record can have more than one link, for example its title and an action.
    const href = [...new Set(await matchingLinks(page, pattern))][index];
    if (href) return href;
    if (Date.now() > deadline) return undefined;
    await page.waitForTimeout(200);
  }
}
