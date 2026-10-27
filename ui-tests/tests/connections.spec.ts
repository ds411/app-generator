// A user connects an account of each API that the app calls in the name
// of a user on the page /connections, calls the API in an action, and
// disconnects the account (ADR 0033). scripts/connection_ui_test.py
// starts the app and the mock server of the API. For an API with the
// authorization code flow, the authorization page of the mock server
// allows the access at once. For an API with HTTP Basic and the
// credentials of each user (#487), the user fills in the form: first
// with a wrong password, which the check of the server does not accept.
// The React app with mock data connects at once.
import { expect, type Locator, type Page, test } from "@playwright/test";

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

/** Fill in the form of the credentials of an item, and send it. */
async function sendCredentials(item: Locator, password: string): Promise<void> {
  if (!connections) return;
  await item.getByLabel("User name").fill(connections.credentials.username);
  await item.getByLabel("Password or API token").fill(password);
  await item.getByRole("button", { name: "Connect", exact: true }).click();
}

test("a user connects and disconnects an account of each API", async ({ page }, testInfo) => {
  test.skip(!connections || testInfo.project.name !== "light", "Only the test of the connections, in the light mode.");
  if (!connections) return;
  await signUp(page);

  await page.goto("/connections");
  await expect(page.getByRole("heading", { name: "Connections" })).toBeVisible();
  for (const { title, kind, rejected } of connections.apis) {
    const item = page.getByRole("listitem").filter({ hasText: title });
    await expect(item).toContainText("Not connected");
    if (kind === "basic") {
      if (rejected !== null) {
        await sendCredentials(item, connections.credentials.wrong);
        await expect(page.getByRole("main").getByRole("alert")).toHaveText(rejected);
        await expect(item).toContainText("Not connected");
      }
      await sendCredentials(item, connections.credentials.password);
      await expect(page.getByRole("main").getByRole("status")).toHaveText("The account is connected.");
      await expect(item).toContainText(`Connected as ${connections.credentials.username}`);
      await expect(item.getByLabel("Password or API token")).toHaveCount(0);
      continue;
    }
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
    await expect(item.getByRole("button", { name: "Connect", exact: true })).toBeVisible();
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
