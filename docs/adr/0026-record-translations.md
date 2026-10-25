# 0026. Translations of the values of the records

- Date: 2026-10-25
- Deciders: Maintainers

## Status

Accepted

## Context

ADR 0010 translates the text of the UI and the messages of the apps. The
values of the records stay in one language: a task has one title, also
for the users who read the app in another language. An app with users
of more than one language needs some text fields with a value in each
language, for example the title and the description of a task.

The three bindings store the records in a relational database: the
FastAPI app and the Next.js app in Postgres (or SQLite and PGlite on the
local machine). The apps search, sort, filter, and check the unique
rules in the database.

The options for the storage:

- **A JSON column for each translatable field.** The column of the field
  keeps the value of the default language. A second column,
  `<field>_translations`, keeps the values of the other languages as a
  JSON object, by the code of the language. A read gets all languages
  with the record, without a join. The search, the sort, the filters, and
  the unique constraints use the column of the field, as before. The
  database cannot sort or search by the value of another language
  without an index on an expression.
- **A table of translations for each entity**, with one row for each
  record and language. The database can sort and search in each
  language with a join. Each read, list, and write needs the join or a
  second query, and each binding needs more code. A unique rule in each
  language needs a constraint in the table of translations.
- **A row for each language in the table of the entity.** The records of
  one entity in more than one language are more than one row. The
  relations, the IDs, and the counts of the lists get more difficult.

## Decision

We use a JSON column for each translatable field.

- `entities.<E>.fields.<f>.translatable: true` marks a field whose
  values have a translation for each language of `translations`. It is
  for `string` and `text` fields. `appgen validate` reports it for
  another type, for a computed field, for a param of an operation, and
  for a definition without `translations` (`invalid-option`). The name
  `<f>_translations` is for the values of the field, so another field or
  relation cannot have it (`duplicate-name`).
- The column of the field keeps the value of the default language. The
  column `<f>_translations` (JSON, JSONB on Postgres) keeps the values of
  the other languages by their codes, or null without a translation.
- The search, the sort, the filters, and the unique rules use the value
  of the default language: the column of the field.
- FastAPI:
  - A read gives the value of the language of the request (the
    `LanguageMiddleware` of ADR 0010), else the value of the default
    language. `<f>_translations` is null.
  - With the query parameter `translations=all`, the read gives the
    values of all languages in `<f>_translations`, the default language
    included, for the forms. The field keeps the value of the language
    of the request. The endpoints that return a record take the
    parameter, also a create, a change, and a custom operation.
  - A create or a change sets the value of the language of the request.
    A new record without a value of the default language takes the value
    of the request as its default value, so that each record has a value
    in the default language. `<f>_translations` in the input sets the
    value of each language that it gives, the default language included.
    Null or an empty text removes the value of another language. The
    value of each language has the rules of the field (for example
    `max_length`), and a required field cannot get null in the default
    language.
  - `app/core/i18n.py` has the functions: `translated` (the read schemas),
    `store_translations` (the repositories), and `translations_query`
    (the dependency of the parameter).
  - The first migration creates the columns. An app that exists gets
    them with the next migration of the `alembic revision --autogenerate`
    flow (ADR 0009). `scripts/check_schema_change.py` makes a field
    translatable in an app with a record, and checks that the next
    migration adds the column and that the record keeps its value.
  - The generated tests read and write a translatable field of each
    entity in the default language and in a second language.
- The front ends (Next.js and React) store and show the values in the
  same way. Their stories decide the details of the forms.

## Consequences

- A read gives each record in the language of the user, without a join
  and without a second query.
- The records that exist keep their values as the values of the default
  language. A translation is optional: without it, the users of a
  language read the value of the default language.
- The search, the sort, and the filters do not use the values of the
  other languages. A user who searches in German finds a task by the
  English title, not by the German title.
- A unique rule applies to the value of the default language only.
- A JSON column has no length limit of its own: the input rules of the
  API check the length of each value.
- A client that does not know the translations gets the value of its
  language in the field, as before.
- The Next.js app with the seed data has the values of the default
  language only: the seed has no values in other languages.
