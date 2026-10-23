"""Python helpers for the templates of the React binding.

The generator adds each function of `HELPERS` to the template globals.
The helpers are deterministic: they read only the definition.
"""

import re
from collections.abc import Callable
from typing import Any

_PARAM = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def route_path(path: str) -> str:
    """Return the React Router path of a page path: `/projects/{id}` gives `/projects/:id`."""
    return _PARAM.sub(lambda match: ":" + match.group(1), path)


def route_params(path: str) -> list[str]:
    """Return the names of the path parameters of a page path, in order."""
    return _PARAM.findall(path)


HELPERS: dict[str, Callable[..., Any]] = {
    "route_path": route_path,
    "route_params": route_params,
}
