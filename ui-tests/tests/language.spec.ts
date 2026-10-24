// The language switch shows the UI text in the selected language, and the
// app keeps the language for the next visit. The example definition
// (project-tracker) has an English and a German text for the page title
// and for the label of the switch.
import { expect, test } from "@playwright/test";

test("the language switch shows the pages in the selected language", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();

  await page.getByLabel("Language").selectOption("de");
  await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "de");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Projekte" })).toBeVisible();

  await page.getByLabel("Sprache").selectOption("en");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();
});
