"""The `appgen` command line interface."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from appgen import __version__
from appgen.dsl import Diagnostic, check_file
from appgen.dsl.schema import json_schema_text


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


app = typer.Typer(
    name="appgen",
    help="Generate application code from a declarative YAML app definition.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"appgen {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Generate application code from a declarative YAML app definition."""


@app.command()
def schema(
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the schema to this file, not to stdout."),
    ] = None,
) -> None:
    """Write the JSON Schema of the app definition DSL."""
    text = json_schema_text()
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")


@app.command()
def validate(
    file: Annotated[Path, typer.Argument(help="The app definition file (YAML).")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="The output format."),
    ] = OutputFormat.TEXT,
) -> None:
    """Validate an app definition. The exit code is 0 if it is valid, else 1."""
    _, diagnostics = check_file(file)
    if output_format is OutputFormat.JSON:
        report = {
            "file": str(file),
            "valid": not diagnostics,
            "diagnostics": [_diagnostic_json(d) for d in diagnostics],
        }
        typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic))
        count = len(diagnostics)
        if count:
            typer.echo(f"{file}: {count} error{'s' if count > 1 else ''}.")
        else:
            typer.echo(f"{file}: valid.")
    if diagnostics:
        raise typer.Exit(code=1)


def _diagnostic_json(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "file": diagnostic.location.file,
        "line": diagnostic.location.line,
        "column": diagnostic.location.column,
        "element_id": diagnostic.element_id,
        "hint": diagnostic.hint,
    }
