// The front ends show only the pages and the operations that the role of
// the user allows (ADR 0012), and a new user can sign up (ADR 0016).
// scripts/auth_ui_test.py starts the room booking example, and runs this
// file. Without the values of the sign-in (`expected.auth`), the tests
// skip.
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
  await expect(page.getByRole("alert")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/sign-up");
  await fill(String(Date.now()));
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL((url) => url.pathname === "/");
  await page.waitForLoadState("networkidle");
  expect(await menuLabels(page)).toEqual(signUp.menu);
});
