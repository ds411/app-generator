"""Diagnostics: the errors that the loader and the validator report."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Location:
    """A position in a source file. The line and the column start at 1."""

    file: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One error in an app definition."""

    code: str
    """A short, stable name for the kind of error, for example `unknown-key`."""
    message: str
    location: Location
    element_id: str | None = None
    """The ID of the definition element that has the error, if known."""
    hint: str | None = None
    """A suggestion for the fix, if there is one."""

    def __str__(self) -> str:
        text = f"{self.location}: error[{self.code}]: {self.message}"
        if self.element_id:
            text += f" (in {self.element_id})"
        if self.hint:
            text += f"\n  hint: {self.hint}"
        return text


class DefinitionError(Exception):
    """An app definition is not valid. The diagnostics give the reasons."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("\n".join(str(d) for d in diagnostics))
        self.diagnostics = diagnostics
