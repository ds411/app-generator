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

## Commands

| Task                   | Command                    |
| ---------------------- | -------------------------- |
| Show the CLI help      | `uv run appgen --help`     |
| Lint                   | `uv run ruff check`        |
| Check the formatting   | `uv run ruff format --check` |
| Format the code        | `uv run ruff format`       |
| Type check             | `uv run pyright`           |
| Test                   | `uv run pytest`            |

## Layout

| Path          | Content                          |
| ------------- | -------------------------------- |
| `src/appgen/` | The generator and the CLI.       |
| `tests/`      | The tests.                       |
