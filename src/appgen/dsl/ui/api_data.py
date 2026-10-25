"""The data of a view of API data: the operation, its answer, and the items (ADR 0022)."""

from dataclasses import dataclass

from appgen.dsl.apis import Api
from appgen.dsl.model import AppDefinition
from appgen.dsl.openapi import (
    ClientSpec,
    Operation,
    Schema,
    list_items,
    object_properties,
    property_chain,
)
from appgen.dsl.ui.views import ApiDetailView, ApiView


@dataclass(frozen=True, slots=True)
class ApiData:
    """The operation of a view of API data, in the normal form of its document."""

    api: Api
    spec: ClientSpec
    operation: Operation
    item: Schema | None
    """The schema of an item of a list view, or of the answer of a detail view: an object.
    None if the answer does not suit the view."""


def api_data(definition: AppDefinition, view: ApiView) -> ApiData | None:
    """Return the data of a view, or None if its API or its operation does not exist."""
    api = definition.apis.get(view.api)
    if api is None or view.operation not in api.operations:
        return None
    spec = api.spec
    operation = next((o for o in spec.operations if o.id == view.operation), None)
    if operation is None:
        return None
    return ApiData(api, spec, operation, _item(view, operation, spec))


def _item(view: ApiView, operation: Operation, spec: ClientSpec) -> Schema | None:
    result = operation.result
    if result is None:
        return None
    if isinstance(view, ApiDetailView):
        return result if object_properties(result, spec) is not None else None
    container = result
    if view.items is not None:
        chain = property_chain(result, view.items, spec)
        if chain is None:
            return None
        container = chain[-1].schema
    item = list_items(container, spec)
    if item is None or object_properties(item, spec) is None:
        return None
    return item
