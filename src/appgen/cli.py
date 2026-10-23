"""The `appgen` command line interface."""

from typing import Annotated

import typer

from appgen import __version__

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
