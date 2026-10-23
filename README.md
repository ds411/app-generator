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
| `src/appgen/bindings/` | The bindings. `minimal` is the test binding of the core.    |
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
