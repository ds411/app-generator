"""The generator core: the binding contract, the registry, and the rendering."""

from appgen.gen.binding import Binding, ElementKind, Output
from appgen.gen.elements import DefinitionElement, element_kind, iter_elements
from appgen.gen.generator import Gap, GeneratedFile, GenerationResult, generate
from appgen.gen.manifest import (
    MANIFEST_PATH,
    Manifest,
    ManifestError,
    ManualEditsError,
    WriteReport,
    read_manifest,
    write_result,
)
from appgen.gen.registry import UnknownBindingError, available_bindings, find_binding
from appgen.gen.render import GenerationError

__all__ = [
    "MANIFEST_PATH",
    "Binding",
    "DefinitionElement",
    "ElementKind",
    "Gap",
    "GeneratedFile",
    "GenerationError",
    "GenerationResult",
    "Manifest",
    "ManifestError",
    "ManualEditsError",
    "Output",
    "UnknownBindingError",
    "WriteReport",
    "available_bindings",
    "element_kind",
    "find_binding",
    "generate",
    "iter_elements",
    "read_manifest",
    "write_result",
]
