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
  /** The origins of the websites that can show the page in a frame (`embed`). */
  embed: string[];
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
  /**
   * The notices (ADR 0041): a user with all operations changes the state
   * of a record of the receiver with the edit form of its detail page.
   * The receiver finds the notice in the bell of the top bar.
   */
  notice?: {
    /** The user names of the user of the change and of the receiver. */
    actor: string;
    receiver: string;
    /** The detail page of the record. */
    path: string;
    /** The label of the field of the state, and the label of the new state. */
    field: string;
    value: string;
    /** The text of the notice. */
    text: string;
  } | null;
};

/** The connections of a user to the APIs, for scripts/connection_ui_test.py (ADR 0033). */
export type ExpectedConnections = {
  /** The APIs with the authorization code flow: the name in the paths, and the title. */
  apis: { api: string; title: string }[];
  /** The inputs of the sign-up of a new user, by ID: `{n}` in a value is a new number. */
  signUp: { id: string; value: string }[];
  password: string;
  /** The row action that calls an API in the name of the user, or null for an app with mock data. */
  sync: { path: string; action: string; toast: string; notConnected: string } | null;
};

/** The views of the rows of the queries of tests/fixtures/listings.yaml, for scripts/listings_ui_test.py (ADR 0045). */
export type ExpectedQueryViews = {
  /** A table of a query of records, with a required text filter and a number filter. */
  table: {
    path: string;
    /** The titles of the first page and of the second page, and the count of all rows. */
    pages: string[][];
    total: number;
    /** The label and the value of the number filter, and the titles of its rows. */
    filter: { label: string; value: string; titles: string[] };
    /** A value of the number filter without rows, and the title of the empty state. */
    none: { value: string; title: string };
    /** The label of the required filter, another value, and the titles of its rows. */
    required: { label: string; value: string; titles: string[] };
    /** The title of the message while the required filter has no value. */
    missing: string;
  };
  /** A card list of a query of rows that are not records, with a path parameter. */
  cards: {
    path: string;
    /** The values of the fields of each card, by label. */
    cards: Record<string, string>[];
    emptyPath: string;
    empty: string;
  };
  /** A calendar of the records of a query of the record of the page. */
  calendar: {
    /** The title of the record in the table, and the path suffix of its calendar. */
    record: string;
    suffix: string;
    /** The day that the browser shows first (UTC). */
    today: string;
    events: string[];
    others: string[];
  };
};

/** The values of the signed-in users, for scripts/sessions_ui_test.py (M36). */
export type ExpectedSessions = {
  password: string;
  users: {
    username: string;
    /** The stat widgets with `$me` on the start page: the label, and the value. */
    stats: { label: string; value: string }[];
    /** The list page with a filter of `$me`: the titles of the records of the user, and of the others. */
    list: { path: string; title: string; own: string[]; others: string[] };
    /** The form with the default `$me`: the label of its button, the ID of the widget, and its text. */
    form: { label: string; id: string; value: string } | null;
    /** The list pages with a column of a total with `$me`: the value of each row. */
    totals: { path: string; title: string; column: string; rows: { title: string; value: string }[] }[];
  }[];
  /**
   * The secret link of a record (ADR 0049): a user with the update
   * operation makes it, a user without it sees no button. A guest sees the
   * title of the record and the display value of a related record.
   */
  share: {
    admin: string;
    member: string;
    /** The detail page of the record, and the path of its links without the token. */
    path: string;
    prefix: string;
    title: string;
    related: string;
    /** The text that a revoked link shows. */
    invalid: string;
  } | null;
  /**
   * The other users on a record page (ADR 0052): the admin types in the
   * form of the button "Edit", and the member reads the record. The page of
   * a list is a link away from the record page.
   */
  presence: {
    admin: { username: string; name: string; initials: string };
    member: { username: string; name: string; initials: string };
    path: string;
    title: string;
    away: { label: string; path: string };
  } | null;
};

export type Expected = {
  binding: string;
  pages: ExpectedPage[];
  /** The color tokens. */
  colors: ExpectedToken[];
  /** The font size of the body text (`typography.body`), for each mode. */
  bodyFontSize: Record<Mode, string>;
  /** The entities whose changes the open views show at once (ADR 0051): none with mock data. */
  live?: string[];
  /** Only for the test of the test language. */
  testLanguage?: ExpectedTestLanguage;
  /** Only for the test of the sign-in and the permissions. */
  auth?: ExpectedAuth;
  /** Only for the test of the connections to the APIs. */
  connections?: ExpectedConnections;
  /** Only for the test of the views of the queries. */
  queryViews?: ExpectedQueryViews;
  /** Only for the test of the signed-in users. */
  sessions?: ExpectedSessions;
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
