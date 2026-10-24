// The language switch shows the UI text in the selected language, and the
// app keeps the language for the next visit. The example definition
// (project-tracker) has an English and a German text for the page title
// and for the label of the switch. The dates and numbers have the format
// of the locale of the language (ADR 0010). Next.js renders the pages on
// the server in the language of the cookie, else of Accept-Language.
import { expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";

/** The cookie of the selected language in Next.js. */
const LANGUAGE_COOKIE = "project-tracker-language";

/** Return the text of a cell of the first row of the table, in the column with a header. */
async function firstCell(page: Page, header: string): Promise<string> {
  await expect(page.getByRole("row").nth(1)).toBeVisible();
  const headers = (await page.getByRole("columnheader").allInnerTexts()).map((text) => text.trim());
  const index = headers.indexOf(header);
  expect(index, `the column ${header}`).toBeGreaterThanOrEqual(0);
  return (await page.getByRole("row").nth(1).getByRole("cell").nth(index).innerText()).trim();
}

/** Open the date picker of the start date in the form of a new project, and return its first weekday and month. */
async function datePicker(page: Page, newProject: string, pickDate: string): Promise<[string, string]> {
  await page.getByRole("button", { name: newProject }).first().click();
  const form = page.getByRole("dialog");
  // The label of the field names the button, and the button shows its placeholder.
  await form.getByRole("button").filter({ hasText: pickDate }).first().click();
  const calendar = page.locator("[data-slot=calendar]");
  await expect(calendar).toBeVisible();
  const weekday = (await calendar.locator(".rdp-weekday").first().innerText()).trim();
  const month = (await calendar.locator("select").first().locator("option:checked").innerText()).trim();
  await page.keyboard.press("Escape");
  await expect(calendar).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(form).toBeHidden();
  return [weekday, month];
}

test("the language switch shows the pages in the selected language", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();

  await page.getByLabel("Language").selectOption("de");
  await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "de");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();

  await page.getByLabel("Sprache").selectOption("en");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();
});

test("the dates and numbers have the format of the selected language", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-01-05T12:00:00Z"));
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();
  // English (en): "Jan 5, 2026" and "$12,500.00". The week starts on Sunday.
  expect(await firstCell(page, "Due")).toMatch(/^[A-Z][a-z]{2} \d{1,2}, \d{4}$/);
  expect(await firstCell(page, "Budget")).toMatch(/^\$\d{1,3}(,\d{3})*\.\d{2}$/);
  expect(await datePicker(page, "New project", "Pick a date")).toEqual(["Sun", "Jan"]);

  await page.getByLabel("Language").selectOption("de");
  await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();
  // German (de): "05.01.2026" and "12.500,00 $". The week starts on Monday.
  expect(await firstCell(page, "Fällig")).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
  expect(await firstCell(page, "Budget")).toMatch(/^\d{1,3}(\.\d{3})*,\d{2}\s\$$/);
  expect(await datePicker(page, "Neues Projekt", "Datum wählen")).toEqual(["Mo", "Jan"]);
});

test.describe("without JavaScript", () => {
  test.skip(expected.binding !== "nextjs", "Only the Next.js app renders the pages on the server.");
  test.use({ javaScriptEnabled: false });

  test("the server renders a page in the language of the cookie", async ({ page, context, baseURL }) => {
    await context.addCookies([{ name: LANGUAGE_COOKIE, value: "de", url: baseURL ?? "" }]);
    await page.goto("/projects");
    await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Seiten suchen" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "de");
    await expect(page).toHaveTitle("Projekte · Projekt-Tracker");
  });

  test.describe("without the cookie", () => {
    test.use({ locale: "de-DE" });

    test("the server renders a page in the language of Accept-Language", async ({ page }) => {
      await page.goto("/projects");
      await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("lang", "de");
    });
  });
});
