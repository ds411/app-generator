"""The elements of an app definition, with their IDs and their kinds."""

from collections.abc import Iterator
from dataclasses import dataclass

from appgen.dsl.ids import walk_elements
from appgen.dsl.model import AppDefinition, Element
from appgen.dsl.source import DataPath
from appgen.gen.binding import ElementKind

# The element kind of the items of each named collection in the definition.
_COLLECTION_KINDS: dict[str, ElementKind] = {
    "entities": "entity",
    "fields": "field",
    "relations": "relation",
    "operations": "operation",
    "params": "param",
    "pages": "page",
}


@dataclass(frozen=True, slots=True)
class DefinitionElement:
    """One element of an app definition, with its ID and its kind."""

    id: str
    """The element ID, for example `entities.Task.fields.title` (see ADR 0002)."""
    kind: ElementKind
    name: str
    """The last segment of the ID, for example `title`."""
    element: Element


def element_kind(path: DataPath) -> ElementKind:
    """Return the kind of the element at a path, for example `field`.

    A top-level element (for example `app`) has its key as kind. An item
    of a named collection has the kind of the collection, or the name of
    the collection if the generator does not know it.
    """
    if len(path) == 1:
        return str(path[0])
    collection = str(path[-2])
    return _COLLECTION_KINDS.get(collection, collection)


def iter_elements(definition: AppDefinition) -> Iterator[DefinitionElement]:
    """Yield each element of a definition except the root, in source order."""
    for path, element in walk_elements(definition):
        if path:
            yield DefinitionElement(
                id=element.id,
                kind=element_kind(path),
                name=str(path[-1]),
                element=element,
            )
