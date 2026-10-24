# 0010. Translations of the UI text

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

The front ends showed the text of the definition in one language. ADR
0002 reserved the section `translations`, and planned a message key for
each element ID and property, for example
`entities.Task.fields.title.label`.

Much of the text that an app shows has no element ID and property: the
default labels that the generator makes from names (`Due date` for
`due_date`), the default texts of forms and states (`Cancel`, `No
records yet`), and texts that more than one element shares. With keys
by element, an author translates the same word many times, and cannot
translate a default text.

The templates write the text in many places: JSX text, JSX attributes,
and data in modules, for example the badge sets and the page titles.

## Decision

- A key of `translations.languages.<code>.text` is a text of the default
  language, as the app shows it. Its value is the translation.
- The definition is in the default language. Each other language
  translates the same keys. The validator reports a key that one
  language has and another language does not have.
- The front ends call `t(text)` at render time. `t` looks up the text in
  the selected language, and gives the text itself if no translation
  exists. The template helpers `jsx_text` and `jsx_attr` write the call
  when the definition has translations. The helper `tr` wraps the
  expression of a text that a module holds, where the component shows it.
- A binding can now change each rendered file (`Binding.finish`). The
  front ends use it to import `t` in each file that calls it.
- The fixed texts of the components (the shadcn/ui components, the app
  shell, the views, the forms, and the messages of the React app) go
  through the same helpers, so a language can translate them too.
  `scripts/vendor_shadcn.py` changes the fixed texts of the shadcn/ui
  components to calls of the helpers. `docs/dsl.md` lists the fixed
  texts.
- A text can hold values in braces, for example `Page {page} of
  {count}`. `t(text, values)` fills them in after the translation, so a
  language can change their order. The template helpers `jsx_format`
  and `js_format` write such a text. The validator reports a
  translation that does not have the values of its key
  (`translation-values`).
- `app_texts` renders an app in memory and returns each text that it
  translates. `scripts/translation_test.py` uses it to make a test
  language that changes each text, and the UI tests find no text of the
  default language on the pages of the React and the Next.js apps.
- The selected language is in the browser storage. A change renders the
  pages again. Next.js renders the default language on the server, and
  the client changes to the stored language after the hydration.

## Consequences

- An author translates each text once, and can translate the default
  texts of the generator.
- A key does not show which element uses it. A text that two elements
  share has one translation, also when the two meanings differ.
- The validator cannot report a text of the app that a language does not
  translate, because some texts come from the templates. Such a text
  shows in the default language.
- The format of dates and numbers stays in the default language. A
  later change can add it.
- A new fixed text in a template must use a text helper, else it shows
  in the default language. `scripts/untranslated_text.mjs` finds such a
  text in the code, and the test language finds it on the pages.
- An app without translations has the same code as before.
