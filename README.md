# app-generator

A proof of concept for an application code generator. A YAML DSL
defines an application. The generator uses Jinja2 templates to write
the code for a binding (a target stack). Traces in the generated code
refer back to the app definition. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the plan and the rules.

## Quick start

1. Install [uv](https://docs.astral.sh/uv/), and for the front-end apps
   [pnpm](https://pnpm.io/) and Node.js 24. Docker runs the apps.
2. Clone the repository, and install appgen:

   ```sh
   git clone https://github.com/ds411/app-generator.git
   cd app-generator
   uv sync
   ```

3. Validate the example definition:

   ```sh
   uv run appgen validate examples/project-tracker/app.yaml
   ```

4. Generate an app. The bindings are `nextjs` (a full-stack app),
   `fastapi` (a REST API), and `react` (a front end with mock data):

   ```sh
   uv run appgen generate examples/project-tracker/app.yaml -b react -o /tmp/tracker
   ```

5. Check the traces of the app against the definition:

   ```sh
   uv run appgen check examples/project-tracker/app.yaml /tmp/tracker
   ```

6. Run the app:

   ```sh
   cd /tmp/tracker && pnpm install && pnpm dev
   ```

   Each generated app has a README with its commands, and a Dockerfile.
   [docs/example-apps.md](docs/example-apps.md) shows how to run each
   example app on your machine and in Docker.

To write your own definition, copy `examples/project-tracker/app.yaml`
and change it. The docs:

| Document                             | Content                                              |
| ------------------------------------ | ---------------------------------------------------- |
| [docs/example-apps.md](docs/example-apps.md) | How to generate, check, and run the example apps. |
| [docs/dsl.md](docs/dsl.md)           | The reference of the app definition, with examples.  |
| [docs/traces.md](docs/traces.md)     | The trace format, generation gaps, and the checker reports. |
| [docs/bindings.md](docs/bindings.md) | How to write a binding.                              |
| [docs/cognito-entra-id.md](docs/cognito-entra-id.md) | The sign-in with Amazon Cognito and Entra ID over SAML. |
| [docs/evaluation.md](docs/evaluation.md) | The evaluation of the proof of concept, and the next steps. |
| [docs/evaluation-skills.md](docs/evaluation-skills.md) | The evaluation of the agent skill with agent tasks. |
| [docs/adr/](docs/adr/)               | The architecture decision records.                   |

## Setup

This section is for the maintainers of appgen. Install [uv](https://docs.astral.sh/uv/). Then run this command in the
repository root:

```sh
uv sync
```

uv installs Python 3.14 (from `.python-version`) and the locked
dependencies (from `uv.lock`) into `.venv/`.

Enable the pre-push hook, which runs the checks before each push:

```sh
git config core.hooksPath .githooks
```

See [CONTRIBUTING.md](CONTRIBUTING.md#pre-push-hook) for the details.

## Commands

| Task                  | Command                                                    |
| --------------------- | ---------------------------------------------------------- |
| Show the CLI help     | `uv run appgen --help`                                     |
| Validate a definition | `uv run appgen validate examples/project-tracker/app.yaml` |
| Check the traces      | `uv run appgen check <definition> <code-folder>`           |
| List orphaned files   | `uv run appgen orphans <definition> <code-folder>`         |
| Generate an app       | `uv run appgen generate <definition> -b <binding> -o <dir>`  |
| Lint                  | `uv run ruff check`                                        |
| Check the formatting  | `uv run ruff format --check`                               |
| Format the code       | `uv run ruff format`                                       |
| Type check            | `uv run pyright`                                           |
| Test                  | `uv run pytest`                                            |
| Run all hook checks   | `APPGEN_CHECK_ALL=1 .githooks/pre-push < /dev/null`        |
| Show the changed check sections | `uv run scripts/check_plan.py select --base origin/main` |
| Update golden files   | `APPGEN_UPDATE_GOLDEN=1 uv run pytest`                     |
| Update the schema     | `uv run appgen schema --out schema/app.schema.json`        |
| Update the skill DSL reference | `uv run scripts/update_skill_references.py` |
| Install the agent skill | `uv run appgen skills install` |
| Smoke test the apps   | `uv run scripts/smoke_test.py [nextjs] [fastapi] [react]`  |
| UI tests (front ends) | `uv run scripts/smoke_test.py nextjs react --ui`           |
| Test language check   | `uv run scripts/translation_test.py [react] [nextjs]`      |
| Sign-in UI check      | `uv run scripts/auth_ui_test.py [react] [nextjs]`          |
| Connections UI check  | `uv run scripts/connection_ui_test.py [react] [nextjs] [react-api]` |

## Layout

| Path                   | Content                                                     |
| ---------------------- | ----------------------------------------------------------- |
| `src/appgen/`          | The generator and the CLI.                                  |
| `src/appgen/dsl/`      | The app definition DSL: the model, the loader, and checks.  |
| `src/appgen/dsl/ui/`   | The UI part of the DSL: design tokens and UI elements.      |
| `src/appgen/gen/`      | The generator core: the binding contract and the rendering. |
| `src/appgen/bindings/` | The bindings. `minimal` is the test binding of the core, `nextjs` writes a Next.js 16 app, `react` writes a React 19 app, and `fastapi` writes a FastAPI REST API. |
| `src/appgen/trace/`    | The trace scanner and the trace checker (ADR 0004).         |
| `src/appgen/skills/`   | The agent skill of appgen (ADR 0015).                       |
| `schema/`              | The JSON Schema of the DSL, for editors.                    |
| `tests/`               | The tests.                                                  |
| `docs/`                | The user docs: the DSL, traces, and bindings.               |
| `ui-tests/`            | The Playwright UI tests of the generated front ends.        |
| `docs/adr/`            | The architecture decision records.                          |
| `.githooks/`           | The git hooks (pre-push checks).                            |

[ADR 0002](docs/adr/0002-app-definition-dsl-v0.md) describes the DSL, and
[ADR 0003](docs/adr/0003-ui-dsl.md) describes its UI part.

## Editor support

`schema/app.schema.json` is the JSON Schema of the DSL. `appgen schema`
makes it from the Pydantic models, and a test fails if the committed
file is out of date. To let a YAML language server (for example the
YAML extension of VS Code) complete and check a definition, put this
line at the top of the file:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json
```

A relative path to `schema/app.schema.json` also works.

## Agent skill

`src/appgen/skills/appgen/` is an agent skill in the Agent Skills
format, for Claude Code, Codex, and other agents. It tells an agent how
to use the CLI (validate a definition, fix the diagnostics, generate an
app, and check its traces), how to write a new definition, how to change
a definition, how to fill the generation gaps, and how to add seed
records (the data that the apps start with). The skill is a part
of the package, so each version of appgen has its own skill.
[ADR 0015](docs/adr/0015-agent-skills.md) describes the design.

Install the skill into the folders that your agents read:

```sh
appgen skills install                 # ./.agents/skills/ and ./.claude/skills/
appgen skills install --scope user    # ~/.agents/skills/ and ~/.claude/skills/
appgen skills list                    # the installed version in each folder
appgen skills uninstall               # remove the files that appgen installed
```

| Target   | Scope     | Folder                                                    |
| -------- | --------- | --------------------------------------------------------- |
| `claude` | `project` | `<project>/.claude/skills/` (Claude Code)                 |
| `claude` | `user`    | `~/.claude/skills/`                                       |
| `claude` | `system`  | `/etc/claude-code/.claude/skills/` on Linux, `/Library/Application Support/ClaudeCode/.claude/skills/` on macOS |
| `agents` | `project` | `<project>/.agents/skills/` (Codex and other agents)      |
| `agents` | `user`    | `~/.agents/skills/`                                       |
| `agents` | `system`  | `/etc/codex/skills/`                                      |

`--target` (repeat it for more), `--scope`, and `--project-dir <folder>`
select the folders, and `--path <folder>` gives another skills folder.
The system scope is for shared machines and container images, and needs
root. Each installed copy has a record file (`.appgen-skill.json`) with
the appgen version and the hash of each file. A second install of the
same version changes no file, and an install of another version updates
the files. `install` and `uninstall` do not overwrite or remove a file
that a person changed, unless `--force`. `--dry-run` shows the changes
and writes no file.

`references/dsl.md` is a copy of `docs/dsl.md` with links to GitHub:
after a change to `docs/dsl.md`, run
`uv run scripts/update_skill_references.py`. Tests fail if the skill does
not agree with the CLI, the DSL, the diagnostic codes, or the extension
files of the bindings.
[docs/evaluation-skills.md](docs/evaluation-skills.md) records the
tasks that agents did with only the installed skill, and the fixes of
the skill that they showed. `scripts/evaluate_skill.py` prepares, runs,
and scores these tasks.

## One definition, three apps

The proof of concept generates three standalone apps from one
definition: a full-stack app (Next.js), a back-end REST API (FastAPI),
and a front-end app with mock data (React). Generate and check each app
of the example:

```sh
for binding in nextjs fastapi react; do
  uv run appgen generate examples/project-tracker/app.yaml -b $binding -o /tmp/tracker-$binding
  uv run appgen check examples/project-tracker/app.yaml /tmp/tracker-$binding
done
```

Each check reports no invalid traces and no uncovered elements. The
stubs of the custom operations (and in the front ends, of the custom UI
elements) and the logic of the webhook are open gaps until a developer
writes them: 11 for Next.js, 10 for React, and 5 for FastAPI. The
FastAPI app leaves out the pages and the UI by design, so its report
lists the kinds `page` and `ui` as excluded. The React app has no
server, so it leaves out the webhooks. `tests/test_end_to_end.py` runs these
steps with the CLI.

`scripts/smoke_test.py` starts the apps in Docker, one at a time: the
Next.js app and the FastAPI app with Postgres (Docker Compose), and the
React app with nginx. It opens one page for each entity in the
Next.js and React apps, and calls the health check and the list endpoint
of each entity in the FastAPI app, which must give the seed records. The check scripts of the bindings
(`scripts/check-<binding>.sh`) run it on the image that they build, so
the pre-push hook runs it. The script header lists the environment
variables, for example `POSTGRES_IMAGE` for a mirror of the Postgres
image.

`ui-tests/` holds the Playwright UI tests of the front ends (pnpm).
`scripts/smoke_test.py --ui` runs them on a running Next.js or React
app: each page of the definition opens in the light and the dark mode
without a script error, the CSS variable of each color token has the
value of the mode, the components use the primary color, and the body
uses the background color and the font size of the tokens. The tests
save a screenshot of each page in `ui-tests/screenshots/<binding>/<mode>/`,
which git ignores, and compare it with the approved screenshot in
`ui-tests/approved/` (see CONTRIBUTING.md). Install the browser once:

```sh
pnpm --dir ui-tests install
pnpm --dir ui-tests exec playwright install chromium
uv run scripts/smoke_test.py react --ui
```

`scripts/translation_test.py` checks that the front ends translate each
text (ADR 0010). It generates the project tracker with a test language
that changes each text to `⟦text⟧`, and finds the UI text in the code
that does not call `t` (`scripts/untranslated_text.mjs`). Then it builds
and starts the React app and the Next.js app without Docker, and the UI
test `ui-tests/tests/test-language.spec.ts` opens each page in the test
language, with the page search, the menu of a record, and a form. A
Latin text without `⟦` that is not a value of the records fails the
test. For Next.js, it also sends requests in the test language and in
the default language at the same time, and each page must be in the
language of its request. The pre-push hook runs it with
`scripts/check-translations.sh`.

`scripts/auth_ui_test.py` checks that the front ends show only what the
role of the user allows (ADR 0012). It builds and starts the room
booking example with React and Next.js without Docker. The UI test
`ui-tests/tests/auth.spec.ts` signs in as a user of each role, compares
the menu with the menu that the role allows and with an approved
screenshot (`ui-tests/approved/<binding>/room-booking/<mode>/`), opens
the pages that the role may not open, and checks the page actions. The
pre-push hook runs it with `scripts/check-auth-ui.sh`.

`scripts/connection_ui_test.py` checks the page `/connections` of the
front ends (ADR 0033). It builds `tests/fixtures/api-connections.yaml`
with React, Next.js, and React with the FastAPI app. The UI test
`ui-tests/tests/connections.spec.ts` signs up, connects an account of
the calendar API at the mock OAuth server, syncs a calendar, and
disconnects the account. The script checks that the app sent the code
and the token to the mock server. The pre-push hook runs it with
`scripts/check-auth-ui.sh`.

The check scripts reuse caches, so a second run is faster:

- `docker build` reuses the image layers when the dependency files of
  the app do not change. The Dockerfiles keep the pnpm store and the uv
  cache in BuildKit cache mounts, so a build after a dependency change
  downloads only the changed packages.
- `pnpm install` on the host uses the shared pnpm store of the user
  (`pnpm store path`), and uv uses its shared cache.

Times of the pre-push hook in a cloud session (4 CPUs), with warm
caches:

| Push                                                | Time      |
| --------------------------------------------------- | --------- |
| The Python checks (pytest on 4 CPUs)                | 6 min     |
| The selection of the sections, after a change of `src/appgen/` | 15 to 60 s |
| All 51 sections (`APPGEN_CHECK_ALL=1`), two checks at a time | 44 min |
| The same, before the selection (six checks at a time, pytest on one CPU) | 45 min |

With all sections, the longest checks take about 20 minutes each:
`scripts/check-auth-ui.sh` 20 min, `scripts/check-nextjs.sh` 19 min,
`scripts/check-fastapi.sh` 19 min, `scripts/check-react.sh` 6 min,
`scripts/check-translations.sh` 3 min, and `scripts/check-react-api.sh`
2 min. A push runs only the sections that it changes (see
[CONTRIBUTING.md](CONTRIBUTING.md#pre-push-hook)). The 5 merges before
the selection would have run 4 to 37 of the 51 sections.

## Bindings

A binding is a `Binding` object (see `src/appgen/gen/binding.py`). It
declares its name, its template folder, its output layout (a list of
`Output` rules), and the element kinds that it covers. The generator
marks each element of a kind that the binding does not cover as a gap.
The rendering is deterministic: a missing template value stops the
run, the files are sorted by path, and each file has LF line endings
and one final newline. The golden file tests in `tests/golden/` compare
the output of the `minimal` binding with committed files.

Templates write traces (ADR 0004) with two Jinja2 helpers.
`trace_header(id, ...)` writes the header of a file: a notice and a file
trace for each ID. `trace(id, scope=None, kind=None, jsx=False)` writes
one trace. Both use the comment syntax of the output file, and stop the
run for an ID that is not an element. Each file that can hold comments
must have a trace. For a file without comments (for example JSON), the
manifest records the traces.

Templates can use the naming filters `camel`, `pascal`, `kebab`,
`snake`, and `constant` (see `src/appgen/gen/naming.py`), for example
`{{ name | pascal }}`. A binding can give its templates Python
functions in `helpers`, for example a function that converts a field
type to a TypeScript type. A helper must be deterministic.

An output rule can have `when`: a Jinja2 expression. If it is false,
the rule writes no file. For a rule with `for_each`, the expression
gets the context of each element, so `when="element.kind == 'custom'"`
writes a file only for the custom operations. A binding can also
declare a `context` function, which returns more template values for a
definition (it cannot replace the values of the generator, and it must
be deterministic), and more Jinja2 `filters`. `shared_template_dirs`
gives more template folders: the generator looks for a template in the
folder of the binding first, and then in these folders. The front-end
bindings share the templates in `src/appgen/bindings/shared/templates/`.

Templates get the design tokens as `tokens`: a flat list of
`ResolvedToken`, sorted by path. Each entry has the final value for the
light and the dark mode, with all references resolved, and keeps its
element ID for traces. The kind of an element is its class name in
snake case, for example `entity`, `token`, or `menu_item`. A `Field`
in `params` has the kind `param`.

`appgen generate <definition> --binding <name> --out <folder>`
validates the definition, generates the app, and prints a summary: the
files written and deleted, the gaps created, the other extension files
created, and the orphaned extension files. `Gaps created` lists each
element of a gap trace in an extension file that the run created, with
its file: the elements that the binding cannot generate, and the stubs
of the custom elements. A second run keeps the files, so it counts
them under `Gaps kept`. If the definition is not valid, it writes no
file and the exit code is 1. `--force` overwrites generated files that
have manual edits.

A binding can declare a `gap_rule`: an output rule that the generator
renders once for each element of a kind that the binding does not
cover. Each such file is an extension file (ADR 0005) with a gap trace
and a `TODO(appgen):` comment. The generator creates it once, and never
overwrites or deletes it.

A binding can also declare `excludes`: the element kinds that are out
of its scope, for example `page` and `ui` for a back-end binding. The
generator makes no gap for an element of an excluded kind, or for the
elements under it. The manifest records the excluded kinds, and
`appgen check` does not count these elements in the coverage.

`write_result()` writes a generation result into an output folder and
keeps a manifest in `.appgen/manifest.json`. The manifest lists each
generated file with its SHA-256 hash, and each extension file apart
(ADR 0005). A new run deletes the generated files that no rule writes
any more. It stops, and writes nothing, if a generated file has manual
edits or if a new file would overwrite a file that appgen did not
make, unless `force` is set. It never overwrites or deletes an
extension file.

A binding registers itself with an entry point in the group
`appgen.bindings` in `pyproject.toml`:

```toml
[project.entry-points."appgen.bindings"]
minimal = "appgen.bindings.minimal:BINDING"
```

### Next.js binding

`appgen generate <definition> -b nextjs -o <dir>` writes a full-stack
Next.js 16 app: the App Router, TypeScript in strict mode, Tailwind
CSS, and pnpm. The Next.js `app/` folder in the root holds only the
routes. Each route renders a page slice of Feature-Sliced Design in
`src/pages`, and the other FSD layers are in `src/` too. Each layout of
`ui.layouts` with pages is a route group (`app/(app-shell)/`) whose
`layout.tsx` renders the shared layout widget: the sidebar with the
menus, the top bar with the breadcrumbs, the page search, and the color
mode switch. Pages without a layout are in `app/(bare)/`, the pages
that other websites show in a frame (`embed`) are in `app/(embed)/`
without the app shell, and `app/not-found.tsx` shows the 404 page in the
default layout. `next.config.ts` sends `Content-Security-Policy:
frame-ancestors` with the origins of each page with `embed`, and
`'self'` for the other pages. The
actions of a page header are a widget in `src/widgets/page-actions`, and
the actions of a top bar are a part of its layout widget (shared
template `ui/widgets/actions/action-bar.tsx.j2`). An action of a page
with a record (a page with an entity and path parameters) gets the
record of the last path parameter. The
shared UI code imports `@/shared/lib/router`, which the binding writes
with `next/link` and `next/navigation`. Each table, card list, and
board view is a widget in `src/widgets/<view>` from the shared view
templates, and a page with the view as its content shows it. Each
detail view and dashboard is a widget from the shared templates too: a
page with a detail view shows the record of the ID in its path, and a
page with a dashboard shows its widgets. Each form is a feature slice
in `src/features/<form>-form` from the shared form templates: it opens
in a dialog, a sheet, or a page, as the definition says, and checks the
input with the same zod schemas as the server actions. A server error
shows its messages on the fields. The views and the forms
read and change the records with the server actions of the entity
slices. Each element
of a kind that the binding does not cover yet gets an extension file in
`src/gaps/`. The app gets the shadcn/ui components that its UI uses, in
`src/shared/ui/`, and their npm packages. The theme in
`src/app/styles/globals.css` comes from the design tokens, and
next-themes switches the color mode (`ui.theme`). Each entity is a Drizzle
table in `src/shared/db/schema/` (a foreign key column for each
`many_to_one` and `one_to_one` relation, and a join table for each
`many_to_many` relation), with a trace on each table, column, and
relation. A relation and its inverse are stored once. `pnpm db:generate`
writes the SQL migrations with drizzle-kit, and the server applies them
at start when `DATABASE_MIGRATE=true`. The app has a multi-stage
`Dockerfile` (a standalone Next.js server as a non-root user, with the
migrations in `drizzle/`) and a `compose.yaml` with Postgres:
`docker compose up --build` starts both, and the app migrates the
database when it starts. A detail page for an ID that no record has
gives the status 404 and the not-found page. The app has seed records: `pnpm db:seed` (or
`DATABASE_SEED=true` at start) adds the records of the `seed` section
of the definition by ID, and fills an empty database with the mock
records of the shared generator, the same records as in the React app. For a local run without a Postgres server, set
`DATABASE_URL=pglite:./.pglite` to use PGlite, an embedded Postgres
([ADR 0007](docs/adr/0007-local-database.md)).

Each entity slice in `src/entities/` has the same public API as in the
React app, so that the shared UI templates work in both apps: the types,
the field rules (`<entity>Meta`), zod schemas from the field rules
(`<entity>InputSchema`, `<entity>PatchSchema`), and `<entity>Api` with
`list` (filters, search, sorting, and pages), `get`, `create`, `update`,
`remove`, and `subscribe`. In the Next.js app, `<entity>Api` calls the
server actions of the slice (`api/<entity>-actions.ts`), which check
their input with the zod schemas and use the Drizzle repository of the
slice (`server.ts`, only on the server). A server action returns its
errors as data, and `<entity>Api` throws them again as `NotFoundError`
or `ValidationError`. Each custom operation is a features slice with a
server action (`.gen.ts`) that calls the extension file (`.ext.ts`),
where the developer writes the logic. Each webhook is a route handler
`app/<path>/route.ts` that checks the signature of the sender and
records the ID of each event, with a features slice
`src/features/<webhook>-webhook/` whose extension file has the logic.
Custom UI parts (page content,
detail tabs and sections, dashboard widgets, form widgets, form rules,
and actions) get the same generated and extension files as in the React
app, from the shared templates in `gap/` and `appgen.bindings.shared.gaps`.
appgen writes an extension file only once, so a later run keeps its
code. The exact package versions are in
`src/appgen/bindings/nextjs/versions.py`. To try the output:

```sh
uv run appgen generate examples/project-tracker/app.yaml -b nextjs -o /tmp/tracker-next
cd /tmp/tracker-next && pnpm install && pnpm lint && pnpm typecheck && pnpm build
```

`scripts/check-nextjs.sh` runs these steps, `docker build`, and
`appgen check` on the output. The pre-push hook runs it.

### Shared shadcn/ui templates

The Next.js and the React bindings write the same shadcn/ui components.
`src/appgen/bindings/shared/templates/shadcn/` holds one template for
each component, with the FSD import paths of the generated apps
(`@/shared/ui/<name>`, `@/shared/lib/utils`, and `@/shared/lib/theme`,
which each binding writes). `registry.json` lists the npm packages, the
components, and the hooks that each component imports.
`appgen.bindings.shared.shadcn.used_components()` gives the components
that the UI of a definition needs. To update the components, change the
commit or the list in `scripts/vendor_shadcn.py`, and run
`uv run scripts/vendor_shadcn.py`.

`theme/globals.css.j2` writes the theme of Tailwind CSS 4 and shadcn/ui
from the resolved design tokens (`appgen.bindings.shared.theme`). Each
color token, and each token with another value in the dark mode, is a
CSS variable in `:root` and `.dark` (`color.primary_foreground` gives
`--primary-foreground` and `bg-primary-foreground`). The other tokens
are theme variables of Tailwind CSS (`spacing.4` gives `--spacing-4`,
`font_size.sm` gives `--text-sm`), and each typography token gives a
utility (`typography-heading`). `radius.lg` gives `--radius`. A shadcn/ui
variable without a token keeps the shadcn/ui default. Each variable has
a trace to its token. `theme/mode-toggle.tsx.j2` is the switch for the
color mode.

The entity templates are shared too: `src/shared/api/types.ts.j2` (the
`EntityApi` interface and `NotFoundError`), and `model/types.ts.j2`,
`model/meta.ts.j2`, and `model/schema.ts.j2` in `src/entities/entity/`.
They use the template globals of `appgen.bindings.shared.typescript`
(`HELPERS`), which both bindings add. The gap templates in `gap/` and
`appgen.bindings.shared.gaps` (`gap_spec`, `gap_rules()`) give the
generated and the extension files of the custom elements. A binding template with the same
path wins over a shared template.

`ui/` holds the shared UI code: the app shell (layouts, menus,
breadcrumbs, page search, page header, and the 404 page), and the list
views in `ui/views/` (tables, card lists, and boards, with their filters,
actions, states, and value formats), and the forms in `ui/forms/` (with
their widgets and rules). The app shell templates render the
values of `appgen.bindings.shared.ui`, and the view templates render the
`ViewPlan` of each view from `appgen.bindings.shared.views` (the
template global `ui_views`, with the output rules of
`views.view_rules()`). The form templates render the `FormPlan` of each
form from `appgen.bindings.shared.forms` (the template global
`ui_forms`, with the output rules of `forms.form_rules()`). A binding
that generates the forms makes `ViewContext(definition, forms=True)`, so
that the form actions of the views open the forms. With `endpoints` (the
names of the list endpoints of the FastAPI app), the tables and the card
lists send their filters, their sort, and their page to the API
(`ServerPlan`), and load one page.
The detail view templates in `ui/details/`
render a `DetailPlan` from `appgen.bindings.shared.details`: a header
with the title, subtitle, badges, and actions, the sections as cards with
a responsive field grid, and the tabs (sections, a list view of the
related records, or a custom component). The dashboard templates in
`ui/dashboards/` render a `DashboardPlan` from
`appgen.bindings.shared.dashboards`: a responsive grid of stat tiles,
charts (line, bar, and donut with recharts), and lists, which filter and
aggregate the records in the browser. The templates are
client components that import only `@/shared/*`, `@/widgets/*`,
`@/features/*`, and `@/entities/<entity>`. Each binding writes
`@/shared/lib/router` with `Link` (prop `href`), `useNavigate`,
`usePathname`, and `useParams`, so that the same UI code works with the
router of each binding.

### React binding

`appgen generate <definition> -b react -o <dir>` writes a standalone
React 19 app with mock data: TypeScript in strict mode, Vite, React
Router, and pnpm, with the code in the layers of Feature-Sliced Design
(`src/app`, `src/pages`, `src/widgets`, `src/features`,
`src/entities`, and `src/shared`). Each page of the definition gets a
route and a slice in `src/pages`. The binding is in
`src/appgen/bindings/react/`, and `versions.py` there pins the version
of each package.

The UI uses Tailwind CSS and shadcn/ui. The binding takes the shadcn/ui
components from the shared templates (`src/appgen/bindings/shared/`),
and writes into `src/shared/ui` only the components that the UI of the
definition uses, with their npm packages.

Each layout of the definition is an app shell in `src/widgets/layouts`:
a shadcn/ui sidebar with the menu, a top bar with the breadcrumbs, the
page search (Ctrl+K), and the mode toggle, the content region, and a
footer. The router puts each page in its layout (the page layout, else
`ui.defaults.layout`), and unknown paths show a 404 page. A page with
`embed` shows without the app shell, and the nginx configuration of the
Docker image sends `Content-Security-Policy: frame-ancestors` with its
origins, and `'self'` for the other pages. The menu marks
the active route. The breadcrumbs come from the page paths, and a page of
a record shows the display field of the record. The page actions and the
top bar actions are widgets from the shared template
`ui/widgets/actions/action-bar.tsx.j2`, as in the Next.js app. The responsive rules of
the layout change the sidebar mode (expanded, icons, drawer, or hidden),
the widths, the top bar parts, and the content padding on screens
narrower than each breakpoint token.

Each table, card list, and board view is a widget in
`src/widgets/<view>`, and a page with the view as its content shows it.
A view reads all records of its entity, and the related records that its
field paths go through, and filters, sorts, and pages them in the
browser. A table has sortable columns, a row selection with the bulk
actions, and a menu of row actions (shadcn/ui data table with TanStack
Table). A card list shows the card fields in a responsive grid. A board
has one column for each value of its enum field, with the work in
progress limits: a drag and drop, or the "Move to" menu, moves a card and
runs the move operation. The filters are a search box, selects (one or
many values), a switch, and a date range. The enum values show as
badges with the label, the color token, and the icon of their badge set.
The actions open a page, run an operation or a custom action, ask for a
confirmation, and show a toast. Each view shows its loading, empty, and
error states.

A page with a detail view as its content shows the record of the last
path parameter: a header with the title, the subtitle, the badges, and
the actions, then the sections and the tabs, with the lists of related
records. A page with a dashboard as its content shows its stat tiles,
charts (Recharts in the shadcn/ui chart component), and record lists in
the grid of the dashboard. The detail views and dashboards are widgets
from the shared templates, and compute their values from the mock data
in the browser.

Each form is a feature slice in `src/features/<form>-form`, with the
shadcn/ui field components in the sections and the grid of the form. A
form validates its values with the required, length, number, and pattern
rules of its fields, the zod schema of its operation (the entity slice
writes `<Entity>InputSchema` and `<Entity>PatchSchema` in
`model/schema.ts`), the compare rules, and the custom rules. The widgets
are text and number inputs, text areas, selects, radio groups, check
boxes, switches, date and date and time inputs, and relation selects
(one record or many records), and a custom widget is a generation gap.
A form in page mode is the content of its page and reads the record from
the path. The other forms open in a dialog or a sheet from the form
actions of the views. After a save, a form shows its toast, and closes or
resets, or opens its page. A default value can come from a path
parameter of the page (`$route.<param>`).

The theme comes from the design tokens, with the shared template
`theme/globals.css.j2`: one CSS variable for each token, with a light and
a dark value, as shadcn/ui and Tailwind CSS name them. The app switches
between the light, the dark, and the system mode (next-themes, with the
class `dark` on `<html>`), if the definition shows the mode toggle.

The app has a multi-stage `Dockerfile`: pnpm builds the static files,
and nginx serves them as a non-root user on port 8080. nginx sends
unknown paths to `index.html`, so that the client routes work after a
reload:

```sh
docker build -t tracker /tmp/tracker && docker run --rm -p 8080:8080 tracker
```

The app has no back end. Each entity gets a slice in `src/entities`
with its TypeScript type, the labels and rules of its fields, mock
records, and a data access object. The data access keeps the records in
memory, and has the interface of an API client (`EntityApi` in
`src/shared/api`): list (with sort, filters, search, and pages), get,
create, update, and delete. The CRUD and list operations of the
definition call it. The mock records come from a fixed seed, so the
output stays the same, and each relation refers to a record that
exists. A key or a code field comes from the name of the record (for
example the key `MP` for "Meridian Portal"). An entity sets the number of records with the extension key
`x-mock-count` (default: 12). The records of the `seed` section of the
definition come first, with their fixed IDs, and `mock` generated
records follow them ([ADR 0021](docs/adr/0021-seed-data.md)).

Each custom element of the definition is a generation gap (ADR 0005):
custom operations, custom page contents, detail tabs and sections,
dashboard widgets, form widgets, form rules, and actions. For each one,
the binding writes a generated file (`*.gen.ts` or `*.gen.tsx`) with the
typed signature, and an extension file (`*.ext.ts` or `*.ext.tsx`) with
a stub that the app developer replaces. The app builds with the stubs.
`src/appgen/bindings/react/gaps.py` lists the paths. To try the output:

```sh
uv run appgen generate examples/project-tracker/app.yaml -b react -o /tmp/tracker
cd /tmp/tracker && pnpm install && pnpm lint && pnpm typecheck && pnpm build
```

`scripts/check-react.sh` runs these steps, `docker build`, and
`appgen check` on the output. The pre-push hook runs it.

### FastAPI binding

`appgen generate <definition> -b fastapi -o <dir>` writes a standalone
REST API: FastAPI 0.161 on Python 3.14, with uv. Each entity is a
vertical slice in `app/features/<slice>/`, with a SQLAlchemy model,
Pydantic schemas, a repository, and one module for each operation. A
custom operation has a generated endpoint and an extension file for its
logic, and each entity has an extension file for its custom validation.
Each webhook has an endpoint that checks the signature of the sender
and records the ID of each event, and an extension file for its logic.
A webhook with `format: email` reads the inbound emails of Mailgun,
Postmark, or SendGrid. Each third-party API has a typed client. With the
authorization code flow of OAuth 2.0, a user connects an account of the
service, and the client sends the token of the user ([ADR
0033](docs/adr/0033-api-connections.md)). The Next.js app has the same
flow, and the front ends show the page `/connections`, where a user
connects and disconnects the accounts.
Each operation has generated API tests that run against Postgres in a
container, or against SQLite. Errors use the problem details format (RFC 9457). An Alembic
migration creates the schema in Postgres. `uv run python -m app.cli
seed` (or `DATABASE_SEED=true` at start) adds the seed records by ID,
and fills an empty database with the mock records of the shared
generator, the same records as in the Next.js and React apps. A
Dockerfile and a Compose file run the API with Postgres and the seed
records. For a local run without a Postgres
server, set `DATABASE_URL=sqlite+aiosqlite:///./local.db` ([ADR
0007](docs/adr/0007-local-database.md)). Pages and the UI are out of the scope of
the binding. The binding is in `src/appgen/bindings/fastapi/`, and [ADR
0006](docs/adr/0006-fastapi-binding.md) describes its design. To try the
output:

```sh
uv run appgen generate examples/project-tracker/app.yaml -b fastapi -o /tmp/tracker-api
cd /tmp/tracker-api && uv sync && uv run ruff check && uv run pyright && uv run pytest
```

`scripts/check-fastapi.sh` runs these steps, `docker build`, and
`appgen check` on the output. The pre-push hook runs it.

## Traces

[ADR 0004](docs/adr/0004-trace-format.md) defines the trace format. The
scanner (`appgen.trace.scan_folder`) finds the traces in a code folder
with a text scan. It skips the paths in `.gitignore` files and in an
ignore list (by default `node_modules/`, `.venv/`, `.git/`, and other
tool folders). It reports each malformed trace with its file, line, and
column.

The coverage (`appgen.trace.compute_coverage`) gives the status of each
definition element: an open gap (a `gap` trace), covered (a
`generated` or a `manual` trace, and no `gap` trace), or uncovered (no
trace). It gives the
coverage as a percentage, in total and for each element kind. A list of
excluded kinds removes elements and the elements under them from the
coverage, for example `ui` for an app without a front end.

The validity check (`appgen.trace.find_invalid_traces`) lists the
malformed traces, and the traces to element IDs that the definition
does not have, with a "did you mean" hint where possible. With the list
of generated files, it also lists `generated` traces in other files.

`appgen check <definition> <code-folder>` runs the scanner and both
reports. `--format text` (the default) prints a report for people, and
`--format json` prints a stable JSON document (`"version": 1`). The
exit code is 0 if the check passes, and 1 if there is an invalid trace
or if the coverage is lower than `--min-coverage <percent>`. It is 2
if the definition is not valid. `--exclude-kind <kind>` and
`--ignore <pattern>` take more than one value if you repeat them.

If the code folder has an output manifest (`.appgen/manifest.json`),
the check reads the list of generated files and the traces of the files
without comments (for example JSON files) from it. Then a `generated`
trace in a file that appgen did not write is an invalid trace. The
pre-push hook runs the check on the output of the test binding.

When the definition changes, a new run regenerates the generated files
and keeps the extension files. A trace in hand-written code to an element
that the change renames or removes is then an invalid trace, so
`appgen check` shows the drift until the developer updates the code.
`appgen orphans <definition> <code-folder>` lists the extension files
whose element does not exist any more, with the element that most
likely replaces it.
`tests/test_definition_change.py` proves this for each binding: it adds a
field, renames an entity, and removes a page in a copy of the example.
