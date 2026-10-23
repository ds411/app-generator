"""The generator core: the binding contract, the registry, and the rendering."""

from appgen.gen.binding import Binding, ElementKind, Output
from appgen.gen.elements import DefinitionElement, element_kind, iter_elements
from appgen.gen.generator import Gap, GeneratedFile, GenerationResult, generate
from appgen.gen.registry import UnknownBindingError, available_bindings, find_binding

__all__ = [
    "Binding",
    "DefinitionElement",
    "ElementKind",
    "Gap",
    "GeneratedFile",
    "GenerationResult",
    "Output",
    "UnknownBindingError",
    "available_bindings",
    "element_kind",
    "find_binding",
    "generate",
    "iter_elements",
]
