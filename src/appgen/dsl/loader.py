"""Load a YAML app definition into the typed model."""

import difflib
from collections import defaultdict
from pathlib import Path
from typing import Annotated, TypeAliasType, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from appgen.dsl.apis import expand_operations
from appgen.dsl.crud import expand_crud
from appgen.dsl.diagnostics import DefinitionError, Diagnostic, Location
from appgen.dsl.ids import element_id, index_elements, walk_elements
from appgen.dsl.model import DSL_VERSION, RESERVED_SECTIONS, AppDefinition, is_extension_key
from appgen.dsl.seed import read_seed_files
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
_STRING_ERRORS = frozenset({"string_type", "literal_error", "string_pattern_mismatch"})
"""The errors of a value that must be a string."""


def load_definition(path: Path | str) -> AppDefinition:
    """Load an app definition file. Raise DefinitionError if it is not valid.

    The loader reads the OpenAPI documents of the `apis` and the data files
    of the `seed` from the folder of the file. The validator reports a
    document that is not valid. A data file that is not valid is an error
    of the loader.
    """
    path = Path(path)
    return _load(read_yaml_file(path), path.parent)


def load_definition_text(
    text: str, file: str = "<string>", base_dir: Path | None = None
) -> AppDefinition:
    """Load an app definition from YAML text. Raise DefinitionError if it is not valid.

    The loader reads the OpenAPI documents of the `apis` and the data files
    of the `seed` from `base_dir`, by default the folder of `file`.
    """
    return _load(read_yaml(text, file), base_dir or Path(file).parent)


def _load(document: YamlDocument, base_dir: Path) -> AppDefinition:
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
    data = document.data
    diagnostics: list[Diagnostic] = []
    if isinstance(data, dict):
        sections = cast(dict[str, object], data)
        diagnostics = [
            _not_supported(section, source_map)
            for section in sections
            if section in RESERVED_SECTIONS
        ]
        data = {k: v for k, v in sections.items() if k not in RESERVED_SECTIONS}
    data = expand_crud(data, source_map)
    diagnostics += expand_operations(data, source_map)
    seed_diagnostics, seed_hashes = read_seed_files(data, source_map, base_dir)
    diagnostics += seed_diagnostics
    definition: AppDefinition | None = None
    try:
        definition = AppDefinition.model_validate(data)
    except ValidationError as error:
        diagnostics += [_diagnostic(detail, source_map) for detail in error.errors()]
    if definition is None or diagnostics:
        raise DefinitionError(_unique(diagnostics))
    value_locations: dict[DataPath, dict[str, Location]] = defaultdict(dict[str, Location])
    for key, location in source_map.values.items():
        if key:
            value_locations[key[:-1]][str(key[-1])] = location
    for path, element in walk_elements(definition):
        element._location = source_map.element(path)  # pyright: ignore[reportPrivateUsage]
        element._value_locations = value_locations.get(path, {})  # pyright: ignore[reportPrivateUsage]
    definition._index = index_elements(definition)  # pyright: ignore[reportPrivateUsage]
    for api in definition.apis.values():
        api.read_document(base_dir)
    for name, seed in definition.seed.items():
        seed._file_hash = seed_hashes.get(name)  # pyright: ignore[reportPrivateUsage]
    return definition


def _not_supported(section: str, source_map: SourceMap) -> Diagnostic:
    return Diagnostic(
        code="not-supported",
        message=f"The section '{section}' is not supported in this version of the DSL.",
        location=source_map.element((section,)),
        hint="A later version of the DSL adds this section. Remove it, or keep "
        f"its data in an extension key, for example 'x-{section}'.",
    )


def _diagnostic(detail: ErrorDetails, source_map: SourceMap) -> Diagnostic:
    kind = detail["type"]
    path, is_key = _data_path(detail["loc"])
    element = _element_id(path)
    if path == ("version",):
        return _version_diagnostic(detail, source_map)
    if kind == "missing":
        parent = path[:-1]
        return Diagnostic(
            code="missing-key",
            message=f"The key '{path[-1]}' is missing.",
            location=source_map.element(parent) if parent else source_map.root,
            element_id=element,
        )
    if kind == "extra_forbidden":
        return Diagnostic(
            code="unknown-key",
            message=f"The key '{path[-1]}' is not known here.",
            location=source_map.element(path),
            hint=_did_you_mean(str(path[-1]), _known_keys(path[:-1])),
            element_id=element,
        )
    location = source_map.element(path) if is_key else source_map.value(path)
    value = detail["input"]
    if isinstance(value, bool) and kind in _STRING_ERRORS and path in source_map.booleans:
        text = source_map.booleans[path]
        return Diagnostic(
            code="invalid-value",
            message=f"YAML reads '{text}' as a boolean ({str(value).lower()}), "
            "but a string must be here.",
            location=location,
            hint=f'Put the value in quotes: "{text}".',
            element_id=element,
        )
    if kind == "literal_error":
        expected = detail.get("ctx", {}).get("expected", "")
        return Diagnostic(
            code="invalid-value",
            message=f"The value {value!r} is not valid. Expected {expected}.",
            location=location,
            hint=_did_you_mean(str(value), _literal_choices(expected)),
            element_id=element,
        )
    if kind == "union_tag_invalid":
        # A union that the `kind` key selects (see `appgen.dsl.ui.common.kind_tag`).
        ctx = detail.get("ctx", {})
        tag = str(ctx.get("tag", "")).removeprefix("tag-")
        choices = [
            choice.removeprefix("tag-") for choice in _literal_choices(ctx.get("expected_tags", ""))
        ]
        expected = ", ".join(f"'{choice}'" for choice in choices)
        return Diagnostic(
            code="invalid-value",
            message=f"The kind '{tag}' is not valid. Expected {expected}.",
            location=source_map.value((*path, "kind")),
            hint=_did_you_mean(tag, choices),
            element_id=element,
        )
    if kind == "union_tag_not_found":
        if isinstance(value, dict):
            return Diagnostic(
                code="missing-key",
                message="The key 'kind' is missing.",
                location=source_map.element(path),
                element_id=element,
            )
        return Diagnostic(
            code="invalid-value",
            message="Expected a mapping.",
            location=location,
            element_id=element,
        )
    if kind == "string_pattern_mismatch":
        pattern = detail.get("ctx", {}).get("pattern", "")
        what = "name" if is_key else "value"
        extension = is_key and isinstance(value, str) and is_extension_key(value)
        return Diagnostic(
            code="invalid-name" if is_key else "invalid-value",
            message=f"The {what} {value!r} does not match the pattern {pattern}.",
            location=location,
            element_id=element,
            hint="Put extension keys in an element, not in a mapping of names."
            if extension
            else None,
        )
    return Diagnostic(
        code="invalid-value",
        message=_TYPE_MESSAGES.get(kind, detail["msg"] + "."),
        location=location,
        element_id=element,
    )


def _version_diagnostic(detail: ErrorDetails, source_map: SourceMap) -> Diagnostic:
    if detail["type"] == "missing":
        return Diagnostic(
            code="missing-version",
            message="The key 'version' is missing. It gives the version of the DSL.",
            location=source_map.root,
            hint=f"Add 'version: {DSL_VERSION}' at the top of the file.",
        )
    return Diagnostic(
        code="unsupported-version",
        message=f"The DSL version {detail['input']!r} is not supported.",
        location=source_map.value(("version",)),
        hint=f"This version of appgen reads DSL version {DSL_VERSION}.",
    )


def _data_path(loc: tuple[int | str, ...]) -> tuple[DataPath, bool]:
    """Convert a Pydantic error location to a data path.

    Pydantic adds "[key]" for an error in a dict key, and a tag for each
    member of a union or a function validator. The tags of the unions in
    the model start with "tag-". Return the path without them, and true
    if the error is in a dict key.
    """
    path: list[str | int] = []
    is_key = False
    for part in loc:
        if part == "[key]":
            is_key = True
        elif isinstance(part, int) or not part.startswith(("function-", "constrained-", "tag-")):
            path.append(part)
    return tuple(path), is_key


def _known_keys(path: DataPath) -> list[str]:
    """Return the keys that the model permits for the mapping at a path."""
    model, _ = _resolve(path)
    return list(model.model_fields) if model else []


def _element_id(path: DataPath) -> str | None:
    """Return the ID of the innermost element that contains a path."""
    _, end = _resolve(path)
    return element_id(path[:end]) if end else None


def _resolve(path: DataPath) -> tuple[type[BaseModel] | None, int]:
    """Follow a data path through the model classes.

    Return the model class at the end of the path (None if the path does
    not end at an element), and the length of the longest prefix of the
    path that ends at an element.
    """
    model: type[BaseModel] = AppDefinition
    end = 0
    position = 0
    while position < len(path):
        info = model.model_fields.get(str(path[position]))
        children = _child_models(info.annotation) if info else []
        if info is None or not children:
            return None, end
        if _is_mapping(info.annotation):
            # The next part is the key of the mapping, for example the entity name.
            if position + 1 == len(path):
                return None, end
            position += 2
        else:
            position += 1
        end = position
        if len(children) > 1:
            # A union, for example of views: take a member that has the next key.
            following = str(path[position]) if position < len(path) else None
            children = [child for child in children if following in child.model_fields]
            if not children:
                return None, end
        model = children[0]
    return model, end


def _unwrap(annotation: object) -> object:
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if get_origin(annotation) is Annotated:
        return _unwrap(get_args(annotation)[0])
    return annotation


def _is_mapping(annotation: object) -> bool:
    return get_origin(_unwrap(annotation)) is dict


def _child_models(annotation: object) -> list[type[BaseModel]]:
    """Return the models in an annotation, for example the members of a union."""
    annotation = _unwrap(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    models: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        models += [model for model in _child_models(arg) if model not in models]
    return models


def _literal_choices(expected: str) -> list[str]:
    return [part.strip(" '") for part in expected.replace(" or ", ",").split(",") if part.strip()]


def _did_you_mean(value: str, choices: list[str]) -> str | None:
    matches = difflib.get_close_matches(value, choices, n=1)
    return f"Did you mean '{matches[0]}'?" if matches else None


def _unique(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    seen: set[tuple[str, str, str]] = set()
    result: list[Diagnostic] = []
    for diagnostic in sorted(diagnostics, key=lambda d: d.location):
        key = (str(diagnostic.location), diagnostic.code, diagnostic.message)
        if key not in seen:
            seen.add(key)
            result.append(diagnostic)
    return result
