"""Python helpers for the templates of the React binding.

The generator adds each function of `HELPERS` to the template globals,
and the values of `context()` to the context of all templates. The
helpers are deterministic: they read only the definition.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any

from appgen.bindings.react import versions
from appgen.bindings.react.api_client import api_entities, data_source, widget_endpoints
from appgen.bindings.shared import shadcn
from appgen.bindings.shared.auth import auth_pages, record_rules
from appgen.bindings.shared.forms import FormContext
from appgen.bindings.shared.i18n import text_helpers
from appgen.bindings.shared.integrations import ts_apis
from appgen.bindings.shared.mock_data import mock_data
from appgen.bindings.shared.theme import build_theme
from appgen.bindings.shared.typescript import HELPERS as TYPESCRIPT_HELPERS
from appgen.bindings.shared.typescript import (
    Member,
    members,
    to_json,
)
from appgen.bindings.shared.ui import ui_plan
from appgen.bindings.shared.views import ListEndpoint, ViewContext
from appgen.dsl.model import AppDefinition

__all__ = ["HELPERS", "Member", "context", "members", "mock_records", "to_json", "warnings"]

_PARAM = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def route_path(path: str) -> str:
    """Return the React Router path of a page path: `/projects/{id}` gives `/projects/:id`."""
    return _PARAM.sub(lambda match: ":" + match.group(1), path)


def route_params(path: str) -> list[str]:
    """Return the names of the path parameters of a page path, in order."""
    return _PARAM.findall(path)


def mock_records(definition: AppDefinition) -> dict[str, list[dict[str, Any]]]:
    """Return the mock records of each entity, with the keys of the TypeScript types."""
    data = mock_data(definition)
    result: dict[str, list[dict[str, Any]]] = {}
    for entity_name, entity in definition.entities.items():
        keys = {m.name: m.key for m in members(entity_name, entity)}
        result[entity_name] = [
            {"id": record["id"]} | {keys[k]: v for k, v in record.items() if k in keys}
            for record in data[entity_name]
        ]
    return result


def _endpoints(definition: AppDefinition) -> dict[str, ListEndpoint]:
    """Return the list endpoints by entity name, for an app with `x-react-data: api`."""
    if data_source(definition) != "api":
        return {}
    return {name: entity.list_endpoint for name, entity in api_entities(definition).items()}


def package_json(definition: AppDefinition) -> dict[str, Any]:
    """Return the content of `package.json`, with the packages sorted by name.

    The app gets the npm packages of the shadcn/ui components that it uses.
    """
    components = shadcn.used_components(definition, _endpoints(definition))
    dependencies = {
        **versions.DEPENDENCIES,
        **{name: versions.COMPONENT_PACKAGES[name] for name in shadcn.packages(components)},
    }
    if "table" in ViewContext(definition).features:
        dependencies |= versions.TABLE_PACKAGES
    if FormContext(definition).used:
        dependencies |= versions.FORM_PACKAGES
    if definition.auth is not None and definition.auth.second_factor is not None:
        dependencies |= versions.SECOND_FACTOR_PACKAGES
    return {
        "name": definition.app.name,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "packageManager": f"pnpm@{versions.PNPM_VERSION}",
        "engines": {"node": ">=22.22.0"},
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
            "lint": "eslint --max-warnings 0 .",
            "typecheck": "tsc --noEmit",
        },
        "dependencies": dict(sorted(dependencies.items())),
        "devDependencies": dict(sorted(versions.DEV_DEPENDENCIES.items())),
    }


def context(definition: AppDefinition) -> dict[str, Any]:
    """Return the values that the binding adds to the context of all templates."""
    theme = definition.ui.theme if definition.ui is not None else None
    api = data_source(definition) == "api"
    apis = api_entities(definition) if api else {}
    endpoints = {name: entity.list_endpoint for name, entity in apis.items()}
    widgets = widget_endpoints(definition) if api else {}
    components = shadcn.used_components(definition, endpoints)
    third_party = ts_apis(definition)
    return {
        "api_entities": apis,
        # The browser cannot keep a secret or set a cookie for another site:
        # only the APIs without them get a client (ADR 0019), and the
        # exposed APIs, which the FastAPI app calls (`expose`).
        "ts_apis": {name: a for name, a in third_party.items() if a.browser or a.exposed},
        "ts_server_apis": {
            name: a for name, a in third_party.items() if not a.browser and not a.exposed
        },
        "mock": mock_records(definition),
        "theme": build_theme(definition),
        "theme_element": theme.id if theme is not None else "app",
        "ui_plan": ui_plan(definition),
        "ui_views": ViewContext(definition, forms=True, endpoints=endpoints, widgets=widgets),
        "ui_forms": FormContext(definition, server=api),
        "auth_pages": auth_pages(definition, server=api),
        "record_rules": record_rules(definition),
        **text_helpers(definition),
        "react": {
            "default_mode": theme.default_mode if theme is not None else "system",
            "mode_toggle": shadcn.has_mode_toggle(definition),
            "shadcn": [component.name for component in components],
            "hooks": shadcn.hooks(components),
            "package_json": package_json(definition),
            "node_version": versions.NODE_VERSION,
            "api": api,
        },
    }


def warnings(definition: AppDefinition) -> Iterator[str]:
    """Return a warning for each API with a secret or a cookie parameter that the FastAPI app
    does not expose.

    The React app has no client for such an API.
    """
    for name, api in ts_apis(definition).items():
        if api.browser or api.exposed:
            continue
        reason = api.server_reason.replace("`", "")
        yield (
            f"The API '{name}' {reason}, so the React app has no client for it. Hint: set "
            "'expose: true' on the API, so that the FastAPI app calls the API for the React "
            f"app, or call the API in a custom operation of the FastAPI app (apis: [{name}]). "
            "Then set 'x-react-data: api' in the section 'app'."
        )


HELPERS: dict[str, Callable[..., Any]] = {
    "route_path": route_path,
    "route_params": route_params,
    **TYPESCRIPT_HELPERS,
}
