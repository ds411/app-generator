"""The API client of the React app for the FastAPI app (the key `x-react-data: api`).

The client calls the endpoints that the FastAPI binding generates for
the same definition: the paths, the methods, the JSON names, and the
query parameters of the list endpoints come from the model of the
FastAPI binding, which also makes its OpenAPI document. Without the key,
the React app uses mock data.
"""

from dataclasses import dataclass, field
from typing import Literal

from appgen.bindings.fastapi.model import python_app
from appgen.bindings.shared.typescript import members
from appgen.bindings.shared.views import ListEndpoint, WidgetEndpoint, definition_display
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel

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
    display: str
    """The key of the display field: the text of a record in a choice."""
    search: bool
    """True if `q` of the list endpoint searches the display field."""
    endpoints: list[ApiEndpoint]
    list_endpoint: ListEndpoint
    """The query parameters and the sort keys of the list endpoint, for the views."""
    translations: bool = False
    """True if the entity has a translatable field: the client asks for all languages (ADR 0026)."""
    files: dict[str, str] = field(default_factory=dict[str, str])
    """The last part of the path of the endpoints of each file field (ADR 0027), by key, for
    example `testReport: test-report`. Empty if the app has no endpoints of the files."""


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
        json_names |= {f.id: f.name for f in py.files}
        json_names |= {r.id: r.fk_attr or "" for r in py.relations if r.side == "fk"}
        json_names |= {r.id: r.ids_field or "" for r in py.relations if r.side == "m2m"}
        translations = {f.id: f.translations_name for f in py.translatable}
        keys: dict[str, str] = {}
        for member in members(name, entity):
            names = json_names if member.translations is None else translations
            if member.element_id in names:
                keys[names[member.element_id]] = member.key
        # The computed fields with totals: the FastAPI app computes them (ADR 0034).
        totals = [c for c in py.computed if c.totals]
        keys |= {c.attr: camel(c.name) for c in totals}
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
        display = definition_display(entity)
        search = query.search
        result[name] = ApiEntity(
            name=name,
            path=py.path,
            keys=keys,
            numbers=[
                *(keys[f.name] for f in py.fields if f.type == "decimal" and f.name in keys),
                *(keys[c.attr] for c in totals if c.type == "Decimal"),
            ],
            filters=filters,
            sorts=[key for json, key in keys.items() if json in sort_keys],
            display=camel(display),
            search=search is not None and any(p.path == display for p in search.search),
            endpoints=[
                ApiEndpoint(op.name, op.method.upper(), py.path + op.path.rstrip("/"))
                for op in py.operations
            ],
            list_endpoint=ListEndpoint(element_params, sort_keys),
            translations=bool(translations),
            files={
                keys[f.name]: f.path.removeprefix("/{id}/")
                for f in (py.files if py.file_endpoints else [])
            },
        )
    return result


def widget_endpoints(definition: AppDefinition) -> dict[str, WidgetEndpoint]:
    """Return the endpoint of each dashboard widget of the FastAPI app, by element ID."""
    return {
        widget.id: WidgetEndpoint(dashboard.path + widget.path, widget.today, widget.week)
        for dashboard in python_app(definition).dashboards.values()
        for widget in dashboard.widgets
    }
