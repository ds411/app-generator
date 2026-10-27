"""Python helpers for the templates of the React binding.

The generator adds each function of `HELPERS` to the template globals,
and the values of `context()` to the context of all templates. The
helpers are deterministic: they read only the definition.
"""

import base64
import re
from collections.abc import Callable, Iterator
from typing import Any

from appgen.bindings.react import versions
from appgen.bindings.react.api_client import api_entities, data_source, widget_endpoints
from appgen.bindings.shared import shadcn
from appgen.bindings.shared.auth import auth_pages, kind_operations, record_rules, uses_me
from appgen.bindings.shared.available import available_rules
from appgen.bindings.shared.events import has_events, ts_events
from appgen.bindings.shared.forms import FormContext
from appgen.bindings.shared.i18n import text_helpers
from appgen.bindings.shared.integrations import ts_apis, ts_connections
from appgen.bindings.shared.lines import lines_operations
from appgen.bindings.shared.memberships import member_plan
from appgen.bindings.shared.mock_data import mock_data
from appgen.bindings.shared.notices import has_notices
from appgen.bindings.shared.presence import presence_plans
from appgen.bindings.shared.sharing import share_plans
from appgen.bindings.shared.theme import build_theme
from appgen.bindings.shared.totals import entity_totals, total_keys
from appgen.bindings.shared.typescript import HELPERS as TYPESCRIPT_HELPERS
from appgen.bindings.shared.typescript import (
    Member,
    has_history,
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


def frame_rules(definition: AppDefinition) -> list[tuple[str, str]]:
    """Return the pattern of the request URI and the `frame-ancestors` of each page with
    `embed`, for the map of `nginx.conf` (ADR 0032)."""
    rules: list[tuple[str, str]] = []
    for page in definition.pages.values():
        if not page.embed:
            continue
        segments = [segment for segment in page.path.split("/") if segment]
        path = "".join(
            "/" + ("[^/?]+" if _PARAM.fullmatch(segment) else re.escape(segment))
            for segment in segments
        )
        rules.append((f"~^{path}/?(\\?|$)", " ".join(["'self'", *page.embed])))
    return rules


def route_params(path: str) -> list[str]:
    """Return the names of the path parameters of a page path, in order."""
    return _PARAM.findall(path)


def mock_records(definition: AppDefinition) -> dict[str, list[dict[str, Any]]]:
    """Return the mock records of each entity, with the keys of the TypeScript types.

    A file of a seed record (ADR 0027) is a `FileValue` with a `data:` URL
    of its content, so that the app shows it without a server.
    """
    data = mock_data(definition)
    result: dict[str, list[dict[str, Any]]] = {}
    for entity_name, entity in definition.entities.items():
        keys = {m.name: m.key for m in members(entity_name, entity)}
        seed = definition.seed.get(entity_name)
        seed_records = list(seed.records.values()) if seed is not None else []
        records: list[dict[str, Any]] = []
        for index, record in enumerate(data[entity_name]):
            values = dict(record)
            files = seed_records[index].files if index < len(seed_records) else {}
            for name, seed_file in files.items():
                content = seed_file.content or b""
                media_type = seed_file.media_type or "application/octet-stream"
                encoded = base64.b64encode(content).decode()
                values[name] = {
                    "name": seed_file.name,
                    "size": len(content),
                    "type": media_type,
                    "url": f"data:{media_type};base64,{encoded}",
                }
            records.append(
                {"id": record["id"]} | {keys[k]: v for k, v in values.items() if k in keys}
            )
        result[entity_name] = records
    return result


def _endpoints(definition: AppDefinition) -> dict[str, ListEndpoint]:
    """Return the list endpoints by entity name, for an app with `x-react-data: api`."""
    if data_source(definition) != "api":
        return {}
    return {name: entity.list_endpoint for name, entity in api_entities(definition).items()}


def package_json(definition: AppDefinition) -> dict[str, Any]:
    """Return the content of `package.json`, with the packages sorted by name.

    The app gets the npm packages of the shadcn/ui components that it uses,
    and Leaflet with a map (ADR 0046).
    """
    components = shadcn.used_components(definition, _endpoints(definition))
    dependencies = {
        **versions.DEPENDENCIES,
        **{name: versions.COMPONENT_PACKAGES[name] for name in shadcn.packages(components)},
    }
    views = ViewContext(definition)
    dev_dependencies = dict(versions.DEV_DEPENDENCIES)
    if "table" in views.features:
        dependencies |= versions.TABLE_PACKAGES
    if views.map_tiles:
        dependencies |= versions.MAP_PACKAGES
        dev_dependencies |= versions.MAP_DEV_PACKAGES
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
        "devDependencies": dict(sorted(dev_dependencies.items())),
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
    entities = list(definition.entities)
    return {
        "api_entities": apis,
        # The browser cannot keep a secret or set a cookie for another site:
        # only the APIs without them get a client (ADR 0019), and the
        # exposed APIs, which the FastAPI app calls (`expose`).
        "ts_apis": {name: a for name, a in third_party.items() if a.browser or a.exposed},
        "ts_server_apis": {
            name: a for name, a in third_party.items() if not a.browser and not a.exposed
        },
        # The page of the connections calls the routes of the FastAPI app (ADR 0033).
        "ts_connections": ts_connections(third_party) if definition.auth else [],
        "mock": mock_records(definition),
        "theme": build_theme(definition),
        "theme_element": theme.id if theme is not None else "app",
        "ui_plan": ui_plan(definition),
        "ui_views": ViewContext(definition, forms=True, endpoints=endpoints, widgets=widgets),
        "ui_forms": FormContext(definition, server=api),
        "auth_pages": auth_pages(definition, server=api),
        "record_rules": record_rules(definition),
        # The roles of the users in the records of a scope (ADR 0048), or None.
        "memberships": member_plan(definition),
        # The pages with `share` by entity: the secret links of the records (ADR 0049).
        "shares": share_plans(definition),
        # The pages with `presence` by name: the other users on the records (ADR 0052). The
        # React app with mock data has no server, so it shows no users.
        "presences": presence_plans(definition) if api else {},
        # The values `$me` of the filters and of the defaults: the hook `useMe`.
        "me": uses_me(definition),
        # The keys of the totals in the records (ADR 0034), by entity.
        "record_totals": {name: total_keys(definition, name, api=api) for name in entities},
        # The create and the update operations with lines (ADR 0035), by name.
        "lines_ops": lines_operations(definition),
        **text_helpers(definition),
        "react": {
            "default_mode": theme.default_mode if theme is not None else "system",
            "mode_toggle": shadcn.has_mode_toggle(definition),
            "shadcn": [component.name for component in components],
            "hooks": shadcn.hooks(components),
            "package_json": package_json(definition),
            "node_version": versions.NODE_VERSION,
            "api": api,
            # The events (ADR 0031): the mock store runs their operations. With the
            # FastAPI app, the FastAPI app runs them.
            "events": has_events(definition) and not api,
            # The fields with a sequence: the mock store gives the next number. With
            # the FastAPI app, the database gives it.
            "sequences": not api
            and any(entity.sequence_fields for entity in definition.entities.values()),
            "frame_rules": frame_rules(definition),
            # The totals of the related records (ADR 0034): the mock store computes them.
            # With the FastAPI app, the FastAPI app computes them.
            "totals": {}
            if api
            else {name: totals for name in entities if (totals := entity_totals(definition, name))},
            # The ranges of the related records of the available filters (ADR 0047): the mock
            # store reads them. With the FastAPI app, the list endpoints filter the records.
            "ranges": {} if api else available_rules(definition),
            # The change log (ADR 0040): the mock store keeps the entries, else the FastAPI app.
            "history": has_history(definition),
            # The notices (ADR 0041): the mock store adds them, else the FastAPI app.
            "notices": has_notices(definition),
            # The live entities (ADR 0051): with the FastAPI app, the open views load their
            # records again after the events of the stream `/live`. The mock records stay in
            # the browser tab: no other client changes them.
            "live": [name for name, entity in definition.entities.items() if entity.live and api],
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
    "ts_events": ts_events,
    "kind_operations": kind_operations,
    **TYPESCRIPT_HELPERS,
}
