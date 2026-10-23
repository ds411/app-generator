"""Checks across the elements of an app definition: names, references, and field options.

The loader checks the structure of each element. The checks in this module
need more than one element, for example a relation and its target entity.
Each check is a function that yields diagnostics. `CHECKS` lists them, so
that later parts of the DSL can add their own checks.
"""

import datetime
import difflib
import re
import uuid
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from appgen.dsl.diagnostics import DefinitionError, Diagnostic, Location
from appgen.dsl.loader import load_definition
from appgen.dsl.model import AppDefinition, Element, Field
from appgen.dsl.ui.checks import (
    check_ui_dashboards,
    check_ui_forms,
    check_ui_references,
    check_ui_states,
    check_ui_tokens,
    check_ui_views,
)

type Check = Callable[[AppDefinition], Iterator[Diagnostic]]

STRING_TYPES = frozenset({"string", "text", "email", "url"})
NUMBER_TYPES = frozenset({"integer", "decimal"})
SINGLE_KINDS = frozenset({"many_to_one", "one_to_one"})
INVERSE_KINDS = {
    "many_to_one": "one_to_many",
    "one_to_many": "many_to_one",
    "one_to_one": "one_to_one",
    "many_to_many": "many_to_many",
}
CUSTOM_ONLY_KEYS = ("params", "returns")


def validate_definition(definition: AppDefinition) -> list[Diagnostic]:
    """Run all checks on a loaded definition. Return all diagnostics, in source order."""
    diagnostics = [diagnostic for check in CHECKS for diagnostic in check(definition)]
    return sorted(diagnostics, key=lambda d: d.location)


def check_file(path: Path | str) -> tuple[AppDefinition | None, list[Diagnostic]]:
    """Load and validate a definition file.

    Return the definition (None if it does not load) and all diagnostics.
    """
    try:
        definition = load_definition(path)
    except DefinitionError as error:
        return None, error.diagnostics
    return definition, validate_definition(definition)


def check_names(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Names must be unique in their scope, also without regard to case."""
    yield from _unique_names(definition.entities.values(), "entity")
    yield from _unique_names(definition.operations.values(), "operation")
    yield from _unique_names(definition.pages.values(), "page")
    for entity in definition.entities.values():
        members = [*entity.fields.values(), *entity.relations.values()]
        yield from _unique_names(members, "field or relation")
        for member in members:
            if _name(member) == "id":
                yield _error(
                    "reserved-name",
                    "The name 'id' is reserved for the primary key of each entity.",
                    member,
                    hint="Use another name. Each entity has an implicit 'id' field.",
                )
        for name, relation in entity.relations.items():
            column = f"{name}_id"
            if relation.kind in SINGLE_KINDS and column in entity.fields:
                yield _error(
                    "duplicate-name",
                    f"The field '{column}' has the same name as the foreign key of "
                    f"the relation '{name}'.",
                    entity.fields[column],
                    hint="Rename the field or the relation.",
                )
    paths: dict[str, Element] = {}
    for page in definition.pages.values():
        first = paths.setdefault(page.path, page)
        if first is not page:
            yield _error(
                "duplicate-path",
                f"The path '{page.path}' is also the path of '{first.id}'.",
                page,
                at="path",
            )


def check_references(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Each reference to an entity, a field, or a relation must resolve."""
    entities = definition.entities
    for entity in entities.values():
        if entity.display_field is not None and entity.display_field not in entity.fields:
            yield _missing(entity, "display_field", "field", entity.display_field, entity.fields)
        for relation in entity.relations.values():
            if relation.target not in entities:
                yield _missing(relation, "target", "entity", relation.target, entities)
    for operation in definition.operations.values():
        if operation.entity not in entities:
            yield _missing(operation, "entity", "entity", operation.entity, entities)
        if operation.returns != "none" and operation.returns not in entities:
            yield _missing(operation, "returns", "entity", operation.returns, [*entities, "none"])
    for page in definition.pages.values():
        if page.entity is not None and page.entity not in entities:
            yield _missing(page, "entity", "entity", page.entity, entities)


def check_relations(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Relation options must fit the kind, and the inverse must be the other side."""
    for entity_name, entity in definition.entities.items():
        for name, relation in entity.relations.items():
            if relation.kind not in SINGLE_KINDS:
                for key in ("required", "on_delete"):
                    if key in relation.model_fields_set:
                        yield _error(
                            "invalid-option",
                            f"'{key}' is only for 'many_to_one' and 'one_to_one' relations.",
                            relation,
                            at=key,
                        )
            if relation.required and relation.on_delete == "set_null":
                yield _error(
                    "invalid-option",
                    "A required relation cannot use 'on_delete: set_null'.",
                    relation,
                    at="on_delete",
                    hint="Use 'cascade' or 'restrict', or remove 'required'.",
                )
            target = definition.entities.get(relation.target)
            if target is None:
                continue
            if relation.inverse is None:
                if relation.kind == "one_to_many":
                    yield _error(
                        "missing-inverse",
                        "A 'one_to_many' relation needs an 'inverse': the 'many_to_one' "
                        f"relation on '{relation.target}' that holds the foreign key.",
                        relation,
                        hint=f"Add a 'many_to_one' relation to '{entity_name}' on "
                        f"'{relation.target}', and name it in 'inverse'.",
                    )
                continue
            inverse = target.relations.get(relation.inverse)
            if inverse is None:
                yield _missing(relation, "inverse", "relation", relation.inverse, target.relations)
                continue
            if inverse.target not in definition.entities:
                # check_references reports the target of the inverse.
                continue
            expected_kind = INVERSE_KINDS[relation.kind]
            if inverse.target != entity_name or inverse.kind != expected_kind:
                yield _error(
                    "invalid-inverse",
                    f"The inverse '{relation.target}.{relation.inverse}' must be a "
                    f"'{expected_kind}' relation to '{entity_name}'.",
                    relation,
                    at="inverse",
                )
            elif inverse.inverse not in (None, name) and inverse.inverse in entity.relations:
                yield _error(
                    "invalid-inverse",
                    f"The inverse '{relation.target}.{relation.inverse}' names "
                    f"'{inverse.inverse}' as its inverse, not '{name}'.",
                    relation,
                    at="inverse",
                )


def check_operations(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Only custom operations have params and a return type."""
    for operation in definition.operations.values():
        if operation.kind == "custom":
            continue
        for key in CUSTOM_ONLY_KEYS:
            if key in operation.model_fields_set:
                yield _error(
                    "invalid-option",
                    f"'{key}' is only for 'custom' operations.",
                    operation,
                    at=key,
                )


def check_fields(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The options of each field must fit its type."""
    for entity in definition.entities.values():
        for field in entity.fields.values():
            yield from _check_field(field)
    for operation in definition.operations.values():
        for param in operation.params.values():
            yield from _check_field(param)
            if param.unique:
                yield _error(
                    "invalid-option", "'unique' is only for entity fields.", param, at="unique"
                )


CHECKS: list[Check] = [
    check_names,
    check_references,
    check_relations,
    check_operations,
    check_fields,
    check_ui_tokens,
    check_ui_views,
    check_ui_forms,
    check_ui_dashboards,
    check_ui_states,
    check_ui_references,
]
"""The checks that `validate_definition` runs, in order."""


def _check_field(field: Field) -> Iterator[Diagnostic]:
    allowed = {
        "min_length": STRING_TYPES,
        "max_length": STRING_TYPES,
        "pattern": {"string"},
        "min": NUMBER_TYPES,
        "max": NUMBER_TYPES,
        "precision": {"decimal"},
        "scale": {"decimal"},
        "values": {"enum"},
    }
    for key, types in allowed.items():
        if key in field.model_fields_set and field.type not in types:
            names = ", ".join(f"'{name}'" for name in sorted(types))
            yield _error(
                "invalid-option",
                f"'{key}' is not an option of the type '{field.type}'. It is for {names}.",
                field,
                at=key,
            )
    if field.type == "enum":
        if not field.values:
            yield _error(
                "missing-key",
                "An 'enum' field needs 'values': a list of one or more names.",
                field,
                hint="Add for example 'values: [open, done]'.",
            )
        elif len(set(field.values)) != len(field.values):
            yield _error("duplicate-name", "The enum values must be unique.", field, at="values")
    for low, high in (("min_length", "max_length"), ("min", "max"), ("scale", "precision")):
        low_value, high_value = getattr(field, low), getattr(field, high)
        if low_value is not None and high_value is not None and low_value > high_value:
            yield _error(
                "invalid-option", f"'{low}' must not be greater than '{high}'.", field, at=low
            )
    if field.pattern is not None and field.type == "string":
        try:
            re.compile(field.pattern)
        except re.error as error:
            yield _error(
                "invalid-value",
                f"The pattern is not a valid regular expression: {error}.",
                field,
                at="pattern",
            )
    if field.default is not None and not _default_fits(field):
        yield _error(
            "invalid-value",
            f"The default {field.default!r} is not a valid '{field.type}' value.",
            field,
            at="default",
            hint=f"Use one of {field.values}." if field.type == "enum" else None,
        )


def _default_fits(field: Field) -> bool:
    value = field.default
    match field.type:
        case "string" | "text" | "email" | "url":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "decimal":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "enum":
            return isinstance(value, str) and value in (field.values or [])
        case "date":
            return isinstance(value, str) and _parses(datetime.date.fromisoformat, value)
        case "datetime":
            return isinstance(value, str) and _parses(datetime.datetime.fromisoformat, value)
        case "uuid":
            return isinstance(value, str) and _parses(uuid.UUID, value)
        case "json":
            return True


def _parses(parse: Callable[[str], object], value: str) -> bool:
    try:
        parse(value)
    except ValueError:
        return False
    return True


def _unique_names(elements: Iterable[Element], what: str) -> Iterator[Diagnostic]:
    seen: dict[str, Element] = {}
    for element in elements:
        first = seen.setdefault(_name(element).lower(), element)
        if first is not element:
            yield _error(
                "duplicate-name",
                f"The {what} name '{_name(element)}' differs only in case from '{_name(first)}'.",
                element,
                hint=f"The other {what} is at {first.location}.",
            )


def _name(element: Element) -> str:
    return element.id.rpartition(".")[2]


def _missing(
    element: Element, key: str, what: str, name: str, choices: Iterable[str]
) -> Diagnostic:
    matches = difflib.get_close_matches(name, list(choices), n=1)
    return _error(
        "unknown-reference",
        f"The {what} '{name}' does not exist.",
        element,
        at=key,
        hint=f"Did you mean '{matches[0]}'?" if matches else None,
    )


def _error(
    code: str, message: str, element: Element, *, at: str | None = None, hint: str | None = None
) -> Diagnostic:
    location = element.location_of(at) if at else element.location
    return Diagnostic(
        code=code,
        message=message,
        location=location or Location("<unknown>", 1, 1),
        element_id=element.id or None,
        hint=hint,
    )
