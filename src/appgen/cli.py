"""The `appgen` command line interface."""

from pathlib import Path
from typing import Annotated

import typer

from appgen import __version__
from appgen.dsl.schema import json_schema_text

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
