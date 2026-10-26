// A form uploads an image, the detail view shows it, and the form removes
// it again (ADR 0027). The test uses the project tracker: its task detail
// page has the action "Edit" with the form "Edit task", which has the
// image field "Screenshot". At the end the task has no screenshot, so the
// screenshots of the pages stay the same.
import { expect, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";
import { firstRecordLink } from "./links";

const detail = expected.pages.find((p) => p.name === "task_detail");
/** A PNG image of 48 × 32 pixels: a blue and white checkerboard. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAADAAAAAgCAIAAADbtmxLAAAARklEQVR42u3WsQ0AIAgEQJZxMsd2A93BuACWxoJLvvyEq4BofaUZc6d53Q8gIKByoF+" +
    "Db30gIKB6IJsaCAjIP+R0AAEVBx0soKK1++CmdgAAAABJRU5ErkJggg==",
  "base64",
);

test("a form uploads an image and removes it", async ({ page }) => {
  test.skip(detail === undefined, "The definition has no page task_detail.");
  const href = await firstRecordLink(page, "/tasks", pathPattern(detail?.path ?? ""));
  expect(href, "a link to a task").toBeDefined();
  await page.goto(href ?? "");
  await page.waitForLoadState("networkidle");
  const main = page.locator("main");
  const image = main.getByRole("img", { name: "screenshot.png" });
  await expect(image).toHaveCount(0);

  // A file of a type that the field does not allow: the form does not save.
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const sheet = page.getByRole("dialog");
  const input = sheet.locator('input[type="file"]');
  await input.setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("notes") });
  await expect(sheet.getByText("notes.txt", { exact: true })).toBeVisible();
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet.getByText(/^Select a file of a type that the field allows/)).toBeVisible();

  // An image: the form shows a preview, and the detail view shows the image after the save.
  await input.setInputFiles({ name: "screenshot.png", mimeType: "image/png", buffer: PNG });
  await expect(sheet.getByText("screenshot.png", { exact: true })).toBeVisible();
  // The label of the field names the button of the file dialog.
  const button = sheet.getByRole("button", { name: "Screenshot", exact: true });
  await expect(button).toHaveText("Select another file");
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(48);

  // The form removes the image.
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await expect(sheet.getByText("screenshot.png", { exact: true })).toBeVisible();
  await sheet.getByRole("button", { name: "Remove the file", exact: true }).click();
  await expect(button).toHaveText("Select a file");
  await sheet.getByRole("button", { name: "Save", exact: true }).click();
  await expect(sheet).toBeHidden();
  await expect(image).toHaveCount(0);
});
