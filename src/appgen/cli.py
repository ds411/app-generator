"""The `appgen` command line interface."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from appgen import __version__
from appgen.dsl import Diagnostic, check_file
from appgen.dsl.schema import json_schema_text
from appgen.trace import DEFAULT_IGNORE, check_traces, render


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


@app.command()
def check(
    definition_file: Annotated[Path, typer.Argument(help="The app definition file (YAML).")],
    code_folder: Annotated[
        Path,
        typer.Argument(help="The folder of the app code.", file_okay=False, exists=True),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="The output format."),
    ] = OutputFormat.TEXT,
    min_coverage: Annotated[
        float | None,
        typer.Option(
            "--min-coverage",
            min=0,
            max=100,
            help="Fail if the coverage in percent is lower than this value.",
        ),
    ] = None,
    exclude_kinds: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-kind",
            help="Do not count the elements of this kind, and the elements under them, "
            "in the coverage, for example 'ui'. Repeat the option for more kinds.",
        ),
    ] = None,
    ignore: Annotated[
        list[str] | None,
        typer.Option(
            "--ignore",
            help="Also skip the paths that match this pattern (gitignore syntax). "
            "Repeat the option for more patterns.",
        ),
    ] = None,
    use_gitignore: Annotated[
        bool,
        typer.Option("--gitignore/--no-gitignore", help="Skip the paths in .gitignore files."),
    ] = True,
) -> None:
    """Check the traces in a code folder against an app definition.

    The report lists the invalid traces, the uncovered elements, and the
    open gaps, and gives the coverage. The exit code is 0 if the check
    passes, 1 if there is an invalid trace or the coverage is too low,
    and 2 if the definition is not valid.
    """
    definition, diagnostics = check_file(definition_file)
    if definition is None or diagnostics:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic), err=True)
        typer.echo(f"{definition_file}: the app definition is not valid.", err=True)
        raise typer.Exit(code=2)
    report = check_traces(
        definition,
        code_folder,
        ignore=[*DEFAULT_IGNORE, *(ignore or [])],
        use_gitignore=use_gitignore,
        exclude_kinds=exclude_kinds or [],
        min_coverage=min_coverage,
    )
    typer.echo(render(report, "json" if output_format is OutputFormat.JSON else "text"), nl=False)
    raise typer.Exit(code=report.exit_code)


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
