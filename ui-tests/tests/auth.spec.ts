// The front ends show only the pages and the operations that the role of
// the user allows (ADR 0012), a new user can sign up (ADR 0016), a user
// can reset the password (ADR 0017), a user of an owner rule sees only
// the records of the user (ADR 0018), and a user signs in with a provider
// (ADR 0020).
// scripts/auth_ui_test.py starts the room booking example, and runs this
// file. Without the values of the sign-in (`expected.auth`), the tests
// skip.
import { readFileSync } from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { type ExpectedAction, expected, modeOf } from "./expected";

const auth = expected.auth;

test.skip(!auth, "The app has no values of the sign-in.");

/** Sign in on the sign-in page, and wait for the start page. */
async function signIn(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname === "/");
  await page.waitForLoadState("networkidle");
}

/** Return the labels of the items of the sidebar menu, in order. */
async function menuLabels(page: Page): Promise<string[]> {
  const buttons = page.locator(
    '[data-slot="sidebar-content"] :is([data-slot="sidebar-menu-button"], [data-slot="sidebar-menu-sub-button"])',
  );
  await expect(buttons.first()).toBeVisible();
  return (await buttons.allInnerTexts()).map((text) => text.trim());
}

/** Compare the sidebar with its approved screenshot in ui-tests/approved/<binding>/<app>/<mode>/. */
async function expectSidebar(page: Page, mode: string, name: string): Promise<void> {
  const sidebar = page.locator('[data-slot="sidebar-container"]').first();
  await expect(sidebar).toBeVisible();
  await expect(sidebar).toHaveScreenshot([expected.binding, auth?.app ?? "", mode, `${name}.png`]);
}

/** Open the page of each action, and check that the action shows only if the role allows it. */
async function expectActions(page: Page, actions: ExpectedAction[]): Promise<void> {
  for (const action of actions) {
    await page.goto(action.path);
    await expect(page.locator("h1").first()).toHaveText(action.title);
    await page.waitForLoadState("networkidle");
    const button = page.getByRole("button", { name: action.label, exact: true });
    if (action.shown) {
      await expect(button.first(), `${action.path}: ${action.label}`).toBeVisible();
    } else {
      await expect(button, `${action.path}: ${action.label}`).toHaveCount(0);
    }
  }
}

for (const role of auth?.roles ?? []) {
  test(`the menu of the role ${role.role} shows only its pages`, async ({ page }, testInfo) => {
    await signIn(page, role.username, auth?.password ?? "");
    expect(await menuLabels(page)).toEqual(role.menu);
    await expectSidebar(page, modeOf(testInfo.project.name), `menu-${role.role}`);
  });

  test(`the role ${role.role} sees only the pages and the actions that it may use`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "light", "The checks do not depend on the color mode.");
    await signIn(page, role.username, auth?.password ?? "");
    // A direct URL of a page that the role may not open shows "not found".
    for (const path of role.deniedPaths) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: "This page does not exist" }), path).toBeVisible();
    }
    await expectActions(page, role.actions);
  });
}

test("without a session, the menu shows only the public pages", async ({ page }, testInfo) => {
  const anonymous = auth?.anonymous;
  test.skip(!anonymous, "The app has no public page.");
  if (!anonymous) return;
  await page.goto(anonymous.path);
  await expect(page.locator("h1").first()).toHaveText(anonymous.title);
  await page.waitForLoadState("networkidle");
  expect(await menuLabels(page)).toEqual(anonymous.menu);
  await expectSidebar(page, modeOf(testInfo.project.name), "menu-anonymous");
  if (testInfo.project.name === "light") await expectActions(page, anonymous.actions);
});

test("the sign-up page shows the fields of a new user", async ({ page }, testInfo) => {
  test.skip(!auth?.signUp, "The app has no sign-up.");
  await page.goto("/sign-up");
  await expect(page.getByRole("heading", { name: "Sign up" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveScreenshot([expected.binding, auth?.app ?? "", modeOf(testInfo.project.name), "sign-up.png"]);
});

test("a new user signs up, and sees the menu of the default role", async ({ page }, testInfo) => {
  const signUp = auth?.signUp;
  test.skip(!signUp || testInfo.project.name !== "light", "One sign-up in the light mode.");
  if (!signUp) return;
  const fill = async (n: string) => {
    for (const field of signUp.fields) {
      await page.locator(`#${field.id}`).fill(field.value.replaceAll("{n}", n));
    }
    await page.locator("#sign-up-password").fill(signUp.password);
  };
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "Sign up" }).click();
  await page.waitForURL((url) => url.pathname === "/sign-up");
  // A user name that exists shows an error, and the page stays open.
  const existing = auth?.roles[0]?.username ?? "";
  await fill(String(Date.now()));
  await page.locator(`#${signUp.usernameId}`).fill(existing);
  await page.getByRole("button", { name: "Sign up" }).click();
  // The route announcer of Next.js is an alert too, outside the main element.
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/sign-up");
  await fill(String(Date.now()));
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL((url) => url.pathname === "/");
  await page.waitForLoadState("networkidle");
  expect(await menuLabels(page)).toEqual(signUp.menu);
});

/** Return the last reset link of a user in the log of the app. */
function resetLink(serverLog: string, username: string): string | undefined {
  const prefix = `The password reset link of ${username}: `;
  const lines = readFileSync(serverLog, "utf8").split("\n").filter((line) => line.includes(prefix));
  return lines.at(-1)?.split(prefix)[1]?.trim();
}

test("the password reset pages ask for a link, and set a new password", async ({ page }, testInfo) => {
  const reset = auth?.passwordReset;
  test.skip(!reset, "The app has no password reset pages.");
  if (!reset) return;
  const mode = modeOf(testInfo.project.name);
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "Did you forget the password?" }).click();
  await page.waitForURL((url) => url.pathname === "/forgot-password");
  await expect(page.getByRole("heading", { name: "Reset the password" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveScreenshot([expected.binding, auth?.app ?? "", mode, "forgot-password.png"]);
  await page.goto("/reset-password?token=example");
  await expect(page.getByRole("heading", { name: "Set a new password" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveScreenshot([expected.binding, auth?.app ?? "", mode, "reset-password.png"]);
  if (testInfo.project.name !== "light") return;

  // Ask for a link, and find it in the log of the app.
  const before = resetLink(reset.serverLog, reset.username);
  await page.goto("/forgot-password");
  await page.locator('input[name="username"]').fill(reset.username);
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByRole("main").getByRole("status")).toBeVisible();
  let link: string | undefined;
  await expect
    .poll(() => {
      link = resetLink(reset.serverLog, reset.username);
      return link !== undefined && link !== before;
    })
    .toBe(true);
  // Set a new password with the link. The link is valid only one time.
  const password = `new-password-${Date.now()}`;
  for (const [value, result] of [
    [password, "status"],
    [`${password}-2`, "alert"],
  ] as const) {
    await page.goto(link ?? "");
    await page.locator('input[name="password"]').fill(value);
    await page.getByRole("button", { name: "Set the password" }).click();
    await expect(page.getByRole("main").getByRole(result)).toBeVisible();
  }
  await signIn(page, reset.username, password);
});

for (const rule of auth?.ownerRules ?? []) {
  test(`the role ${rule.role} sees only the ${rule.entity} records of its user`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "light", "The checks do not depend on the color mode.");
    await signIn(page, rule.username, auth?.password ?? "");
    await page.goto(rule.listPath);
    await expect(page.locator("h1").first()).toHaveText(rule.listTitle);
    for (const title of rule.own) {
      await expect(page.getByText(title, { exact: true }).first(), title).toBeVisible();
    }
    for (const title of rule.others) {
      await expect(page.getByText(title, { exact: true }), title).toHaveCount(0);
    }
    // The form of a new record does not show the owner: the record belongs to the user.
    if (rule.form) {
      await page.getByRole("button", { name: rule.form.label, exact: true }).first().click();
      await expect(page.locator(`#${rule.form.firstId}`)).toBeVisible();
      await expect(page.locator(`#${rule.form.ownerId}`)).toHaveCount(0);
    }
    // A record of the user opens. A record of another user does not exist.
    await page.goto(rule.ownPath);
    await expect(page.getByText(rule.ownTitle, { exact: true }).first()).toBeVisible();
    await page.goto(rule.otherPath);
    await expect(page.getByText(rule.otherMessage, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(rule.otherTitle, { exact: true })).toHaveCount(0);
  });
}

for (const provider of auth?.providers ?? []) {
  test(`a user signs in with the provider ${provider.name}, and sees the menu of its role`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "light", "The sign-in does not depend on the color mode.");
    await page.goto("/sign-in");
    const app = new URL(page.url()).origin;
    await page.getByRole("button", { name: provider.title, exact: true }).click();
    // The browser goes to the provider, and comes back to the start page of the app.
    await page.waitForURL((url) => url.origin === app && url.pathname === "/");
    await page.waitForLoadState("networkidle");
    expect(await menuLabels(page)).toEqual(provider.menu);
  });
}
