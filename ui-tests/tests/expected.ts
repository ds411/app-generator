// The values that the tests expect, from the app definition.
// scripts/smoke_test.py writes the file before it runs the tests.
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

/** The test language of scripts/translation_test.py. */
export type ExpectedTestLanguage = {
  code: string;
  /** The locale of the test language: the `lang` of the page. */
  locale: string;
  /** The direction of the test language: the `dir` of the page. */
  direction: "ltr" | "rtl";
  /** The key of the selected language in the browser storage, and the name of its cookie. */
  storageKey: string;
  /** The texts that are not UI text: the values of the records and the names of the languages. */
  ignore: string[];
  /** The pages with an approved screenshot in the test language, in ui-tests/approved/<binding>/<direction>/. */
  screenshots: string[];
};

/** An action of a page, and if the role sees it. */
export type ExpectedAction = {
  path: string;
  /** The title of the page. */
  title: string;
  label: string;
  shown: boolean;
};

/** The sign-in and the permissions of scripts/auth_ui_test.py. */
export type ExpectedAuth = {
  /** The name of the app, for the folder of the approved screenshots. */
  app: string;
  /** The password of each user. */
  password: string;
  roles: {
    role: string;
    /** The user name of a user with the role. */
    username: string;
    /** The labels of the menu items that the role sees. */
    menu: string[];
    /** The paths of the pages that the role may not open. */
    deniedPaths: string[];
    actions: ExpectedAction[];
  }[];
  /** A public page, and what a user without a session sees. */
  anonymous?: { path: string; title: string; menu: string[]; actions: ExpectedAction[] };
  /** The sign-up (ADR 0016): the values of the required fields, and the menu of a new user. */
  signUp?: {
    /** The IDs of the widgets and their values. `{n}` in a value becomes a unique number. */
    fields: { id: string; value: string }[];
    /** The ID of the widget of the user name. */
    usernameId: string;
    password: string;
    /** The labels of the menu items that the role of a new user sees. */
    menu: string[];
    /**
     * The verification of the email address (ADR 0023), only if the app has
     * the page of the link: the widget of the address, and the file of the
     * mock SMTP server with the emails of the app.
     */
    verifyEmail?: { addressId: string; mailbox: string } | null;
  };
  /** The password reset (ADR 0017), only if the app has the reset pages. */
  passwordReset?: {
    /** A user whose password the test changes. */
    username: string;
    /** The file of the mock SMTP server with the emails of the app: the reset links. */
    mailbox: string;
  };
  /**
   * The second factor (ADR 0024): a user who turns it on, signs out, and
   * signs in with a code that the test computes. The menu is the menu of
   * the role of the user.
   */
  secondFactor?: { username: string; menu: string[] } | null;
  /** The record rules of `read` (ADR 0018, ADR 0025): a user of the role sees only the records of the rule. */
  recordRules?: {
    role: string;
    entity: string;
    /** The user of the role with the most records of the rule. */
    username: string;
    /** A page with a list of the records, and its title. */
    listPath: string;
    listTitle: string;
    /** The titles of the records of the rule, and of the other records. */
    own: string[];
    others: string[];
    /** The detail page of a record of the rule, and its title. */
    ownPath: string;
    ownTitle: string;
    /** The detail page of another record, its title, and the message that shows instead. */
    otherPath: string;
    otherTitle: string;
    otherMessage: string;
    /** The form of a new record on the list page: the label of its button, a widget that shows, and the widgets that do not. */
    form: { label: string; firstId: string; hiddenIds: string[] } | null;
  }[];
  /** The sign-in with each provider that makes users (ADR 0020): the button, and the menu of the user. */
  providers?: { name: string; title: string; menu: string[] }[];
};

export type Expected = {
  binding: string;
  pages: ExpectedPage[];
  /** The color tokens. */
  colors: ExpectedToken[];
  /** The font size of the body text (`typography.body`), for each mode. */
  bodyFontSize: Record<Mode, string>;
  /** Only for the test of the test language. */
  testLanguage?: ExpectedTestLanguage;
  /** Only for the test of the sign-in and the permissions. */
  auth?: ExpectedAuth;
};

// APPGEN_UI_EXPECTED names another file, so that the checks of two apps
// can run at the same time.
const file =
  process.env.APPGEN_UI_EXPECTED || fileURLToPath(new URL("../expected.json", import.meta.url));

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
