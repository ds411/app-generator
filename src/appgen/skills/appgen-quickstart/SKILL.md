---
name: appgen-quickstart
description: "Make a working app from one or more prompts that describe it, with appgen. The skill picks the defaults of the app from the words of the prompts: the binding (nextjs, react, or fastapi), the sign-in, the roles, the languages, the seed records, the APIs, and the other options. It asks no question about a default, records the defaults at the top of app.yaml, and uses the appgen skill to write the definition, generate the apps, and check them. Use this skill when a task asks for a new app from a description, for example 'make an app for a neighborhood tool library', in a folder without an app definition, and when a later prompt of the same session changes a default of that app, for example 'use a Python API' or 'add German'. For the other tasks with appgen (a change to an existing definition, the generation gaps, the seed records, and the CLI), use the appgen skill."
---

# appgen quick start

This skill makes a first working app from prompts, without questions.
It gives the **defaults**: the bindings and the options that the
prompts do not name. It gives the order of the work, and the record of
the chosen defaults in `app.yaml`.

The skill does not describe the CLI, the DSL, or the gaps. For these,
load the `appgen` skill: `/appgen` in Claude Code, or read
[../appgen/SKILL.md](../appgen/SKILL.md). Its reference files give the
details:

- [../appgen/references/new-definition.md](../appgen/references/new-definition.md):
  write the definition.
- [../appgen/references/dsl.md](../appgen/references/dsl.md): the keys
  of each section.
- [../appgen/references/seed-data.md](../appgen/references/seed-data.md):
  the seed records.
- [../appgen/references/fill-gaps.md](../appgen/references/fill-gaps.md):
  the hand-written code of the gaps.
- [../appgen/references/change-definition.md](../appgen/references/change-definition.md):
  a later change.

## Steps

1. Read all prompts. For each row of [Bindings](#bindings) and
   [Defaults](#defaults), find its signal in the prompts. A binding, a
   folder, a name, or an option that the prompts give wins over the
   table.
2. Do not ask about a default. Ask only when the prompts
   [conflict](#questions).
3. Load the `appgen` skill, and read its `references/new-definition.md`.
4. Write `app.yaml` in the current folder: the schema line, the
   [record of the defaults](#the-record-of-the-defaults), and then the
   definition, step by step, as `new-definition.md` tells. Add the keys
   of each chosen default. Validate after each step.
5. Generate each binding into the folder `./<binding>/`, for example
   `./nextjs/`, and check it with the CLI loop of the `appgen` skill.
6. Fill each gap whose logic the prompts give, as `fill-gaps.md` tells,
   for example "a member can mark a loan as returned". Leave the other
   gaps open.
7. Install, lint, type check, and test each app with the commands of
   its README. Do not start a server that keeps running.
8. End with the [summary](#the-summary).

Prefer the DSL to hand-written code: the CRUD shorthand, workflows,
rules, computed fields, and record rules give a working app without a
gap. Use a `custom` operation only for logic that the DSL cannot give.

## Bindings

| Signal in the prompts | Bindings | Keys |
| --------------------- | -------- | ---- |
| No stack. An app, a web app, a site, a portal, or a tool. | `nextjs` | |
| Next.js. | `nextjs` | |
| Only an API: a REST API, or a back end for a mobile app or for another front end. | `fastapi` | |
| A front end with its own Python API: React and Python (or FastAPI), or React without the words of a prototype. | `react`, `fastapi` | `app.x-react-data: api` |
| A prototype, a mock-up, or a demo without a server and a database. | `react` | `app.x-react-data: mock` |

With `react` and `fastapi`, both apps come from the same definition.
The READMEs of both apps tell how the React app finds the API
(`VITE_API_URL`) and how the API allows the React app (`CORS_ORIGINS`).

## Defaults

A key with `<...>` stands for a name that you choose, for example
`entities.<Entity>` for `entities.Tool`.

| Default | Signal in the prompts | Keys |
| ------- | --------------------- | ---- |
| `app` | Always: the subject of the prompts. `name` in kebab case, for example `tool-library`. | `app.name`, `app.title`, `app.description` |
| `entities` | Always: each thing that the app keeps records of. | `entities.<Entity>.crud: { views: [table, detail], forms: [create, update] }` |
| `pages` | Always with `nextjs` or `react`: a start page with a dashboard, a list page and a detail page for each entity, and a menu. | `pages.<page>.path: /`, `ui.dashboards`, `ui.layouts`, `ui.navigation`, `ui.defaults.layout` |
| `auth` | Users, members, customers, staff, accounts, a sign-in, "my" records, or roles. A sign-in with an email address and a password. | `auth.user_entity`, `auth.username_field: email` |
| `access` | Roles, or rights that differ between groups of users, for example "only the librarians add tools". The role with the most rights gets all operations and pages. | `access.role_field: role`, `access.roles.<role>.operations: ["*"]`, `access.roles.<role>.pages: ["*"]` |
| `records` | Users see or change only their own records, for example "members see their loans". | `access.roles.<role>.records.<Entity>.owner` |
| `sign_up` | A public app: anyone, customers, or visitors make their own accounts. | `auth.sign_up.fields`, `auth.sign_up.default_role`, `auth.password_reset`, `auth.delivery: smtp` |
| `public` | Parts that visitors use without an account, for example a public catalog. | `auth.public_pages`, `auth.public_operations` |
| `second_factor` | A second factor: two-factor, 2FA, or MFA. | `auth.second_factor.totp: true` |
| `providers` | Company accounts: single sign-on (SSO), Microsoft Entra ID (Azure AD), Okta, Google Workspace, Amazon Cognito, or OpenID Connect. | `auth.providers.<provider>.issuer`, `auth.providers.<provider>.client_id_env`, `auth.providers.<provider>.client_secret_env`, `auth.providers.<provider>.create_users: true`, `auth.providers.<provider>.claims`, `auth.providers.<provider>.default_role` |
| `password` | Only company accounts, for example "the staff sign in with their Microsoft account". | `auth.password: false` |
| `translations` | More than one language, or a language other than English. The first language of the prompts is the default language. | `translations.default`, `translations.languages.<code>.label`, `translations.languages.<code>.text` |
| `seed` | Data in the prompts, for example a list of rooms, or a data file (CSV, JSON, or YAML) that the prompts name. | `seed.<Entity>.records`, `seed.<Entity>.file` |
| `apis` | An outside service that the app calls, with an OpenAPI document in the folder. | `apis.<api>.document`, `apis.<api>.base_url_env`, `apis.<api>.operations`, `apis.<api>.security` |
| `jobs` | Work at a time: "every night", "each Monday", or "a reminder one day before". | `jobs.<job>.schedule`, `jobs.<job>.entity`, `jobs.<job>.at`, `jobs.<job>.offset`, `jobs.<job>.operation` |
| `notifications` | Tell users about a change: "notify", "tell the owner when", or "an alert". With "by email", also an email. | `notifications.<notification>.entity`, `notifications.<notification>.event: changed`, `notifications.<notification>.receivers`, `notifications.<notification>.text`, `notifications.<notification>.email: true` |
| `workflows` | A status with fixed steps, for example "a request is approved or rejected". | `workflows.<workflow>.entity`, `workflows.<workflow>.field`, `workflows.<workflow>.initial`, `workflows.<workflow>.transitions` |
| `files` | Files, photos, images, documents, or attachments. | `entities.<Entity>.fields.<field>.type: image`, `storage.kind: local` |
| `places` | Addresses on a map, or "near me". | `entities.<Entity>.fields.<field>.type: point` |
| `history` | "Who changed what", an audit log, or an undo of a change. | `entities.<Entity>.history: true` |
| `live` | Users see the changes of other users at once, for example on a board. | `entities.<Entity>.live: true` |

For Amazon Cognito, the issuer of a provider is
`https://cognito-idp.<region>.amazonaws.com/<user pool ID>`. For
Microsoft Entra ID, it is
`https://login.microsoftonline.com/<tenant ID>/v2.0`.

## Questions

Ask no question about a default: use the table. Ask only in these
cases:

- **The prompts conflict.** Two words of the same request that no app
  can satisfy, for example "anyone can make an account" and "only our
  staff can use the app". Ask one question, and wait for the answer.
  A later prompt that changes a default is no conflict: it wins.
- **The app needs a file that you cannot make.** For example the
  OpenAPI document of a named API, or a data file that the prompts name
  and the folder does not have. Make the app without that part, and
  name the part and the file in the summary. Do not stop.

## The record of the defaults

Write the chosen defaults as comments at the top of `app.yaml`, after
the schema line: a line `# appgen-quickstart defaults:`, then one line
for each chosen default. Each line has the name of the row, the choice,
and the words of the prompt that caused it:

```text
# - <row>: <choice>. Prompt: "<words of the prompt>"
```

Write a line only for a chosen default, not for a row without its
signal. Use `binding` for the row of [Bindings](#bindings). An example:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json
# appgen-quickstart defaults:
# - binding: nextjs, in the folder nextjs. Prompt: "an app for our community garden"
# - app: community-garden. Prompt: "an app for our community garden"
# - entities: Gardener, Plot, and Harvest. Prompt: "gardeners rent plots and log their harvests"
# - pages: a dashboard, and a list and a detail page of each entity. Prompt: "an app for our community garden"
# - auth: a sign-in with an email address and a password. Prompt: "gardeners rent plots"
# - access: the roles coordinator and gardener. Prompt: "the coordinators give out the plots"
# - records: a gardener sees only the own harvests. Prompt: "each gardener sees only their own harvests"
version: 0

app:
  name: community-garden
  title: Community Garden
  description: Give out the plots of a community garden, and log the harvests.

entities:
  Gardener:
    crud: { views: [table, detail], forms: [create, update] }
    display_field: name
    fields:
      name: { type: string, required: true, max_length: 80 }
      email: { type: email, required: true, unique: true }
      role: { type: enum, values: [coordinator, gardener], default: gardener }
    relations:
      plots: { kind: one_to_many, target: Plot, inverse: gardener }
      harvests: { kind: one_to_many, target: Harvest, inverse: gardener }
  Plot:
    crud: { views: [table, detail], forms: [create, update] }
    display_field: code
    fields:
      code: { type: string, required: true, unique: true, max_length: 10 }
      size_m2: { type: integer, min: 1 }
    relations:
      gardener: { kind: many_to_one, target: Gardener, on_delete: set_null, inverse: plots }
  Harvest:
    crud: { views: [table, detail], forms: [create, update] }
    display_field: crop
    fields:
      crop: { type: string, required: true, max_length: 80 }
      picked_on: { type: date, required: true }
      weight_kg: { type: decimal, scale: 2, min: 0 }
    relations:
      gardener:
        { kind: many_to_one, target: Gardener, required: true, on_delete: cascade, inverse: harvests }

auth:
  user_entity: Gardener
  username_field: email

access:
  role_field: role
  roles:
    coordinator: { label: Coordinator, operations: ["*"], pages: ["*"] }
    gardener:
      label: Gardener
      operations: [list_plots, read_plot, list_harvests, read_harvest, create_harvest, update_harvest]
      pages: [dashboard, plots, plot_detail, harvests, harvest_detail]
      records:
        Harvest: { owner: gardener }

pages:
  dashboard: { path: /, title: Dashboard, content: { dashboard: overview } }
  plots: { path: /plots, title: Plots, entity: Plot, content: { view: plot_table } }
  plot_detail: { path: "/plots/{id}", title: Plot, entity: Plot, content: { view: plot_detail } }
  harvests:
    path: /harvests
    title: Harvests
    entity: Harvest
    content: { view: harvest_table }
    actions:
      new_harvest: { kind: form, form: new_harvest, label: New harvest, icon: plus }
  harvest_detail:
    path: "/harvests/{id}"
    title: Harvest
    entity: Harvest
    content: { view: harvest_detail }
    actions:
      edit: { kind: form, form: edit_harvest, label: Edit, icon: pencil }
  gardeners: { path: /gardeners, title: Gardeners, entity: Gardener, content: { view: gardener_table } }
  gardener_detail:
    { path: "/gardeners/{id}", title: Gardener, entity: Gardener, content: { view: gardener_detail } }

ui:
  layouts:
    app_shell: { sidebar: { navigation: main, title: Community Garden, icon: sprout } }
  navigation:
    main:
      items:
        dashboard: { page: dashboard, icon: layout-dashboard }
        plots: { page: plots, icon: map }
        harvests: { page: harvests, icon: wheat }
        gardeners: { page: gardeners, icon: users }
  dashboards:
    overview:
      title: Overview
      widgets:
        plots: { kind: stat, label: Plots, entity: Plot, aggregate: count, link: plots }
        harvests: { kind: stat, label: Harvests, entity: Harvest, aggregate: count, link: harvests }
  defaults:
    layout: app_shell
```

## The summary

End the task with a summary for the user, in this order:

1. **Defaults**: each line of the record, in words.
2. **Folders**: `app.yaml`, and the folder and the binding of each app.
3. **Start**: the commands that install, migrate, seed, and start each
   app, from the table "Commands" of its README. With `react` and
   `fastapi`, also the settings that connect the two apps.
4. **Open gaps**: each entry of `gaps` of `appgen check`, with its
   file, and each part that you did not make, with the file that it
   needs.

## A later prompt

A later prompt of the same session can change a default, for example
"use a Python API", "add German", or "the staff sign in with Entra ID".

1. Change the line of the default in the record, with the words of the
   new prompt. Add a line for a new default.
2. Change the definition as `change-definition.md` of the `appgen`
   skill tells. Validate.
3. Generate again into the same folders, and check. A new run keeps
   the hand-written code of the extension files.
4. For a new binding, generate it into its own folder `./<binding>/`.
   Write the logic of each filled gap again in the extension file of
   the same element in the new app, in the language of the new
   binding, with a `@trace:manual` trace. Keep the folder of the old
   binding: do not delete hand-written code. The summary names the old
   folder, and tells that the record no longer has its binding.
5. End with the summary.
