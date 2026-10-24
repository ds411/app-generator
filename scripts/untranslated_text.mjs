// Find the UI text in a generated front end that does not call `t`.
//
// With a `translations` section, each text that the app shows must go
// through `t` (ADR 0010). This script reads each .tsx file of an app with
// the TypeScript parser, and reports the text that does not:
//
// - JSX text, for example `<span>Close</span>`.
// - A text attribute with a string, for example `aria-label="Close"`.
// - A string or a template in a JSX expression or a text attribute, for
//   example `{text ?? "Loading"}`, outside a call of `t`.
// - A string as the default value of a parameter, for example
//   `title = "Command Palette"`, and a string argument of `toast`.
//
// Run it from the repository root. It needs the TypeScript package of
// ui-tests/ (`pnpm --dir ui-tests install`):
//
//   node scripts/untranslated_text.mjs <app folder>
//
// The script writes one line for each text (`file:line: text`), and
// exits with 1 if it finds a text.
import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, relative } from "node:path";

const require = createRequire(new URL("../ui-tests/package.json", import.meta.url));
const ts = require("typescript");

/** The attributes and props that hold a text that the user reads. */
const TEXT_ATTRIBUTES = new Set([
  "aria-label",
  "aria-description",
  "aria-roledescription",
  "aria-valuetext",
  "alt",
  "title",
  "placeholder",
  "label",
  "description",
  "text",
  "message",
  "confirmLabel",
]);
const LETTER = /[A-Za-z]/;

/** True if a string of a parameter default or a call argument is a text, not a name or a class list. */
function isText(value) {
  return LETTER.test(value) && (/^[A-Z][a-z]/.test(value) || / [a-z]/.test(value)) && !/[-:/[]/.test(value);
}

/** True if a node is in a call of `t`. */
function inT(node) {
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (ts.isCallExpression(parent) && ts.isIdentifier(parent.expression) && parent.expression.text === "t") {
      return true;
    }
    if (ts.isJsxAttribute(parent) || ts.isJsxElement(parent) || ts.isJsxSelfClosingElement(parent)) return false;
  }
  return false;
}

/** The strings and templates that an expression can give as its value. */
function* values(expression) {
  if (ts.isParenthesizedExpression(expression)) {
    yield* values(expression.expression);
  } else if (ts.isConditionalExpression(expression)) {
    yield* values(expression.whenTrue);
    yield* values(expression.whenFalse);
  } else if (ts.isBinaryExpression(expression)) {
    const operator = expression.operatorToken.kind;
    if (operator === ts.SyntaxKind.QuestionQuestionToken || operator === ts.SyntaxKind.BarBarToken) {
      yield* values(expression.left);
      yield* values(expression.right);
    } else if (operator === ts.SyntaxKind.AmpersandAmpersandToken) {
      yield* values(expression.right);
    }
  } else if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    yield [expression, expression.text];
  } else if (ts.isTemplateExpression(expression)) {
    const parts = [expression.head.text, ...expression.templateSpans.map((span) => span.literal.text)];
    yield [expression, parts.join("…")];
  }
}

function scan(file, source) {
  const found = [];
  const add = (node, text) => {
    const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
    found.push(`${file}:${line + 1}: ${text.trim().replace(/\s+/g, " ")}`);
  };
  const visit = (node) => {
    if (ts.isJsxText(node) && LETTER.test(node.text)) {
      add(node, node.text);
    } else if (ts.isJsxAttribute(node) && node.initializer && TEXT_ATTRIBUTES.has(node.name.getText(source))) {
      const value = ts.isJsxExpression(node.initializer) ? node.initializer.expression : node.initializer;
      for (const [part, text] of value ? values(value) : []) {
        if (LETTER.test(text) && !inT(part)) add(part, text);
      }
    } else if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
      for (const [part, text] of values(node.expression)) {
        if (LETTER.test(text) && !inT(part)) add(part, text);
      }
    } else if ((ts.isParameter(node) || ts.isBindingElement(node)) && node.initializer) {
      for (const [part, text] of values(node.initializer)) {
        if (isText(text) && !inT(part)) add(part, text);
      }
    } else if (ts.isCallExpression(node) && /^toast(\.\w+)?$/.test(node.expression.getText(source))) {
      for (const argument of node.arguments) {
        for (const [part, text] of values(argument)) {
          if (isText(text) && !inT(part)) add(part, text);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

function* tsxFiles(folder) {
  for (const entry of readdirSync(folder, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
    const path = join(folder, entry.name);
    if (entry.isDirectory()) yield* tsxFiles(path);
    else if (entry.name.endsWith(".tsx")) yield path;
  }
}

const [folder] = process.argv.slice(2);
if (!folder) {
  console.error("usage: node scripts/untranslated_text.mjs <app folder>");
  process.exit(2);
}
const found = [];
for (const path of [...tsxFiles(folder)].sort()) {
  const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  found.push(...scan(relative(folder, path), source));
}
for (const line of found) console.log(line);
process.exit(found.length ? 1 : 0);
