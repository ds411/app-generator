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

| Task                 | Command                                             |
| -------------------- | --------------------------------------------------- |
| Show the CLI help    | `uv run appgen --help`                              |
| Lint                 | `uv run ruff check`                                 |
| Check the formatting | `uv run ruff format --check`                        |
| Format the code      | `uv run ruff format`                                |
| Type check           | `uv run pyright`                                    |
| Test                 | `uv run pytest`                                     |
| Run all hook checks  | `APPGEN_CHECK_ALL=1 .githooks/pre-push < /dev/null` |

## Layout

| Path              | Content                                                    |
| ----------------- | ---------------------------------------------------------- |
| `src/appgen/`     | The generator and the CLI.                                 |
| `src/appgen/dsl/` | The app definition DSL: the model, the loader, and checks. |
| `tests/`          | The tests.                                                 |
| `docs/adr/`       | The architecture decision records.                         |
| `.githooks/`      | The git hooks (pre-push checks).                           |

[ADR 0002](docs/adr/0002-app-definition-dsl-v0.md) describes the DSL.
