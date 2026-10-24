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
- The React app keeps the selected language in the browser storage. A
  change renders the pages again.
- The Next.js app keeps the selected language in a cookie
  (`<app name>-language`), and the server renders each request in the
  language of the request: the cookie, else the first language of
  `Accept-Language` that the app has (by code or locale, also by the
  primary language), else the default language
  (`src/shared/lib/i18n-server.ts`). The root layout sets `html lang` and
  gives the language to the `LanguageProvider`. On the server, `t` reads
  the language from an `AsyncLocalStorage`: the metadata and the server
  actions run in `inRequestLanguage`, and the provider enters the
  language for the render of the client components, so two requests at
  the same time keep their languages. In the browser, the first render
  uses the language of the server, so the hydration matches. A change
  sets the cookie, renders the pages again, and refreshes the server
  parts (`router.refresh()`), for example the page title.
- The server actions of Next.js give their messages in the language of
  the request: the rules of the entities, the workflows, the sign-in,
  the access checks, and the errors of the data access.
- The FastAPI app gives its messages in the language of the request.
  `app/core/i18n.py` holds the locales and the translations of the
  definition. `LanguageMiddleware` takes the first language of
  `Accept-Language` that the API has, as the Next.js server does, else
  the default language, and keeps it in a context variable for
  `t(text, **values)`. Each response has the locale in
  `Content-Language`, and `Vary: Accept-Language`. The problem details
  translate their title and their detail: the errors of the input, the
  rules of the entities, the workflows, the sign-in, the access checks,
  the data access, the sort keys, and the rate limit. The message of
  each error of the input is a message of the form fields of the front
  ends, for example `Enter a value.`, else `The value is not valid.`,
  and the `type` of the error keeps its kind. `docs/dsl.md` lists the
  messages.
- With `x-react-data: api`, the API client of the React app sends the
  locale of the selected language in `Accept-Language`.
- Each language has a locale, a language tag (BCP 47) in
  `translations.languages.<code>.locale`. The default is the code. The
  validator reports a locale that is not a language tag
  (`translation-locale`).
- The front ends format the dates and numbers with `Intl` in the locale
  of the selected language: `getLocale` of `src/shared/lib/i18n.ts`
  gives it, and `src/shared/lib/format.ts` keeps one format for each
  locale and options. The format of a field (`currency`, `date`, and so
  on) and its currency stay the same in each language. The calendar
  views and the date pickers start the week on the first day of the
  locale (`Intl.Locale` week info, else Monday) and use its names of the
  months and days. `scripts/vendor_shadcn.py` changes the date picker
  and the chart tooltip of shadcn/ui to use the locale. The `lang` of
  the page is the locale.

## Consequences

- An author translates each text once, and can translate the default
  texts of the generator.
- A key does not show which element uses it. A text that two elements
  share has one translation, also when the two meanings differ.
- The validator cannot report a text of the app that a language does not
  translate, because some texts come from the templates. Such a text
  shows in the default language.
- A language with a code that is not a language tag, for example
  `pt_br`, must give a locale (`pt-BR`).
- In a browser without the week info of `Intl.Locale`, the week starts on
  Monday.
- The test language has the Japanese locale, so a date or number that
  does not use the locale shows Latin letters, and the UI test finds it.
- A new fixed text in a template must use a text helper, else it shows
  in the default language. `scripts/untranslated_text.mjs` finds such a
  text in the code, and the test language finds it on the pages.
- With translations, the routes of the Next.js app are dynamic, because
  the root layout reads the cookie and the headers of the request.
- The provider of the language enters the language of the request in the
  async context of the render (`enterWith`). The translation test sends
  requests in two languages at the same time to show that each page
  keeps its language.
- The translations of the FastAPI app hold each text of each language,
  also the texts of the UI, so that an extension file can translate its
  own messages with `t`.
- With translations, the messages of the input errors of the FastAPI
  app are not the messages of Pydantic, also in the default language.
- The generated tests of the FastAPI app check the selection of the
  language, and one message in two languages.
- An app without translations has the same code as before.
