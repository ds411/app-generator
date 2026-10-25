// The front ends show only the pages and the operations that the role of
// the user allows (ADR 0012), a new user can sign up (ADR 0016) and
// confirm the email address (ADR 0023), a user can reset the password
// (ADR 0017), a user of an owner rule sees only the records of the user
// (ADR 0018), a user signs in with a provider (ADR 0020), and a user turns
// on a second factor and signs in with a code (ADR 0024).
// scripts/auth_ui_test.py starts the room booking example, and runs this
// file. Without the values of the sign-in (`expected.auth`), the tests
// skip.
import { createHmac } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";

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

/** The pages of the links of the messages, by the kind of the message. */
const LINK_PAGES: Record<string, string> = {
  "password-reset": "/reset-password?",
  "email-verification": "/verify-email?",
};

/**
 * Return the links of a kind that the app sent to an address, from the
 * emails that the mock SMTP server wrote to its file (one JSON line each).
 */
function messageLinks(mailbox: string, kind: string, to: string): string[] {
  if (!existsSync(mailbox)) return [];
  const messages = readFileSync(mailbox, "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as { to: string[]; text: string });
  return messages
    .filter((message) => message.to.includes(to))
    .flatMap((message) => message.text.match(/https?:\/\/\S+/g) ?? [])
    .filter((link) => link.includes(LINK_PAGES[kind] ?? "?"));
}

/**
 * Wait for a new link of a kind in the emails of the app, and return it.
 * Two links of the same second can be equal, so the test counts the links.
 */
async function newMessageLink(mailbox: string, kind: string, to: string, before: number): Promise<string> {
  await expect.poll(() => messageLinks(mailbox, kind, to).length).toBeGreaterThan(before);
  return messageLinks(mailbox, kind, to).at(-1) ?? "";
}

test("the page of the verification link asks for a confirmation", async ({ page }, testInfo) => {
  test.skip(!auth?.signUp?.verifyEmail, "The app has no page of the verification link.");
  await page.goto("/verify-email?token=example");
  await expect(page.getByRole("heading", { name: "Confirm the email address" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveScreenshot([expected.binding, auth?.app ?? "", modeOf(testInfo.project.name), "verify-email.png"]);
});

test("a new user signs up, and sees the menu of the default role", async ({ page }, testInfo) => {
  const signUp = auth?.signUp;
  test.skip(!signUp || testInfo.project.name !== "light", "One sign-up in the light mode.");
  if (!signUp) return;
  const valueOf = (id: string, n: string) => signUp.fields.find((field) => field.id === id)?.value.replaceAll("{n}", n) ?? "";
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
  const n = String(Date.now());
  await fill(n);
  await page.getByRole("button", { name: "Sign up" }).click();
  const verify = signUp.verifyEmail;
  if (verify) {
    // The app sends a link, and the user signs in only after the confirmation.
    const username = valueOf(signUp.usernameId, n);
    const address = valueOf(verify.addressId, n);
    await expect(page.getByRole("main").getByRole("status")).toBeVisible();
    await newMessageLink(verify.mailbox, "email-verification", address, 0);
    await page.goto("/sign-in");
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(signUp.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
    // A new link.
    await page.getByRole("button", { name: "Send the link again" }).click();
    await expect(page.getByRole("main").getByRole("status")).toBeVisible();
    const link = await newMessageLink(verify.mailbox, "email-verification", address, 1);
    await page.goto(link);
    await page.getByRole("button", { name: "Confirm the email address" }).click();
    await expect(page.getByRole("main").getByRole("status")).toBeVisible();
    await signIn(page, username, signUp.password);
  } else {
    await page.waitForURL((url) => url.pathname === "/");
    await page.waitForLoadState("networkidle");
  }
  expect(await menuLabels(page)).toEqual(signUp.menu);
});

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

  // Ask for a link, and find it in the emails of the app.
  const before = messageLinks(reset.mailbox, "password-reset", reset.username).length;
  await page.goto("/forgot-password");
  await page.locator('input[name="username"]').fill(reset.username);
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByRole("main").getByRole("status")).toBeVisible();
  const link = await newMessageLink(reset.mailbox, "password-reset", reset.username, before);
  // Set a new password with the link. The link is valid only one time.
  const password = `new-password-${Date.now()}`;
  for (const [value, result] of [
    [password, "status"],
    [`${password}-2`, "alert"],
  ] as const) {
    await page.goto(link);
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

/** Return the code of a base32 key in a time step (RFC 6238), as an authenticator app makes it. */
function totpCode(key: string, step: number): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = Array.from(key, (char) => alphabet.indexOf(char).toString(2).padStart(5, "0")).join("");
  const secret = Buffer.from((bits.match(/.{8}/g) ?? []).map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", secret).update(counter).digest();
  const offset = (digest.at(-1) ?? 0) & 0x0f;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

/** Return the current time step of the codes: 30 seconds. */
function currentStep(): number {
  return Math.floor(Date.now() / 30_000);
}

test("a user turns on the second factor, and signs in with a code", async ({ page }, testInfo) => {
  const factor = auth?.secondFactor;
  test.skip(!factor || testInfo.project.name !== "light", "One check in the light mode.");
  if (!factor) return;
  const password = auth?.password ?? "";
  await signIn(page, factor.username, password);
  await page.getByRole("link", { name: "Second factor" }).click();
  await page.waitForURL((url) => url.pathname === "/second-factor");
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByRole("img", { name: "QR code of the key" })).toBeVisible();
  const key = (await page.locator("#second-factor-key").innerText()).trim();
  const code = page.locator('input[name="code"]');
  // A wrong code does not turn on the factor.
  const valid = [-1, 0, 1, 2].map((offset) => totpCode(key, currentStep() + offset));
  await code.fill(["000000", "111111", "222222", "333333", "444444"].find((value) => !valid.includes(value)) ?? "");
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await code.fill(totpCode(key, currentStep()));
  await page.getByRole("button", { name: "Turn on" }).click();
  const recoveryCodes = page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem");
  await expect(recoveryCodes).toHaveCount(10);
  const [first = "", second = ""] = (await recoveryCodes.allInnerTexts()).map((text) => text.trim());
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("The second factor is on.");

  /** Sign out, and sign in with the password and a code. */
  const signInWithCode = async (value: () => string) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL((url) => url.pathname === "/sign-in");
    await page.locator('input[name="username"]').fill(factor.username);
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(code).toBeVisible();
    await code.fill(value());
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL((url) => url.pathname === "/");
    await page.waitForLoadState("networkidle");
  };
  // The code of the confirmation is used: the code of the next time step signs in.
  await signInWithCode(() => totpCode(key, currentStep() + 1));
  expect(await menuLabels(page)).toEqual(factor.menu);
  // A recovery code signs in one time.
  await signInWithCode(() => first);
  await page.goto("/second-factor");
  await expect(page.getByText("Recovery codes left: 9")).toBeVisible();
  // A recovery code turns off the factor.
  await code.fill(second);
  await page.getByRole("button", { name: "Turn off" }).click();
  await expect(page.getByRole("button", { name: "Turn on" })).toBeVisible();
});
