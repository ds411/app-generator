// The front ends show the values of the signed-in user (M36): the value
// `$me` of the filters of the widgets and the views, of the totals, and of
// the defaults of the forms. A user shares a record with a secret link
// (ADR 0049). scripts/sessions_ui_test.py starts the app of
// tests/fixtures/courses.yaml, and runs this file. Without the values of
// the users (`expected.sessions`), the tests skip.
import { expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";

const sessions = expected.sessions;

test.skip(!sessions, "The app has no values of the signed-in users.");

/** End the session: the cookies of Next.js, and the session storage of the React app. */
async function signOut(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.evaluate(() => window.sessionStorage.clear());
}

/** Sign in on the sign-in page, and wait for the start page. */
async function signIn(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname === "/");
  await page.waitForLoadState("networkidle");
}

for (const user of sessions?.users ?? []) {
  test(`the pages show the values of the signed-in user ${user.username}`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "light", "The values do not depend on the color mode.");
    await signIn(page, user.username, sessions?.password ?? "");

    // The stat widgets with `$me` count the records of the user.
    for (const stat of user.stats) {
      const card = page.locator('[data-slot="card"]').filter({ has: page.getByText(stat.label, { exact: true }) });
      await expect(card.locator("p").first(), stat.label).toHaveText(stat.value);
    }

    // The list starts with the filter of the user: the records of the user, and no others.
    await page.goto(user.list.path);
    await expect(page.locator("h1").first()).toHaveText(user.list.title);
    for (const title of user.list.own) {
      await expect(page.getByText(title, { exact: true }).first(), title).toBeVisible();
    }
    for (const title of user.list.others) {
      await expect(page.getByText(title, { exact: true }), title).toHaveCount(0);
    }

    // A new record of the form belongs to the user.
    if (user.form) {
      await page.getByRole("button", { name: user.form.label, exact: true }).first().click();
      await expect(page.locator(`#${user.form.id}`)).toContainText(user.form.value);
    }

    // The totals with `$me` count the related records of the user.
    for (const totals of user.totals) {
      await page.goto(totals.path);
      await expect(page.locator("h1").first()).toHaveText(totals.title);
      await expect(page.getByRole("columnheader", { name: totals.column })).toBeVisible();
      const headers = (await page.getByRole("columnheader").allInnerTexts()).map((text) => text.trim());
      const column = headers.indexOf(totals.column);
      expect(column, totals.column).toBeGreaterThanOrEqual(0);
      for (const row of totals.rows) {
        const cells = page.getByRole("row").filter({ hasText: row.title }).first().getByRole("cell");
        await expect(cells.nth(column), row.title).toHaveText(row.value);
      }
    }
  });
}

test("a guest opens the secret link of a record without a sign-in", async ({ page }, testInfo) => {
  const share = sessions?.share;
  test.skip(!share || testInfo.project.name !== "light", "The app has no page with `share`.");
  if (!share) return;
  const password = sessions?.password ?? "";
  const heading = page.getByRole("heading", { name: share.title, exact: true });
  const shareButton = page.getByRole("button", { name: "Share", exact: true });

  // A user without the update operation sees no button "Share".
  await signIn(page, share.member, password);
  await page.goto(share.path);
  await expect(heading).toBeVisible();
  await expect(shareButton).toHaveCount(0);
  await signOut(page);

  // The admin makes the link. Under load, a click can come before the dialog is ready.
  await signIn(page, share.admin, password);
  await page.goto(share.path);
  await expect(heading).toBeVisible();
  const dialog = page.getByRole("dialog");
  const field = dialog.getByRole("textbox", { name: "Link" });
  await expect(async () => {
    if (!(await dialog.isVisible())) {
      await shareButton.click({ timeout: 2_000 });
    }
    if (!(await field.isVisible())) {
      await dialog.getByRole("button", { name: "Make a link", exact: true }).click({ timeout: 2_000 });
    }
    await expect(field).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 30_000 });
  const link = new URL(await field.inputValue());
  expect(link.pathname).toMatch(new RegExp(`^${share.prefix}[A-Za-z0-9_-]{43}$`));
  await page.keyboard.press("Escape");
  await signOut(page);

  // The guest sees the record and its related record, without the actions.
  await page.goto(link.pathname);
  await expect(heading).toBeVisible();
  await expect(page.getByText(share.related, { exact: true }).first()).toBeVisible();
  await expect(shareButton).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe(link.pathname);

  // The admin revokes the link, and the link opens nothing.
  await signIn(page, share.admin, password);
  await page.goto(share.path);
  await expect(heading).toBeVisible();
  const revoke = dialog.getByRole("button", { name: "Revoke the link", exact: true });
  await expect(async () => {
    if (!(await dialog.isVisible())) {
      await shareButton.click({ timeout: 2_000 });
    }
    await revoke.click({ timeout: 2_000 });
    await expect(dialog.getByText("The record has no link.")).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 30_000 });
  await page.keyboard.press("Escape");
  await signOut(page);
  await page.goto(link.pathname);
  await expect(page.getByText(share.invalid, { exact: true })).toBeVisible();
  await expect(heading).toHaveCount(0);
});
