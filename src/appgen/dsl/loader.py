"""Load a YAML app definition into the typed model."""

import difflib
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, TypeAliasType, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from appgen.dsl.diagnostics import DefinitionError, Diagnostic
from appgen.dsl.model import AppDefinition, Element
from appgen.dsl.source import DataPath, SourceMap, YamlDocument, read_yaml, read_yaml_file

_TYPE_MESSAGES = {
    "dict_type": "Expected a mapping.",
    "model_type": "Expected a mapping.",
    "model_attributes_type": "Expected a mapping.",
    "list_type": "Expected a list.",
    "string_type": "Expected a string.",
    "bool_type": "Expected true or false.",
    "int_type": "Expected an integer.",
    "float_type": "Expected a number.",
    "too_short": "Expected one or more items.",
}


def load_definition(path: Path | str) -> AppDefinition:
    """Load an app definition file. Raise DefinitionError if it is not valid."""
    return _load(read_yaml_file(Path(path)))


def load_definition_text(text: str, file: str = "<string>") -> AppDefinition:
    """Load an app definition from YAML text. Raise DefinitionError if it is not valid."""
    return _load(read_yaml(text, file))


def _load(document: YamlDocument) -> AppDefinition:
    source_map = document.source_map
    if document.data is None:
        raise DefinitionError(
            [
                Diagnostic(
                    code="empty-definition",
                    message="The definition is empty.",
                    location=source_map.root,
                )
            ]
        )
    try:
        definition = AppDefinition.model_validate(document.data)
    except ValidationError as error:
        diagnostics = [_diagnostic(detail, source_map) for detail in error.errors()]
        raise DefinitionError(_unique(diagnostics)) from None
    for path, element in walk_elements(definition):
        element._location = source_map.element(path)  # pyright: ignore[reportPrivateUsage]
    return definition


def walk_elements(element: Element, path: DataPath = ()) -> Iterator[tuple[DataPath, Element]]:
    """Yield each element of the tree under an element, with its path, in source order."""
    yield path, element
    for name in type(element).model_fields:
        value = getattr(element, name)
        if isinstance(value, Element):
            yield from walk_elements(value, (*path, name))
        elif isinstance(value, dict):
            for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
                if isinstance(item, Element):
                    yield from walk_elements(item, (*path, name, str(key)))  # pyright: ignore[reportUnknownArgumentType]


def _diagnostic(detail: ErrorDetails, source_map: SourceMap) -> Diagnostic:
    kind = detail["type"]
    path, is_key = _data_path(detail["loc"])
    if kind == "missing":
        parent = path[:-1]
        return Diagnostic(
            code="missing-key",
            message=f"The key '{path[-1]}' is missing.",
            location=source_map.element(parent) if parent else source_map.root,
        )
    if kind == "extra_forbidden":
        return Diagnostic(
            code="unknown-key",
            message=f"The key '{path[-1]}' is not known here.",
            location=source_map.element(path),
            hint=_did_you_mean(str(path[-1]), _known_keys(path[:-1])),
        )
    location = source_map.element(path) if is_key else source_map.value(path)
    value = detail["input"]
    if kind == "literal_error":
        expected = detail.get("ctx", {}).get("expected", "")
        return Diagnostic(
            code="invalid-value",
            message=f"The value {value!r} is not valid. Expected {expected}.",
            location=location,
            hint=_did_you_mean(str(value), _literal_choices(expected)),
        )
    if kind == "string_pattern_mismatch":
        pattern = detail.get("ctx", {}).get("pattern", "")
        what = "name" if is_key else "value"
        return Diagnostic(
            code="invalid-name" if is_key else "invalid-value",
            message=f"The {what} {value!r} does not match the pattern {pattern}.",
            location=location,
        )
    return Diagnostic(
        code="invalid-value",
        message=_TYPE_MESSAGES.get(kind, detail["msg"] + "."),
        location=location,
    )


def _data_path(loc: tuple[int | str, ...]) -> tuple[DataPath, bool]:
    """Convert a Pydantic error location to a data path.

    Pydantic adds "[key]" for an error in a dict key, and a tag for each
    member of a union or a function validator. Return the path without
    them, and true if the error is in a dict key.
    """
    path: list[str | int] = []
    is_key = False
    for part in loc:
        if part == "[key]":
            is_key = True
        elif isinstance(part, int) or not part.startswith(("function-", "constrained-")):
            path.append(part)
    return tuple(path), is_key


def _known_keys(path: DataPath) -> list[str]:
    """Return the keys that the model permits for the mapping at a path."""
    model: type[BaseModel] = AppDefinition
    parts = iter(path)
    for part in parts:
        info = model.model_fields.get(str(part))
        child = _child_model(info.annotation) if info else None
        if child is None:
            return []
        if _is_mapping(info.annotation if info else None):
            # Skip the key of the mapping, for example the entity name.
            next(parts, None)
        model = child
    return list(model.model_fields)


def _unwrap(annotation: object) -> object:
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if get_origin(annotation) is Annotated:
        return _unwrap(get_args(annotation)[0])
    return annotation


def _is_mapping(annotation: object) -> bool:
    return get_origin(_unwrap(annotation)) is dict


def _child_model(annotation: object) -> type[BaseModel] | None:
    annotation = _unwrap(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        found = _child_model(arg)
        if found is not None:
            return found
    return None


def _literal_choices(expected: str) -> list[str]:
    return [part.strip(" '") for part in expected.replace(" or ", ",").split(",") if part.strip()]


def _did_you_mean(value: str, choices: list[str]) -> str | None:
    matches = difflib.get_close_matches(value, choices, n=1)
    return f"Did you mean '{matches[0]}'?" if matches else None


def _unique(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    seen: set[tuple[str, str]] = set()
    result: list[Diagnostic] = []
    for diagnostic in sorted(diagnostics, key=lambda d: d.location):
        key = (str(diagnostic.location), diagnostic.code)
        if key not in seen:
            seen.add(key)
            result.append(diagnostic)
    return result
