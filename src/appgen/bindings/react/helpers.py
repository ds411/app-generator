"""Python helpers for the templates of the React binding.

The generator adds each function of `HELPERS` to the template globals,
and the values of `context()` to the context of all templates. The
helpers are deterministic: they read only the definition.
"""

import re
from collections.abc import Callable
from typing import Any

from appgen.bindings.react import versions
from appgen.bindings.react.mock_data import mock_data
from appgen.bindings.shared import shadcn
from appgen.bindings.shared.theme import build_theme
from appgen.bindings.shared.typescript import HELPERS as TYPESCRIPT_HELPERS
from appgen.bindings.shared.typescript import (
    Member,
    members,
    to_json,
)
from appgen.bindings.shared.ui import ui_plan
from appgen.dsl.model import AppDefinition

__all__ = ["HELPERS", "Member", "context", "members", "mock_records", "to_json"]

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


def package_json(definition: AppDefinition) -> dict[str, Any]:
    """Return the content of `package.json`, with the packages sorted by name.

    The app gets the npm packages of the shadcn/ui components that it uses.
    """
    components = shadcn.used_components(definition)
    dependencies = {
        **versions.DEPENDENCIES,
        **{name: versions.COMPONENT_PACKAGES[name] for name in shadcn.packages(components)},
    }
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
    components = shadcn.used_components(definition)
    theme = definition.ui.theme if definition.ui is not None else None
    return {
        "mock": mock_records(definition),
        "theme": build_theme(definition),
        "theme_element": theme.id if theme is not None else "app",
        "ui_plan": ui_plan(definition),
        "react": {
            "default_mode": theme.default_mode if theme is not None else "system",
            "mode_toggle": shadcn.has_mode_toggle(definition),
            "shadcn": [component.name for component in components],
            "hooks": shadcn.hooks(components),
            "package_json": package_json(definition),
            "node_version": versions.NODE_VERSION,
        },
    }


HELPERS: dict[str, Callable[..., Any]] = {
    "route_path": route_path,
    "route_params": route_params,
    **TYPESCRIPT_HELPERS,
}
