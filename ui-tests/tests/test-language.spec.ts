// In a test language, the pages show no text of the default language
// (ADR 0010). scripts/translation_test.py generates the project tracker
// with a test language that changes each text to ⟦text⟧, and runs this
// file. A text without ⟦ that is not a value of the records does not go
// through `t`. Without the test language, the tests skip.
import { expect, type Locator, type Page, test } from "@playwright/test";

import { type ExpectedPage, expected, pathPattern, UNKNOWN_ID } from "./expected";
import { firstRecordLink } from "./links";

const language = expected.testLanguage;
/** The start of each text of the test language. */
const MARK = "⟦";
/** The attributes that hold a text that the user reads. */
const ATTRIBUTES = ["aria-label", "aria-description", "aria-roledescription", "aria-valuetext", "alt", "title", "placeholder"];
/** The today of the browser: the center of the mock and seed dates (BASE_DATE). */
const TODAY = new Date("2026-01-05T12:00:00Z");

test.skip(!language, "The app has no test language.");
// The test language has the Japanese locale: its dates and numbers have
// no Latin letters, so the Latin text that is left is UI text, a value of
// the records, or a format that does not use the locale of the language.
// The browser has the locale en-US.

/** Return the texts and the text attributes of an element and its children. */
async function textsOf(root: Locator): Promise<string[]> {
  return root.evaluate((element, attributes) => {
    const found: string[] = [];
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      // The initials of an avatar come from a value of the records.
      if (node.parentElement?.closest("script, style, noscript, template, [data-slot=avatar-fallback]")) continue;
      found.push(node.textContent ?? "");
    }
    for (const item of [element, ...element.querySelectorAll("*")]) {
      for (const name of attributes) {
        const value = item.getAttribute(name);
        if (value) found.push(value);
      }
    }
    return found;
  }, ATTRIBUTES);
}

/** Return the texts in the default language: Latin text without ⟦ that is not a value of the records. */
async function untranslated(root: Locator): Promise<string[]> {
  const ignore = new Set(language?.ignore ?? []);
  const texts = new Set((await textsOf(root)).map((text) => text.trim()));
  return [...texts]
    .filter((text) => /[A-Za-z]/.test(text) && !text.includes(MARK))
    .filter((text) => !ignore.has(text) && !text.split(", ").every((part) => ignore.has(part)))
    .sort();
}

/** Return a path of a page: with a record of its parent page for path parameters. */
async function samplePath(page: Page, target: ExpectedPage): Promise<string> {
  if (!target.params.length) return target.path;
  const parent = target.path.slice(0, target.path.indexOf("/{")) || "/";
  const href = await firstRecordLink(page, parent, pathPattern(target.path));
  return href ?? target.path.replace(/\{[^}]+\}/g, UNKNOWN_ID);
}

/** Open the first date picker in an element, and return the texts of its calendar. */
async function checkDatePicker(page: Page, root: Locator): Promise<string[]> {
  // The label of the field names the button, and the button shows its placeholder.
  const picker = root.getByRole("button").filter({ hasText: `${MARK}Pick a date⟧` });
  if ((await picker.count()) === 0) return [];
  await picker.first().click();
  const calendar = page.locator("[data-slot=calendar]");
  await expect(calendar).toBeVisible();
  const found = await untranslated(calendar);
  await page.keyboard.press("Escape");
  await expect(calendar).toBeHidden();
  return found;
}

/**
 * Open a dialog or a menu with a button, check its text, and close it.
 * If the button opens another page, check the text of that page. In a
 * form, also check its first date picker.
 */
async function checkPopup(page: Page, button: Locator, role: "dialog" | "menu"): Promise<string[]> {
  if ((await button.count()) === 0) return [];
  const url = page.url();
  await button.first().click();
  const popup = page.getByRole(role).first();
  await expect.poll(async () => (await popup.isVisible()) || page.url() !== url).toBe(true);
  if (!(await popup.isVisible())) {
    await page.waitForLoadState("networkidle");
    return [...(await untranslated(page.locator("body"))), ...(await checkDatePicker(page, page.locator("main")))];
  }
  const found = [...(await untranslated(popup)), ...(await checkDatePicker(page, popup))];
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();
  return found;
}

for (const target of expected.pages) {
  test(`the page ${target.name} shows no text of the default language`, async ({ page, context, baseURL }) => {
    if (!language) return;
    // The React app keeps the language in the browser storage, and the Next.js app in a cookie.
    await page.addInitScript(
      ([key, code]) => window.localStorage.setItem(key, code),
      [language.storageKey, language.code] as const,
    );
    await context.addCookies([{ name: language.storageKey, value: language.code, url: baseURL ?? "" }]);
    await page.clock.setFixedTime(TODAY);
    await page.goto(await samplePath(page, target));
    await expect(page.locator("html")).toHaveAttribute("lang", language.locale);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("h1").first()).toBeVisible();
    expect(await untranslated(page.locator("body"))).toEqual([]);

    // The search, the menu of the first record, and the first form of the page.
    const search = page.getByRole("button", { name: new RegExp(`^${MARK}Search pages`) });
    expect(await checkPopup(page, search, "dialog")).toEqual([]);
    const main = page.locator("main");
    const actions = main.getByRole("button", { name: `${MARK}Actions⟧`, exact: true });
    expect(await checkPopup(page, actions, "menu")).toEqual([]);
    const newButton = main.getByRole("button", { name: new RegExp(`^${MARK}New `) });
    expect(await checkPopup(page, newButton, "dialog")).toEqual([]);
  });
}
