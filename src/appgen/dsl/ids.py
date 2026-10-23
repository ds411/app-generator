"""Element IDs: the stable names that traces use to refer to definition elements.

An element ID is the path of mapping keys from the root of the definition
to the element, with a dot between the keys, for example
`entities.Task.fields.title` (ADR 0002). IDs never contain list positions.
"""

from collections.abc import Iterator

from appgen.dsl.diagnostics import DefinitionError, Diagnostic
from appgen.dsl.element import Element
from appgen.dsl.source import DataPath


def element_id(path: DataPath) -> str:
    """Return the element ID for the data path of an element."""
    return ".".join(str(part) for part in path)


def walk_elements(element: Element, path: DataPath = ()) -> Iterator[tuple[DataPath, Element]]:
    """Yield each element of the tree under an element, with its path, in source order."""
    yield path, element
    for name in type(element).model_fields:
        value = getattr(element, name)
        if isinstance(value, Element):
            yield from walk_elements(value, (*path, name))
        elif isinstance(value, dict):
            for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
                if isinstance(item, Element):
                    yield from walk_elements(item, (*path, name, str(key)))  # pyright: ignore[reportUnknownArgumentType]
    # Some elements, for example token groups, keep named children as
    # extra keys of their own mapping.
    for key, item in (element.model_extra or {}).items():
        if isinstance(item, Element):
            yield from walk_elements(item, (*path, key))


def index_elements(root: Element) -> dict[str, Element]:
    """Give each element under the root its ID, and return the elements by ID.

    The root itself has no ID. Raise DefinitionError if two elements have
    the same ID.
    """
    index: dict[str, Element] = {}
    diagnostics: list[Diagnostic] = []
    for path, element in walk_elements(root):
        if not path:
            continue
        id_ = element_id(path)
        element._id = id_  # pyright: ignore[reportPrivateUsage]
        first = index.get(id_)
        if first is None:
            index[id_] = element
        elif element.location is not None:
            diagnostics.append(
                Diagnostic(
                    code="duplicate-id",
                    message=f"Two elements have the ID '{id_}'.",
                    location=element.location,
                    element_id=id_,
                    hint=f"The other element is at {first.location}." if first.location else None,
                )
            )
    if diagnostics:
        raise DefinitionError(diagnostics)
    return index
