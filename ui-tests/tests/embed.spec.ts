// A page with `embed` shows without the app shell in a frame of a website
// of the app definition, and in no frame of another website. The other
// pages show in no frame of another website (ADR 0032).
import { expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";

/** A website that no page of the app definition names. */
const OTHER = "https://other.example";
/** The URL of the error page of Chromium: the frame that the browser does not show. */
const BLOCKED = "chrome-error://chromewebdata/";

// The websites of the tests are on the internet, and the app is on this
// machine: Chromium asks for the access to the local network.
test.use({ permissions: ["local-network-access"] });

/** Open a website (a route of the test) with a frame of a URL of the app. */
async function openWebsite(page: Page, origin: string, url: string): Promise<void> {
  const html = `<!doctype html><title>Website</title><iframe src="${url}" width="1000" height="700"></iframe>`;
  await page.route(`${origin}/`, (route) => route.fulfill({ contentType: "text/html", body: html }));
  await page.goto(`${origin}/`);
}

/** Wait until the browser shows its error page in the frame. */
async function expectBlocked(page: Page): Promise<void> {
  await expect.poll(() => page.frames().map((frame) => frame.url())).toContain(BLOCKED);
}

for (const target of expected.pages.filter((p) => p.embed.length && !p.params.length)) {
  test(`the page ${target.name} shows in a frame of ${target.embed[0]}`, async ({ page, baseURL }) => {
    await openWebsite(page, target.embed[0], new URL(target.path, baseURL).href);

    const frame = page.frameLocator("iframe");
    await expect(frame.locator("h1").first()).toHaveText(target.title);
    // The page shows without the app shell: no top bar and no sidebar.
    await expect(frame.locator("header")).toHaveCount(0);
    await expect(frame.locator("[data-slot=sidebar]")).toHaveCount(0);
  });

  test(`the page ${target.name} shows in no frame of another website`, async ({ page, baseURL }) => {
    await openWebsite(page, OTHER, new URL(target.path, baseURL).href);

    await expectBlocked(page);
  });
}

test("a page without embed shows in no frame of another website", async ({ page, baseURL }) => {
  const target = expected.pages.find((p) => !p.embed.length && !p.params.length);
  test.skip(target === undefined, "The app has no page without embed and path parameters.");
  // The origin of a page with `embed` does not open the other pages either.
  const origin = expected.pages.find((p) => p.embed.length)?.embed[0] ?? OTHER;
  await openWebsite(page, origin, new URL(target!.path, baseURL).href);

  await expectBlocked(page);
});
