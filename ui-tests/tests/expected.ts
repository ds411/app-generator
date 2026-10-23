// The values that the tests expect, from the app definition.
// scripts/smoke_test.py writes expected.json before it runs the tests.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export type Mode = "light" | "dark";

export type ExpectedPage = {
  name: string;
  path: string;
  title: string;
  /** The path parameters, for example ["id"]. */
  params: string[];
  /** True if the page shows the detail view of a record. */
  detail: boolean;
  /** The labels of the page actions that run an operation on the record, for example "Delete". */
  recordActions: string[];
};

/** An ID that no record has. */
export const UNKNOWN_ID = "00000000-0000-4000-8000-000000000000";

export type ExpectedToken = {
  path: string;
  /** The CSS variable of the token, for example `--primary`. */
  variable: string;
  light: string;
  dark: string;
};

export type Expected = {
  binding: string;
  pages: ExpectedPage[];
  /** The color tokens. */
  colors: ExpectedToken[];
  /** The font size of the body text (`typography.body`), for each mode. */
  bodyFontSize: Record<Mode, string>;
};

const file = fileURLToPath(new URL("../expected.json", import.meta.url));

export const expected: Expected = JSON.parse(readFileSync(file, "utf8")) as Expected;

export function modeOf(projectName: string): Mode {
  return projectName === "dark" ? "dark" : "light";
}

/** A regular expression for the paths of a page, for example `^/projects/[^/]+$`. */
export function pathPattern(path: string): RegExp {
  const source = path
    .split("/")
    .map((part) => (part.startsWith("{") ? "[^/?#]+" : part.replace(/[.*+?^$()|[\]\\]/g, "\\$&")))
    .join("/");
  return new RegExp(`^${source}$`);
}
