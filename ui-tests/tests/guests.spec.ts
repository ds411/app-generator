// A guest (ADR 0050) fills a cart without a sign-in, and finds the cart
// after the sign-up or the sign-in. Each guest has its own cart.
// scripts/guests_ui_test.py starts the app of tests/fixtures/shop.yaml,
// and runs this file. Without the values of the guests
// (`expected.guests`), the tests skip. The steps follow the links of the
// app, so that the React app with mock data keeps its records in memory.
import { type Browser, expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";
import { saveAndClose } from "./forms";

const guests = expected.guests;

test.skip(!guests, "The app has no guests.");

type Item = { related: string; number: string };

/** Open the list page of the records of a guest with its menu item, and wait for the rows. */
async function openList(page: Page): Promise<void> {
  await page.getByRole("link", { name: guests?.menu, exact: true }).first().click();
  await page.waitForURL((url) => url.pathname === guests?.path);
  await expect(page.locator("h1").first()).toHaveText(guests?.title ?? "");
  await page.waitForLoadState("networkidle");
}

/** Add a record with the form action of the list page. */
async function addItem(page: Page, item: Item): Promise<void> {
  await page.getByRole("button", { name: guests?.add, exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  await sheet.getByRole("combobox", { name: guests?.relation, exact: true }).click();
  await page.getByRole("option", { name: item.related, exact: true }).click();
  await sheet.locator(`#${guests?.numberId}`).fill(item.number);
  await saveAndClose(sheet, guests?.submit);
}

/** Expect a row of the record in the table. */
async function expectItem(page: Page, item: Item): Promise<void> {
  const row = page.getByRole("row").filter({ hasText: item.related });
  await expect(row, item.related).toBeVisible();
  await expect(row, item.related).toContainText(item.number);
}

/** Expect no row of a related record in the table. */
async function expectNoRow(page: Page, related: string): Promise<void> {
  await expect(page.getByRole("row").filter({ hasText: related }), related).toHaveCount(0);
}

/** Open the start page as a new guest: a new browser context, without cookies and storage. */
async function newGuest(browser: Browser, baseURL: string | undefined): Promise<Page> {
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  return page;
}

test("a guest fills a cart, signs up, and finds the cart", async ({ browser, page }, testInfo) => {
  test.skip(!guests || testInfo.project.name !== "light", "One check in the light mode.");
  if (!guests) return;
  const [item] = guests.items;
  if (!item) return;
  await page.goto("/");
  await openList(page);
  // The records of the users are not records of the guest.
  for (const related of guests.others) {
    await expectNoRow(page, related);
  }
  await addItem(page, item);
  await expectItem(page, item);

  // Another guest has its own records.
  const other = await newGuest(browser, testInfo.project.use.baseURL);
  await openList(other);
  await expectNoRow(other, item.related);
  await other.context().close();

  // The sign-up: the records of the guest move to the new user.
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.waitForURL((url) => url.pathname === "/sign-in");
  await page.getByRole("link", { name: "Sign up" }).click();
  await page.waitForURL((url) => url.pathname === "/sign-up");
  const n = String(Date.now());
  for (const field of guests.signUp.fields) {
    await page.locator(`#${field.id}`).fill(field.value.replaceAll("{n}", n));
  }
  await page.locator("#sign-up-password").fill(guests.signUp.password);
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL((url) => url.pathname === "/");
  await openList(page);
  await expectItem(page, item);
  for (const related of guests.others) {
    await expectNoRow(page, related);
  }
});

test("a guest fills a cart, signs in, and finds the cart next to the own records", async ({ page }, testInfo) => {
  test.skip(!guests || testInfo.project.name !== "light", "One check in the light mode.");
  if (!guests) return;
  const item = guests.items[1];
  if (!item) return;
  await page.goto("/");
  await openList(page);
  await addItem(page, item);
  await expectItem(page, item);

  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await page.waitForURL((url) => url.pathname === "/sign-in");
  await page.locator('input[name="username"]').fill(guests.user.username);
  await page.locator('input[name="password"]').fill(guests.user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname === "/");
  await openList(page);
  await expectItem(page, item);
  for (const related of guests.user.own) {
    await expect(page.getByRole("row").filter({ hasText: related }), related).toBeVisible();
  }
});
