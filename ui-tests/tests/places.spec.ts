// The map view of tests/fixtures/places.yaml (ADR 0046): a marker for each
// place, and the list of the places in the visible area of the map.
// scripts/places_ui_test.py starts the app with its seed records and a
// local tile server: the Next.js app, the React app with mock data, and
// the React app with the FastAPI app, whose list endpoint gives the places
// in the visible area. The last test adds a place.
import { expect, type Locator, type Page, test } from "@playwright/test";

import { expected } from "./expected";

const places = expected.places;

/** Return the map of the page. */
function map(page: Page): Locator {
  return page.getByRole("region", { name: places?.title ?? "" });
}

/** Return the names in the list of the places in the visible area of the map. */
async function listed(page: Page): Promise<string[]> {
  const items = await page.getByRole("region", { name: "In the map" }).getByRole("listitem").allInnerTexts();
  return items.map((text) => text.trim());
}

test.describe.configure({ mode: "serial" });

test("a map shows a marker for each place with the tiles of the setting, and a move changes its list", async ({ page }, testInfo) => {
  test.skip(!places || testInfo.project.name !== "light", "Only the test of the map views, in the light mode.");
  if (!places) return;
  await page.goto(places.path);
  const shown = map(page);
  await expect(shown.locator(".leaflet-marker-icon")).toHaveCount(places.all.length);
  await expect.poll(() => listed(page)).toEqual(places.all);
  await expect(page.getByText(`${places.all.length} in the map`, { exact: true })).toBeVisible();

  // The tiles come from the tile server of the setting.
  await expect(shown.locator("img.leaflet-tile-loaded").first()).toBeVisible();
  const sources = await shown.locator("img.leaflet-tile").evaluateAll((items) => items.map((item) => (item as HTMLImageElement).src));
  expect(sources.length).toBeGreaterThan(0);
  expect(sources.filter((source) => !source.startsWith(places.tiles))).toEqual([]);

  // A move of the map to the south (Shift and the down arrow pan it by
  // 240 pixels) leaves the places of the north out of the list.
  await shown.focus();
  await page.keyboard.press("Shift+ArrowDown");
  await expect.poll(() => listed(page)).toEqual(places.south);
  await expect(page.getByText(`${places.south.length} in the map`, { exact: true })).toBeVisible();
});

test("a near filter keeps the places near a point on the map and in its list", async ({ page }, testInfo) => {
  test.skip(!places || testInfo.project.name !== "light", "Only the test of the map views, in the light mode.");
  if (!places) return;
  await page.goto(places.path);
  const shown = map(page);
  await expect(shown.locator(".leaflet-marker-icon")).toHaveCount(places.all.length);

  await page.getByLabel(places.near.label, { exact: true }).fill(places.near.value);
  await expect(shown.locator(".leaflet-marker-icon")).toHaveCount(places.near.names.length);
  await expect.poll(() => listed(page)).toEqual(places.near.names);

  await page.getByRole("button", { name: "Reset" }).click();
  await expect(shown.locator(".leaflet-marker-icon")).toHaveCount(places.all.length);
  await expect.poll(() => listed(page)).toEqual(places.all);
});

test("a place of the list and a marker open the place", async ({ page }, testInfo) => {
  test.skip(!places || testInfo.project.name !== "light", "Only the test of the map views, in the light mode.");
  if (!places) return;
  await page.goto(places.path);
  const first = places.all[0] ?? "";
  await expect.poll(() => listed(page)).toEqual(places.all);
  await page.getByRole("region", { name: "In the map" }).getByRole("link", { name: first, exact: true }).click();
  await expect(page).toHaveURL(/\/places\/[^/]+$/);
  await expect(page.getByText(first, { exact: true }).first()).toBeVisible();

  // Enter on a marker opens its place: the markers take the keyboard focus.
  await page.goto(places.path);
  const marker = map(page).locator(`.leaflet-marker-icon[title="${places.marker}"]`);
  await expect(marker).toHaveCount(1);
  await marker.press("Enter");
  await expect(page).toHaveURL(/\/places\/[^/]+$/);
  await expect(page.getByText(places.marker, { exact: true }).first()).toBeVisible();
});

test("the form of a new place takes its point, and the map shows the new place", async ({ page }, testInfo) => {
  test.skip(!places || testInfo.project.name !== "light", "Only the test of the map views, in the light mode.");
  if (!places) return;
  const { form } = places;
  await page.goto(form.path);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill(form.name);
  await page.getByRole("combobox", { name: "Kind", exact: true }).click();
  await page.getByRole("option", { name: "Museum", exact: true }).click();
  // The location has no default, so its first input is the first empty latitude.
  const latitude = page.getByRole("spinbutton", { name: "Latitude" }).first();
  const longitude = page.getByRole("spinbutton", { name: "Longitude" }).first();

  // A latitude without a longitude is not a point.
  await latitude.fill(form.lat);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText("Enter a value.", { exact: true })).toBeVisible();

  await longitude.fill(form.lng);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(new RegExp(`${places.path}$`));
  await expect(map(page).locator(".leaflet-marker-icon")).toHaveCount(places.all.length + 1);
  await expect.poll(() => listed(page)).toContain(form.name);
});
