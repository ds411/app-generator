"""The API client of the React app for the FastAPI app (the key `x-react-data: api`).

The client calls the endpoints that the FastAPI binding generates for
the same definition: the paths, the methods, the JSON names, and the
query parameters of the list endpoints come from the model of the
FastAPI binding, which also makes its OpenAPI document. Without the key,
the React app uses mock data.
"""

from dataclasses import dataclass
from typing import Literal

from appgen.bindings.fastapi.model import python_app
from appgen.bindings.shared.typescript import members
from appgen.bindings.shared.views import ListEndpoint
from appgen.dsl.model import AppDefinition

DATA_KEY = "x-react-data"
"""The extension key of the app that selects the data source: `mock` (default) or `api`."""

type DataSource = Literal["mock", "api"]


@dataclass(frozen=True, slots=True)
class ApiEndpoint:
    """One endpoint of the FastAPI app: the operation ID, the method, and the path."""

    operation: str
    method: str
    path: str


@dataclass(frozen=True, slots=True)
class ApiEntity:
    """The endpoints and the JSON names of one entity."""

    name: str
    path: str
    """The path of the collection, for example `/tasks`."""
    keys: dict[str, str]
    """The key of the TypeScript type for each JSON name, for example `due_date: dueDate`."""
    numbers: list[str]
    """The keys of the decimal fields: the API sends them as text."""
    filters: dict[str, str]
    """The keys that the list endpoint can filter by: `one` value, or a `list` of values."""
    sorts: list[str]
    """The keys that the list endpoint can sort by."""
    endpoints: list[ApiEndpoint]
    list_endpoint: ListEndpoint
    """The query parameters and the sort keys of the list endpoint, for the views."""


def data_source(definition: AppDefinition) -> DataSource:
    """Return the data source of the React app."""
    return "api" if definition.app.extensions.get(DATA_KEY) == "api" else "mock"


def api_entities(definition: AppDefinition) -> dict[str, ApiEntity]:
    """Return the API of each entity, by entity name."""
    app = python_app(definition)
    result: dict[str, ApiEntity] = {}
    for name, entity in definition.entities.items():
        py = app.entity(name)
        json_names = {f.id: f.name for f in py.fields}
        json_names |= {r.id: r.fk_attr or "" for r in py.relations if r.side == "fk"}
        json_names |= {r.id: r.ids_field or "" for r in py.relations if r.side == "m2m"}
        keys: dict[str, str] = {}
        for member in members(name, entity):
            if member.element_id in json_names:
                keys[json_names[member.element_id]] = member.key
        query = py.query
        params = {p.name: p for p in query.params if p.kind in ("eq", "in")}
        filters = {
            key: "list" if params[json].is_list else "one"
            for json, key in [*keys.items(), ("id", "id")]
            if json in params
        }
        element_params: dict[str, list[str]] = {}
        for param in query.params:
            for element_id in param.ids:
                element_params.setdefault(element_id, []).append(param.name)
        sort_keys = frozenset(k.name for k in query.sort_keys)
        result[name] = ApiEntity(
            name=name,
            path=py.path,
            keys=keys,
            numbers=[keys[f.name] for f in py.fields if f.type == "decimal" and f.name in keys],
            filters=filters,
            sorts=[key for json, key in keys.items() if json in sort_keys],
            endpoints=[
                ApiEndpoint(op.name, op.method.upper(), py.path + op.path.rstrip("/"))
                for op in py.operations
            ],
            list_endpoint=ListEndpoint(element_params, sort_keys),
        )
    return result
