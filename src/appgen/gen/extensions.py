"""Check the extension keys (`x-...`) of a definition against the bindings in use.

The DSL keeps extension keys without a check (ADR 0002). A binding can
declare the keys that it reads (`Binding.extension_keys`). This module
checks each declared key of the bindings in use: the element kind that
has it, and its value. An unknown key with the prefix of a binding, or a
key that is close to a declared key, is an error too. The keys of a
binding that is not in use give no error.
"""

import difflib
from collections.abc import Iterable, Iterator
from typing import Any

from pydantic import TypeAdapter, ValidationError

from appgen.dsl.diagnostics import Diagnostic, Location
from appgen.dsl.model import AppDefinition, Element
from appgen.gen.binding import Binding, ExtensionKey
from appgen.gen.elements import iter_elements

_CLOSE = 0.85
"""The similarity above which an unknown key is a typo of a declared key."""


def check_extensions(definition: AppDefinition, bindings: Iterable[Binding]) -> list[Diagnostic]:
    """Return the diagnostics of the extension keys of a definition, in source order."""
    bindings = list(bindings)
    keys: dict[str, tuple[Binding, ExtensionKey]] = {
        key.name: (binding, key) for binding in bindings for key in binding.extension_keys
    }
    prefixes = {b.extension_prefix: b for b in bindings if b.extension_prefix}
    diagnostics: list[Diagnostic] = []
    elements: list[tuple[Element, str]] = [(definition, "definition")] + [
        (e.element, e.kind) for e in iter_elements(definition)
    ]
    for element, kind in elements:
        for name, value in element.extensions.items():
            diagnostics += _check_key(element, kind, name, value, keys, prefixes)
    return sorted(diagnostics, key=lambda d: d.location)


def _check_key(
    element: Element,
    kind: str,
    name: str,
    value: object,
    keys: dict[str, tuple[Binding, ExtensionKey]],
    prefixes: dict[str, Binding],
) -> Iterator[Diagnostic]:
    found = keys.get(name)
    if found is None:
        owner = next((b for p, b in prefixes.items() if name.startswith(p)), None)
        matches = difflib.get_close_matches(name, list(keys), n=1, cutoff=_CLOSE)
        if owner is not None or matches:
            what = f"the binding '{owner.name}'" if owner else "the bindings in use"
            yield _error(
                "unknown-key",
                f"The extension key '{name}' is not a key of {what}.",
                element,
                name,
                f"Did you mean '{matches[0]}'?" if matches else None,
            )
        return
    binding, key = found
    if kind not in key.kinds:
        kinds = ", ".join(f"'{k}'" for k in sorted(key.kinds))
        yield _error(
            "invalid-option",
            f"The extension key '{name}' of the binding '{binding.name}' is for {kinds}, "
            f"not for '{kind}'.",
            element,
            name,
            key.description,
        )
        return
    try:
        _adapter(key).validate_python(value, strict=True)
    except ValidationError as error:
        problem = error.errors()[0]["msg"]
        yield _error(
            "invalid-value",
            f"The value of '{name}' is not valid: {problem[:1].lower()}{problem[1:]}.",
            element,
            name,
            key.description,
        )


_ADAPTERS: dict[int, tuple[ExtensionKey, TypeAdapter[Any]]] = {}
"""The validator of each declared key, by the identity of the key."""


def _adapter(key: ExtensionKey) -> TypeAdapter[Any]:
    found = _ADAPTERS.get(id(key))
    if found is None or found[0] is not key:
        found = _ADAPTERS[id(key)] = (key, TypeAdapter[Any](key.type))
    return found[1]


def _error(code: str, message: str, element: Element, key: str, hint: str | None) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        location=element.location_of(key) or Location("<unknown>", 1, 1),
        element_id=element.id or None,
        hint=hint,
    )
