// The front ends show only the pages and the operations that the role of
// the user allows (ADR 0012), a new user can sign up (ADR 0016) and
// confirm the email address (ADR 0023), a user can reset the password
// (ADR 0017), a user of a record rule sees only the records of the rule
// (ADR 0018, ADR 0025), a user signs in with a provider (ADR 0020), a
// user turns on a second factor and signs in with a code (ADR 0024), and
// the receiver of a change gets a notice in the bell (ADR 0041) and its
// email, and turns off the emails of a notification (ADR 0044), and a
// user that a text mentions gets a notice too (ADR 0043).
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
 * emails that the mock SMTP or SES server wrote to its file (one JSON line
 * each).
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

/** Return the subjects of the emails of the notices to an address with a text, from the file of the mock SMTP server. */
function noticeEmails(mailbox: string, to: string, text: string): string[] {
  if (!existsSync(mailbox)) return [];
  return readFileSync(mailbox, "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as { to: string[]; subject: string; text: string })
    .filter((email) => email.to.includes(to) && email.text.includes(text) && email.text.includes("/notice-settings"))
    .map((email) => email.subject);
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
  // An app of another delivery of the messages has the same pages: only the delivery is new.
  const screenshots = auth?.screenshots !== false;
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "Did you forget the password?" }).click();
  await page.waitForURL((url) => url.pathname === "/forgot-password");
  await expect(page.getByRole("heading", { name: "Reset the password" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  if (screenshots) {
    await expect(page).toHaveScreenshot([expected.binding, auth?.app ?? "", mode, "forgot-password.png"]);
  }
  await page.goto("/reset-password?token=example");
  await expect(page.getByRole("heading", { name: "Set a new password" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  if (screenshots) {
    await expect(page).toHaveScreenshot([expected.binding, auth?.app ?? "", mode, "reset-password.png"]);
  }
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

for (const rule of auth?.recordRules ?? []) {
  test(`the record rule of the role ${rule.role} limits the ${rule.entity} records`, async ({ page }, testInfo) => {
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
    // The form of a new record does not show the owner and the values that the rule sets.
    if (rule.form) {
      await page.getByRole("button", { name: rule.form.label, exact: true }).first().click();
      await expect(page.locator(`#${rule.form.firstId}`)).toBeVisible();
      for (const id of rule.form.hiddenIds) {
        await expect(page.locator(`#${id}`), id).toHaveCount(0);
      }
    }
    // A record of the rule opens. Another record does not exist.
    await page.goto(rule.ownPath);
    await expect(page.getByText(rule.ownTitle, { exact: true }).first()).toBeVisible();
    await page.goto(rule.otherPath);
    await expect(page.getByText(rule.otherMessage, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(rule.otherTitle, { exact: true })).toHaveCount(0);
  });
}

for (const provider of auth?.providers ?? []) {
  test(`a user signs in with the provider ${provider.name}, and sees the menu of its role`, async ({ browser, baseURL }, testInfo) => {
    test.skip(testInfo.project.name !== "light", "The sign-in does not depend on the color mode.");
    for (const [index, { loginHint, groups = [], menu }] of provider.signIns.entries()) {
      // Each sign-in starts without a session, in a new context of the browser.
      const context = await browser.newContext({ baseURL });
      const page = await context.newPage();
      if (loginHint !== undefined) {
        // The mock provider takes the user and the groups from the authorization request. The
        // start of the sign-in redirects to it, and a route does not see a redirect: the route
        // changes the redirect of the start.
        await page.route(/\/auth\/providers\/[^/]+\/start/, async (route) => {
          const response = await route.fetch({ maxRedirects: 0 });
          const location = new URL(response.headers()["location"] ?? "");
          location.searchParams.set("login_hint", loginHint);
          location.searchParams.set("groups", groups.join(","));
          await route.fulfill({ response, headers: { ...response.headers(), location: location.toString() } });
        });
      }
      await page.goto("/sign-in");
      const app = new URL(page.url()).origin;
      await page.getByRole("button", { name: provider.title, exact: true }).click();
      // The browser goes to the provider, and comes back to the start page of the app.
      await page.waitForURL((url) => url.origin === app && url.pathname === "/");
      await page.waitForLoadState("networkidle");
      expect(await menuLabels(page), `${loginHint ?? "the mock user"} with the groups [${groups.join(", ")}]`).toEqual(menu);
      if (index === provider.signIns.length - 1 && provider.signOut) {
        // The sign-out also ends the session at the provider: the browser goes through its logout URL.
        const { url, clientId, returnParam } = provider.signOut;
        const logout = page.waitForRequest((request) => request.url().startsWith(`${url}?`));
        await page.getByRole("button", { name: "Sign out", exact: true }).click();
        const query = new URL((await logout).url()).searchParams;
        expect(query.get("client_id")).toBe(clientId);
        expect(query.get(returnParam)).toBe(`${app}/sign-in`);
        await page.waitForURL((url) => url.origin === app && url.pathname === "/sign-in");
      }
      await context.close();
    }
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

test("the receiver of a change finds the notice in the bell of the top bar", async ({ page }, testInfo) => {
  const notice = auth?.notice;
  test.skip(!notice || testInfo.project.name !== "light", "One check in the light mode.");
  if (!notice) return;
  const password = auth?.password ?? "";
  const count = page.getByTestId("notice-count");
  await signIn(page, notice.actor, password);
  await page.goto(notice.path);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  await sheet.getByRole("combobox", { name: notice.field, exact: true }).click();
  await page.getByRole("option", { name: notice.value, exact: true }).click();
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  // The user of the change gets no notice.
  await expect(count).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL((url) => url.pathname === "/sign-in");
  await signIn(page, notice.receiver, password);
  await expect(count).toHaveText("1");
  await page.getByRole("button", { name: "Notices: 1 unread", exact: true }).click();
  const item = page.getByRole("list", { name: "Notices", exact: true }).getByRole("button").filter({ hasText: notice.text });
  await expect(item).toBeVisible();
  // A click opens the detail page of the record, and marks the notice read.
  await item.click();
  await page.waitForURL((url) => url.pathname === notice.path);
  await expect(count).toHaveCount(0);

  const emails = auth?.noticeEmails;
  if (!emails) return;
  if (emails.mailbox !== null) {
    // A scheduler calls the route of the job each minute. The run sends the email of the notice.
    const response = await page.request.post("/api/jobs/notice_emails", {
      headers: { authorization: `Bearer ${emails.secret}` },
    });
    expect(response.status()).toBe(200);
    const mailbox = emails.mailbox;
    await expect.poll(() => noticeEmails(mailbox, emails.to, notice.text)).toHaveLength(1);
  }
  // The bell links to the page of the settings: a switch for each notification with emails.
  await page.getByRole("button", { name: /^Notices/ }).click();
  await page.getByRole("link", { name: "Email settings", exact: true }).click();
  await page.waitForURL((url) => url.pathname === "/notice-settings");
  for (const label of emails.labels) {
    await expect(page.getByRole("switch", { name: label, exact: true })).toBeChecked();
  }
  const first = page.getByRole("switch", { name: emails.labels[0], exact: true });
  await first.click();
  await expect(first).not.toBeChecked();
  // The choice stays after a new load of the page.
  await page.reload();
  await expect(page.getByRole("switch", { name: emails.labels[0], exact: true })).not.toBeChecked();
});

test("a mention in a text shows as a link, and gives the user a notice in the bell", async ({ page }, testInfo) => {
  const mention = auth?.mention;
  test.skip(!mention || testInfo.project.name !== "light", "One check in the light mode.");
  if (!mention) return;
  const password = auth?.password ?? "";
  await signIn(page, mention.actor, password);
  await page.goto(mention.path);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  const text = sheet.getByRole("textbox", { name: mention.field, exact: true });
  // After @, the text area suggests the users. A choice puts the mention into the text.
  await text.fill(`Please check @${mention.name.slice(0, 3)}`);
  await page.getByRole("option", { name: `@${mention.name}`, exact: true }).click();
  await expect(text).toHaveValue(/^Please check @\[.+\]\([0-9a-f-]{36}\) $/);
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  if (mention.userPath) {
    const link = page.getByRole("link", { name: `@${mention.name}`, exact: true });
    await expect(link).toHaveAttribute("href", mention.userPath);
  } else {
    await expect(page.getByText(`@${mention.name}`, { exact: true })).toBeVisible();
  }

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL((url) => url.pathname === "/sign-in");
  await signIn(page, mention.receiver, password);
  await page.getByRole("button", { name: /^Notices/ }).click();
  const item = page.getByRole("list", { name: "Notices", exact: true }).getByRole("button").filter({ hasText: mention.text });
  await expect(item).toBeVisible();
  await item.click();
  await page.waitForURL((url) => url.pathname === mention.path);
});
