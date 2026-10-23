"""The app definition DSL: the model, the loader, and the diagnostics."""

from appgen.dsl.diagnostics import DefinitionError, Diagnostic, Location
from appgen.dsl.loader import load_definition, load_definition_text
from appgen.dsl.model import (
    App,
    AppDefinition,
    Element,
    Entity,
    Field,
    Operation,
    Page,
    Relation,
)

__all__ = [
    "App",
    "AppDefinition",
    "DefinitionError",
    "Diagnostic",
    "Element",
    "Entity",
    "Field",
    "Location",
    "Operation",
    "Page",
    "Relation",
    "load_definition",
    "load_definition_text",
]
