// A user connects an account of each API with the authorization code flow
// on the page /connections, calls the API in an action, and disconnects
// the account (ADR 0033). scripts/connection_ui_test.py starts the app
// and the mock server of the API, whose authorization page allows the
// access at once. The React app with mock data connects at once.
import { expect, type Page, test } from "@playwright/test";

import { expected } from "./expected";

const connections = expected.connections;

/** Sign up a new user: the app signs the user in. */
async function signUp(page: Page): Promise<void> {
  if (!connections) return;
  const n = String(Date.now());
  await page.goto("/sign-up");
  for (const field of connections.signUp) {
    await page.locator(`#${field.id}`).fill(field.value.replaceAll("{n}", n));
  }
  await page.locator("#sign-up-password").fill(connections.password);
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL((url) => url.pathname !== "/sign-up");
}

/** Run the row action that calls the API on the first record, and return the text of the toast. */
async function sync(page: Page): Promise<string> {
  if (!connections?.sync) return "";
  await page.goto(connections.sync.path);
  await page.getByRole("button", { name: "Actions" }).first().click();
  await page.getByRole("menuitem", { name: connections.sync.action }).click();
  const toast = page.locator("[data-sonner-toast]").last();
  await expect(toast).toBeVisible();
  const text = (await toast.textContent()) ?? "";
  await toast.evaluate((element) => element.remove());
  return text;
}

test("a user connects and disconnects an account of each API", async ({ page }, testInfo) => {
  test.skip(!connections || testInfo.project.name !== "light", "Only the test of the connections, in the light mode.");
  if (!connections) return;
  await signUp(page);

  await page.goto("/connections");
  await expect(page.getByRole("heading", { name: "Connections" })).toBeVisible();
  for (const { title } of connections.apis) {
    const item = page.getByRole("listitem").filter({ hasText: title });
    await expect(item).toContainText("Not connected");
    await item.getByRole("button", { name: "Connect" }).click();
    // The browser goes to the authorization server, and comes back to the page.
    await page.waitForURL((url) => url.pathname === "/connections" && url.hash.startsWith("#connected="));
    await expect(page.getByRole("main").getByRole("status")).toHaveText("The account is connected.");
    await expect(page.getByRole("listitem").filter({ hasText: title })).toContainText("Connected");
  }

  if (connections.sync) {
    expect(await sync(page)).toContain(connections.sync.toast);
  }

  await page.goto("/connections");
  for (const { title } of connections.apis) {
    const item = page.getByRole("listitem").filter({ hasText: title });
    await item.getByRole("button", { name: "Disconnect" }).click();
    await expect(item).toContainText("Not connected");
    await expect(item.getByRole("button", { name: "Connect" })).toBeVisible();
  }

  if (connections.sync) {
    expect(await sync(page)).toContain(connections.sync.notConnected);
  }
});

test("the page of the connections needs a signed-in user", async ({ page }, testInfo) => {
  test.skip(!connections || testInfo.project.name !== "light", "Only the test of the connections, in the light mode.");
  await page.goto("/connections");
  await page.waitForURL((url) => url.pathname === "/sign-in");
  expect(new URL(page.url()).searchParams.get("next")).toBe("/connections");
});
