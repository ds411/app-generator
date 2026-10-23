"""Find a binding by its name.

A binding registers itself with an entry point in the group
`appgen.bindings`. The entry point refers to a `Binding` object.
"""

from importlib.metadata import entry_points

from appgen.gen.binding import Binding

ENTRY_POINT_GROUP = "appgen.bindings"


class UnknownBindingError(LookupError):
    """No binding has the requested name."""

    def __init__(self, name: str, available: list[str]) -> None:
        names = ", ".join(available) or "none"
        super().__init__(f"The binding '{name}' does not exist. Available bindings: {names}.")
        self.name = name
        self.available = available


def available_bindings() -> list[str]:
    """Return the names of the registered bindings, sorted."""
    return sorted({point.name for point in entry_points(group=ENTRY_POINT_GROUP)})


def find_binding(name: str) -> Binding:
    """Return the binding with a name. Raise UnknownBindingError if none has it."""
    for point in entry_points(group=ENTRY_POINT_GROUP, name=name):
        binding = point.load()
        if not isinstance(binding, Binding):
            raise TypeError(f"The entry point '{point.value}' does not refer to a Binding.")
        return binding
    raise UnknownBindingError(name, available_bindings())
