"""Checks of the UI part of an app definition (ADR 0003).

The validator runs these checks after the checks of the data part.
"""

from collections.abc import Iterator

from appgen.dsl.diagnostics import Diagnostic
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.tokens import check_tokens


def check_ui_tokens(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The design tokens must have valid names, types, values, and references."""
    if definition.ui is not None:
        yield from check_tokens(definition.ui.tokens)
