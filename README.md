# app-generator

A proof of concept for an application code generator. A YAML DSL
defines an application. The generator uses Jinja2 templates to write
the code for a binding (a target stack). Traces in the generated code
refer back to the app definition. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the plan and the rules.

## Setup

Install [uv](https://docs.astral.sh/uv/). Then run this command in the
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
| Generate an app       | `uv run appgen generate <definition> -b <binding> -o <dir>`  |
| Lint                  | `uv run ruff check`                                        |
| Check the formatting  | `uv run ruff format --check`                               |
| Format the code       | `uv run ruff format`                                       |
| Type check            | `uv run pyright`                                           |
| Test                  | `uv run pytest`                                            |
| Run all hook checks   | `APPGEN_CHECK_ALL=1 .githooks/pre-push < /dev/null`        |
| Update golden files   | `APPGEN_UPDATE_GOLDEN=1 uv run pytest`                     |
| Update the schema     | `uv run appgen schema --out schema/app.schema.json`        |

## Layout

| Path                   | Content                                                     |
| ---------------------- | ----------------------------------------------------------- |
| `src/appgen/`          | The generator and the CLI.                                  |
| `src/appgen/dsl/`      | The app definition DSL: the model, the loader, and checks.  |
| `src/appgen/dsl/ui/`   | The UI part of the DSL: design tokens and UI elements.      |
| `src/appgen/gen/`      | The generator core: the binding contract and the rendering. |
| `src/appgen/bindings/` | The bindings. `minimal` is the test binding of the core, `nextjs` writes a Next.js 16 app, `react` writes a React 19 app, and `fastapi` writes a FastAPI REST API. |
| `src/appgen/trace/`    | The trace scanner and the trace checker (ADR 0004).         |
| `schema/`              | The JSON Schema of the DSL, for editors.                    |
| `tests/`               | The tests.                                                  |
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
files written and deleted, and the gaps created. If the definition is
not valid, it writes no file and the exit code is 1. `--force`
overwrites generated files that have manual edits.

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
`src/pages`, and the other FSD layers are in `src/` too. Each element
of a kind that the binding does not cover yet gets an extension file in
`src/gaps/`. The app gets the shadcn/ui components that its UI uses, in
`src/shared/ui/`, and their npm packages. The theme in
`src/app/styles/globals.css` comes from the design tokens, and
next-themes switches the color mode (`ui.theme`). Each entity is a Drizzle
table in `src/shared/db/schema/` (a foreign key column for each
`many_to_one` and `one_to_one` relation, and a join table for each
`many_to_many` relation), with a trace on each table, column, and
relation. `pnpm db:generate` writes the SQL migrations with drizzle-kit,
and the server applies them at start when `DATABASE_MIGRATE=true`. The exact package versions are in
`src/appgen/bindings/nextjs/versions.py`. To try the output:

```sh
uv run appgen generate examples/project-tracker/app.yaml -b nextjs -o /tmp/tracker-next
cd /tmp/tracker-next && pnpm install && pnpm lint && pnpm typecheck && pnpm build
```

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
exists. An entity sets the number of records with the extension key
`x-mock-count` (default: 12).

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

### FastAPI binding

`appgen generate <definition> -b fastapi -o <dir>` writes a standalone
REST API: FastAPI 0.161 on Python 3.14, with uv. Each entity is a
vertical slice in `app/features/<slice>/`, with a SQLAlchemy model,
Pydantic schemas, a repository, and one module for each operation. A
custom operation has a generated endpoint and an extension file for its
logic. Errors use the problem details format (RFC 9457). An Alembic
migration creates the schema in Postgres. Pages and the UI are out of
the scope of the binding. The binding is in
`src/appgen/bindings/fastapi/`, and
[ADR 0006](docs/adr/0006-fastapi-binding.md) describes its design. To
try the output:

```sh
uv run appgen generate examples/project-tracker/app.yaml -b fastapi -o /tmp/tracker-api
cd /tmp/tracker-api && uv sync && uv run ruff check && uv run pyright && uv run pytest
```

## Traces

[ADR 0004](docs/adr/0004-trace-format.md) defines the trace format. The
scanner (`appgen.trace.scan_folder`) finds the traces in a code folder
with a text scan. It skips the paths in `.gitignore` files and in an
ignore list (by default `node_modules/`, `.venv/`, `.git/`, and other
tool folders). It reports each malformed trace with its file, line, and
column.

The coverage (`appgen.trace.compute_coverage`) gives the status of each
definition element: covered (a `generated` or a `manual` trace), an
open gap (only `gap` traces), or uncovered (no trace). It gives the
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
