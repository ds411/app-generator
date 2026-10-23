"""The elements of an app definition, with their IDs and their kinds."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from appgen.dsl.ids import walk_elements
from appgen.dsl.model import AppDefinition, Element, Field
from appgen.dsl.source import DataPath
from appgen.gen.binding import ElementKind

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True, slots=True)
class DefinitionElement:
    """One element of an app definition, with its ID and its kind."""

    id: str
    """The element ID, for example `entities.Task.fields.title` (see ADR 0002)."""
    kind: ElementKind
    name: str
    """The last segment of the ID, for example `title`."""
    element: Element


def element_kind(path: DataPath, element: Element) -> ElementKind:
    """Return the kind of an element, for example `field` or `token_group`.

    The kind is the class name of the element in snake case, for example
    `entity` for an Entity and `token` for a design token. The `Field`
    class serves for entity fields and for operation params, so a Field
    in a `params` mapping has the kind `param`.
    """
    if isinstance(element, Field) and len(path) >= 2 and path[-2] == "params":
        return "param"
    return _CAMEL_BOUNDARY.sub("_", type(element).__name__).lower()


def iter_elements(definition: AppDefinition) -> Iterator[DefinitionElement]:
    """Yield each element of a definition except the root, in source order."""
    for path, element in walk_elements(definition):
        if path:
            yield DefinitionElement(
                id=element.id,
                kind=element_kind(path, element),
                name=str(path[-1]),
                element=element,
            )
