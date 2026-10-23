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
from appgen.dsl.validator import check_file, validate_definition

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
    "check_file",
    "load_definition",
    "load_definition_text",
    "validate_definition",
]
