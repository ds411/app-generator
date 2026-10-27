// The front ends show the values of the signed-in user (M36): the value
// `$me` of the filters of the widgets and the views, of the totals, and of
// the defaults of the forms. A user shares a record with a secret link
// (ADR 0049). The page of a record shows the other users on it, in two
// browsers (ADR 0052). The actions of a page follow the role of the user
// in the scope of the record (ADR 0048). scripts/sessions_ui_test.py
// starts the app of tests/fixtures/courses.yaml, and runs this file.
// Without the values of the users (`expected.sessions`), the tests skip.
import { expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";
import { saveAndClose } from "./forms";

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

test("the page of a record shows the other users on it, and their typing", async ({ page, browser }, testInfo) => {
  const presence = sessions?.presence;
  test.skip(!presence || testInfo.project.name !== "light", "The app has no page with `presence`.");
  if (!presence) return;
  test.setTimeout(120_000);
  const password = sessions?.password ?? "";
  const heading = (on: Page) => on.getByRole("heading", { name: presence.title, exact: true });
  const users = (on: Page) => on.getByRole("list", { name: "Other users on this page" });
  const typing = page.getByText(`${presence.admin.name} is typing.`, { exact: true });

  // The member opens the record in the first browser, and sees no other user. The test of
  // the secret links leaves the admin on the page: the server forgets the admin some seconds
  // after the last call.
  await signIn(page, presence.member.username, password);
  await page.goto(presence.path);
  await expect(heading(page)).toBeVisible();
  await expect(users(page)).toHaveCount(0, { timeout: 30_000 });

  // The admin opens it in a second browser: each browser shows the other user.
  const other = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
    colorScheme: testInfo.project.use.colorScheme,
    locale: "en-US",
    timezoneId: "UTC",
  });
  const admin = await other.newPage();
  try {
    await signIn(admin, presence.admin.username, password);
    await admin.goto(presence.path);
    await expect(heading(admin)).toBeVisible();
    await expect(users(page)).toContainText(presence.admin.initials);
    await expect(users(page)).toContainText(presence.admin.name);
    await expect(users(admin)).toContainText(presence.member.name);

    // The admin types in the form of the button "Edit": the member sees a note, which ends
    // some seconds after the last input.
    await admin.getByRole("button", { name: "Edit", exact: true }).first().click();
    const field = admin.getByRole("dialog").getByRole("textbox", { name: /^Title/ }).first();
    await field.pressSequentially(" draft", { delay: 50 });
    await expect(typing).toBeVisible();
    await expect(typing).toBeHidden();
    await admin.keyboard.press("Escape");

    // The admin goes to another page: the member sees no other user.
    await admin.getByRole("link", { name: presence.away.label, exact: true }).first().click();
    await expect.poll(() => new URL(admin.url()).pathname).toBe(presence.away.path);
    await expect(users(page)).toHaveCount(0);

    // The admin comes back, and closes the browser: the server forgets the admin at the
    // latest some seconds after the last call.
    await admin.goto(presence.path);
    await expect(users(page)).toContainText(presence.admin.name);
  } finally {
    await other.close();
  }
  await expect(users(page)).toHaveCount(0, { timeout: 30_000 });
});

test("the actions of a page follow the role of the user in the scope of the record", async ({ page }, testInfo) => {
  const memberships = sessions?.memberships;
  test.skip(!memberships || testInfo.project.name !== "light", "The app has no memberships.");
  if (!memberships) return;
  const password = sessions?.password ?? "";
  const { record, create } = memberships;
  const [allowed, denied] = record.pages;
  if (!allowed || !denied) throw new Error("The test needs two records.");
  const button = page.getByRole("button", { name: record.label, exact: true });

  // The role of the scope of the first record gives the change: the button shows, and the save passes.
  await signIn(page, record.username, password);
  await page.goto(allowed.path);
  await expect(page.getByRole("heading", { name: allowed.title, exact: true })).toBeVisible();
  await expect(button).toBeVisible();
  const sheet = page.getByRole("dialog");
  await expect(async () => {
    if (!(await sheet.isVisible())) {
      await button.click({ timeout: 2_000 });
    }
    await expect(sheet).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 30_000 });
  await saveAndClose(sheet);

  // The role of the scope of the second record does not give the change.
  await page.goto(denied.path);
  await expect(page.getByRole("heading", { name: denied.title, exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(button).toHaveCount(0);
  await signOut(page);

  // A role of a membership gives the create to one user, and no role gives it to the other.
  const createButton = page.getByRole("button", { name: create.label, exact: true });
  await signIn(page, create.shown, password);
  await page.goto(create.path);
  await expect(page.locator("h1").first()).toHaveText(create.title);
  await expect(createButton).toBeVisible();
  await signOut(page);
  await signIn(page, create.hidden, password);
  await page.goto(create.path);
  await expect(page.locator("h1").first()).toHaveText(create.title);
  await page.waitForLoadState("networkidle");
  await expect(createButton).toHaveCount(0);
});
