// The views of the rows of a query (ADR 0045): a table whose filters give
// the params of the query, a card list whose path parameter gives a param,
// and a calendar of the bookings of a listing. scripts/listings_ui_test.py
// starts the app of tests/fixtures/listings.yaml with its seed records and
// the hand-written queries: the Next.js app runs them in its server
// actions, the React app with mock data in the browser, and the React app
// with the FastAPI app at the endpoints of the queries. The last test picks
// the days of an available filter (ADR 0047): the table keeps the listings
// without a booking in the days. The tests change no record.
import { expect, type Locator, type Page, test } from "@playwright/test";

import { expected } from "./expected";

const views = expected.queryViews;

/** Return the texts of the first column of the rows of a table. */
async function titles(table: Locator): Promise<string[]> {
  const cells = await table.locator("tbody tr td:first-child").allInnerTexts();
  return cells.map((text) => text.trim());
}

/** Wait until the table shows these titles in its first column. */
async function expectTitles(page: Page, expectedTitles: string[]): Promise<void> {
  const table = page.locator("table");
  await expect(table.locator("tbody tr")).toHaveCount(expectedTitles.length);
  await expect.poll(() => titles(table)).toEqual(expectedTitles);
}

test("a table shows the rows of a query, one page at a time, for the values of its filters", async ({ page }, testInfo) => {
  test.skip(!views || testInfo.project.name !== "light", "Only the test of the views of the queries, in the light mode.");
  if (!views) return;
  const { table } = views;
  await page.goto(table.path);

  await expectTitles(page, table.pages[0] ?? []);
  await expect(page.getByText(`1–${table.pages[0]?.length} of ${table.total}`)).toBeVisible();
  // The rows show after the first load, so the page reacts to the click.
  await page.getByRole("button", { name: "Next page" }).click();
  await expectTitles(page, table.pages[1] ?? []);

  // A change of a filter shows the first page of the new rows.
  await page.getByLabel(table.filter.label, { exact: true }).fill(table.filter.value);
  await expectTitles(page, table.filter.titles);
  await page.getByLabel(table.filter.label, { exact: true }).fill(table.none.value);
  await expect(page.getByText(table.none.title, { exact: true })).toBeVisible();
  await page.getByLabel(table.filter.label, { exact: true }).fill("");

  // Without the value of a required param, the view does not run the query.
  const required = page.getByLabel(table.required.label, { exact: true });
  await required.fill("");
  await expect(page.getByText(table.missing, { exact: true })).toBeVisible();
  await expect(page.locator("table")).toHaveCount(0);
  await required.fill(table.required.value);
  await expectTitles(page, table.required.titles);
});

test("a card list shows the rows of a query for a path parameter of the page", async ({ page }, testInfo) => {
  test.skip(!views || testInfo.project.name !== "light", "Only the test of the views of the queries, in the light mode.");
  if (!views) return;
  const { cards } = views;
  await page.goto(cards.path);
  const shown = page.locator("[data-slot=card]");
  await expect(shown).toHaveCount(cards.cards.length);
  for (const [index, fields] of cards.cards.entries()) {
    for (const [label, value] of Object.entries(fields)) {
      const term = shown.nth(index).locator("dt", { hasText: new RegExp(`^${label}$`) });
      await expect(term.locator("xpath=following-sibling::dd[1]")).toHaveText(value);
    }
  }

  await page.goto(cards.emptyPath);
  await expect(page.getByText(cards.empty, { exact: true })).toBeVisible();
});

test("a calendar shows the records of a query of the record of the page", async ({ page }, testInfo) => {
  test.skip(!views || testInfo.project.name !== "light", "Only the test of the views of the queries, in the light mode.");
  if (!views) return;
  const { table, calendar } = views;
  await page.clock.setFixedTime(new Date(calendar.today));
  await page.goto(table.path);
  const link = page.locator("table").getByRole("link", { name: calendar.record, exact: true });
  const href = await link.getAttribute("href");
  expect(href, `the link of ${calendar.record}`).toBeTruthy();

  await page.goto(`${href}${calendar.suffix}`);
  for (const event of calendar.events) {
    await expect(page.getByText(event, { exact: true }).first()).toBeVisible();
  }
  for (const other of calendar.others) {
    await expect(page.getByText(other, { exact: true })).toHaveCount(0);
  }
});

test("an available filter keeps the listings without a booking in the picked days", async ({ page }, testInfo) => {
  const available = expected.available;
  test.skip(!available || testInfo.project.name !== "light", "Only the test of the available filter, in the light mode.");
  if (!available) return;
  // The calendar of the filter shows the month of the bookings first.
  await page.clock.setFixedTime(new Date(available.today));
  await page.goto(available.path);
  await expectTitles(page, available.all);

  for (const { from, to, titles: free } of available.ranges) {
    await page.getByRole("button", { name: available.label, exact: true }).click();
    await page.getByRole("button", { name: new RegExp(from) }).click();
    await page.getByRole("button", { name: new RegExp(to) }).click();
    await page.keyboard.press("Escape");
    await expectTitles(page, free);
    await page.getByRole("button", { name: `Clear ${available.label}`, exact: true }).click();
    await expectTitles(page, available.all);
  }
});
