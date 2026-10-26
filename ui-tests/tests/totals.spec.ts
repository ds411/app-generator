// A total of a relation (ADR 0034): the computed field task_count of the
// project tracker ("Tasks") counts the tasks of a project. The Next.js app
// counts them in the database, and the React app in its mock data. The
// test finds a project with tasks in the table of the projects, and sees
// the same count in the detail view of the project and in the pagination
// of its tasks. The test changes no record, so that the screenshots of
// the pages do not change.
import { expect, type Locator, type Page, test } from "@playwright/test";

import { expected, pathPattern } from "./expected";

const detail = expected.pages.find((p) => p.name === "project_detail");

/** Return the value of a field in the sections of the detail page. */
function fieldValue(page: Page, label: string): Locator {
  return page.locator("dt", { hasText: new RegExp(`^${label}$`) }).locator("xpath=following-sibling::dd[1]");
}

/** Return the link to the detail page and the count of the first row with a count above 0. */
async function projectWithTasks(table: Locator, column: number, pattern: RegExp): Promise<[string, number] | undefined> {
  for (const row of await table.locator("tbody tr").all()) {
    const count = Number((await row.locator("td").nth(column).innerText()).trim());
    const hrefs = await row.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
    const href = hrefs.find((item) => pattern.test(item));
    if (count > 0 && href) return [href, count];
  }
  return undefined;
}

test("a project shows the count of its tasks in the table and in the detail view", async ({ page }) => {
  test.skip(detail === undefined, "The definition has no page project_detail.");
  await page.goto("/projects");
  await page.waitForLoadState("networkidle");
  const table = page.locator("table").first();
  await expect(table.locator("tbody tr").first()).toBeVisible();
  const headers = (await table.locator("thead th").allInnerTexts()).map((text) => text.trim());
  const column = headers.indexOf("Tasks");
  expect(column, `the column Tasks in ${headers.join(", ")}`).toBeGreaterThanOrEqual(0);

  const found = await projectWithTasks(table, column, pathPattern(detail?.path ?? ""));
  expect(found, "a project with tasks").toBeDefined();
  const [href, count] = found ?? ["", 0];
  await page.goto(href);
  await page.waitForLoadState("networkidle");
  await expect(fieldValue(page, "Tasks")).toHaveText(String(count));

  // The tab of the tasks lists the same tasks: the range of the pagination
  // ends with the count, for example "1–3 of 3".
  await page.getByRole("tab", { name: "Tasks", exact: true }).click();
  await expect(page.getByText(new RegExp(`^\\d+–\\d+ of ${count}$`))).toBeVisible();
});
