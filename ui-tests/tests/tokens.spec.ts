// The design tokens of the definition control the UI, in both color modes.
import { expect, type Page, test } from "@playwright/test";

import { expected, modeOf } from "./expected";

type Rgba = [number, number, number, number];

/**
 * Return the computed value of a CSS property for elements with the
 * classes or the styles, one for each probe. Colors come back as sRGB
 * channels: the build can write a color in another form (for example
 * `#fff` for `#ffffff`, or `lab()` for `oklch()`), so the tests compare
 * the pixels that the browser draws.
 */
async function probe(page: Page, property: string, probes: { className?: string; style?: string }[]) {
  return page.evaluate(
    ({ property, probes }) => {
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      const context = canvas.getContext("2d", { willReadFrequently: true })!;
      const rgba = (color: string) => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        return Array.from(context.getImageData(0, 0, 1, 1).data);
      };
      return probes.map((init) => {
        const element = document.createElement("div");
        if (init.className) element.className = init.className;
        if (init.style) element.setAttribute("style", init.style);
        document.body.appendChild(element);
        const value = getComputedStyle(element).getPropertyValue(property);
        element.remove();
        return property.endsWith("color") ? rgba(value) : value;
      });
    },
    { property, probes },
  );
}

/** Expect two colors to be equal, with a tolerance of one step for rounding. */
function expectSameColor(name: string, actual: unknown, want: unknown) {
  const [a, b] = [actual as Rgba, want as Rgba];
  const close = a.every((channel, index) => Math.abs(channel - b[index]) <= 1);
  expect(close, `${name}: got rgba(${a.join(", ")}), want rgba(${b.join(", ")})`).toBe(true);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1").first()).toBeVisible();
});

test("the app shows the color mode of the system", async ({ page }, testInfo) => {
  const mode = modeOf(testInfo.project.name);
  const html = page.locator("html");
  if (mode === "dark") await expect(html).toHaveClass(/\bdark\b/);
  else await expect(html).not.toHaveClass(/\bdark\b/);
});

test("each color token is a CSS variable with the value of the mode", async ({ page }, testInfo) => {
  const mode = modeOf(testInfo.project.name);
  const actual = await probe(
    page,
    "color",
    expected.colors.map((t) => ({ style: `color: var(${t.variable})` })),
  );
  const want = await probe(
    page,
    "color",
    expected.colors.map((t) => ({ style: `color: ${t[mode]}` })),
  );
  expected.colors.forEach((token, index) => expectSameColor(token.path, actual[index], want[index]));
});

test("the components use the primary color token", async ({ page }, testInfo) => {
  const mode = modeOf(testInfo.project.name);
  const primary = expected.colors.find((token) => token.path === "color.primary");
  test.skip(!primary, "The definition has no token color.primary.");
  const [fromClass, fromToken] = await probe(page, "background-color", [
    { className: "bg-primary" },
    { style: `background-color: ${primary![mode]}` },
  ]);
  expectSameColor("bg-primary", fromClass, fromToken);
});

test("the body uses the background color and the font size of the tokens", async ({ page }, testInfo) => {
  const mode = modeOf(testInfo.project.name);
  const body = await page.evaluate(() => {
    const style = getComputedStyle(document.body);
    return { background: style.backgroundColor, fontSize: style.fontSize };
  });
  const background = expected.colors.find((token) => token.path === "color.background");
  if (background) {
    const [actual, want] = await probe(page, "background-color", [
      { style: `background-color: ${body.background}` },
      { style: `background-color: ${background[mode]}` },
    ]);
    expectSameColor("body background", actual, want);
  }
  const [fontSize] = await probe(page, "font-size", [{ style: `font-size: ${expected.bodyFontSize[mode]}` }]);
  expect(body.fontSize).toBe(fontSize);
});
