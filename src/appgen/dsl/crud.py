"""The CRUD shorthand of an entity: `crud` expands to operations, views, and forms.

The loader expands the shorthand in the plain YAML data, before the
model checks it (ADR 0008). Each expanded element gets the same name,
and thus the same element ID, as the explicit form, so that traces stay
valid. An element that the definition gives explicitly wins over the
expanded element of the same name. The source map points each expanded
element to the `crud` key of its entity.
"""

import re
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from appgen.dsl.source import SourceMap

type CrudOperation = Literal["create", "read", "update", "delete", "list"]
type CrudView = Literal["table", "detail"]
type CrudForm = Literal["create", "update"]

CRUD_OPERATIONS: tuple[str, ...] = CrudOperation.__value__.__args__
_NAME_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SINGLE_KINDS = ("many_to_one", "one_to_one")
_COLUMN_SKIP = ("text", "json")


class Crud(BaseModel):
    """The parts that the CRUD shorthand of an entity asks for.

    `crud: true` asks for all operations. `crud: [create, list]` asks for
    some operations. The mapping form also asks for views and forms.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    operations: list[CrudOperation] = Field(
        default_factory=lambda: cast(list[CrudOperation], list(CRUD_OPERATIONS))
    )
    """The operations. The default is all five."""
    views: list[CrudView] = Field(default_factory=list[CrudView])
    """A table view `<entity>_table` and a detail view `<entity>_detail`."""
    forms: list[CrudForm] = Field(default_factory=list[CrudForm])
    """A create form `new_<entity>` and an edit form `edit_<entity>`."""


def crud_input(value: object) -> object:
    """Return the mapping form of a shorthand: `true` and a list of operations become mappings."""
    if value is True:
        return {}
    if value is False:
        return None
    if isinstance(value, list):
        return {"operations": cast(list[object], value)}
    return value


def crud_schema(schema: dict[str, Any]) -> None:
    """Add the short forms (`true`, a list of operations) to the JSON Schema of the key."""
    operations = {"type": "array", "items": {"enum": list(CRUD_OPERATIONS)}}
    schema["anyOf"] = [{"type": "boolean"}, operations, *schema.get("anyOf", [])]


def snake_name(entity: str) -> str:
    """Return the snake case name of an entity name: `TaskList` gives `task_list`."""
    return _NAME_PATTERN.sub("_", entity).lower()


def plural(name: str) -> str:
    """Return the English plural of a name in snake case, with simple rules."""
    head, _, last = name.rpartition("_")
    if re.search(r"[^aeiou]y$", last):
        last = last[:-1] + "ies"
    elif re.search(r"(s|x|z|ch|sh)$", last):
        last += "es"
    else:
        last += "s"
    return f"{head}_{last}" if head else last


def operation_names(entity: str, data: dict[str, object]) -> dict[str, str]:
    """Return the name of each CRUD operation of an entity, by kind.

    The list operation takes the plural label of the entity, if it has
    one, for example `list_people` for the label `People`.
    """
    name = snake_name(entity)
    label = data.get("plural_label")
    many = (
        re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        if isinstance(label, str) and label.strip()
        else plural(name)
    )
    names = {kind: f"{kind}_{name}" for kind in CRUD_OPERATIONS}
    names["list"] = f"list_{many}"
    return names


def expand_crud(data: object, source_map: SourceMap) -> object:
    """Return the definition data with the CRUD shorthand of each entity expanded.

    A shorthand that is not valid stays as it is: the model reports it.
    """
    if not isinstance(data, dict):
        return data
    result = dict(cast(dict[str, object], data))
    entities = result.get("entities")
    if not isinstance(entities, dict):
        return result
    operations: dict[str, object] = {}
    views: dict[str, object] = {}
    forms: dict[str, object] = {}
    at: dict[str, tuple[str, ...]] = {}
    """The `crud` key of the entity of each expanded element, by ID."""
    for entity, value in cast(dict[str, object], entities).items():
        if not isinstance(value, dict):
            continue
        entity_data = cast(dict[str, object], value)
        crud = _parse(entity_data.get("crud"))
        if crud is None:
            continue
        key = ("entities", entity, "crud")
        names = operation_names(entity, entity_data)
        for kind in crud.operations:
            operations[names[kind]] = {"kind": kind, "entity": entity}
            at[f"operations.{names[kind]}"] = key
        name = snake_name(entity)
        if "table" in crud.views:
            views[f"{name}_table"] = _table(entity, entity_data)
            at[f"ui.views.{name}_table"] = key
        if "detail" in crud.views:
            views[f"{name}_detail"] = _detail(entity, entity_data)
            at[f"ui.views.{name}_detail"] = key
        for kind in crud.forms:
            form_name = f"new_{name}" if kind == "create" else f"edit_{name}"
            forms[form_name] = _form(entity, entity_data, names[kind])
            at[f"ui.forms.{form_name}"] = key
    _merge(result, ("operations",), operations, source_map, at)
    if views or forms:
        ui = result.get("ui", {})
        if isinstance(ui, dict):
            ui_data = dict(cast(dict[str, object], ui))
            _merge(ui_data, ("ui", "views"), views, source_map, at)
            _merge(ui_data, ("ui", "forms"), forms, source_map, at)
            result["ui"] = ui_data
    return result


def _parse(value: object) -> Crud | None:
    value = crud_input(value)
    if not isinstance(value, dict):
        return None
    try:
        return Crud.model_validate(value)
    except ValueError:
        return None


def _merge(
    parent: dict[str, object],
    path: tuple[str, ...],
    items: dict[str, object],
    source_map: SourceMap,
    at: dict[str, tuple[str, ...]],
) -> None:
    """Add the expanded items to a mapping of the data. Explicit items win."""
    if not items:
        return
    key = path[-1]
    current = parent.get(key, {})
    if not isinstance(current, dict):
        return
    explicit = cast(dict[str, object], current)
    for name in items:
        if name not in explicit:
            crud = at[".".join((*path, name))]
            location = source_map.keys.get(crud) or source_map.element(crud)
            source_map.keys.setdefault(path, location)
            source_map.keys[(*path, name)] = location
    parent[key] = {**items, **explicit}


def _fields(data: dict[str, object]) -> dict[str, dict[str, object]]:
    fields = data.get("fields")
    if not isinstance(fields, dict):
        return {}
    return {
        str(k): cast(dict[str, object], v)
        for k, v in cast(dict[str, object], fields).items()
        if isinstance(v, dict) and not str(k).startswith("x-")
    }


def _relations(data: dict[str, object], kinds: tuple[str, ...]) -> list[str]:
    relations = data.get("relations")
    if not isinstance(relations, dict):
        return []
    return [
        str(k)
        for k, v in cast(dict[str, object], relations).items()
        if isinstance(v, dict) and cast(dict[str, object], v).get("kind") in kinds
    ]


def _table(entity: str, data: dict[str, object]) -> dict[str, object]:
    names = [n for n, f in _fields(data).items() if f.get("type") not in _COLUMN_SKIP]
    names += _relations(data, _SINGLE_KINDS)
    return {"kind": "table", "entity": entity, "columns": {name: {} for name in names}}


def _detail(entity: str, data: dict[str, object]) -> dict[str, object]:
    names = [*_fields(data), *_relations(data, _SINGLE_KINDS)]
    return {
        "kind": "detail",
        "entity": entity,
        "sections": {"details": {"fields": names, "columns": 2}},
    }


def _form(entity: str, data: dict[str, object], operation: str) -> dict[str, object]:
    stored = [n for n, f in _fields(data).items() if "computed" not in f]
    names = [*stored, *_relations(data, (*_SINGLE_KINDS, "many_to_many"))]
    return {
        "entity": entity,
        "operation": operation,
        "fields": {name: {} for name in names},
    }
