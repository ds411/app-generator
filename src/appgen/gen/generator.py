"""Generate the files of a binding from an app definition."""

from dataclasses import dataclass, field
from typing import Any

import jinja2

from appgen.dsl.model import AppDefinition
from appgen.gen.binding import Binding, Output
from appgen.gen.elements import DefinitionElement, iter_elements


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """One file that the generator writes."""

    path: str
    """The path relative to the output folder, with `/` as separator."""
    content: str


@dataclass(frozen=True, slots=True)
class Gap:
    """A definition element that the binding does not generate code for."""

    element_id: str
    kind: str


@dataclass(slots=True)
class GenerationResult:
    """The output of one generator run, before the generator writes it to disk."""

    files: list[GeneratedFile] = field(default_factory=list[GeneratedFile])
    gaps: list[Gap] = field(default_factory=list[Gap])


def generate(definition: AppDefinition, binding: Binding) -> GenerationResult:
    """Render the templates of a binding for a definition.

    Each element of a kind that the binding does not cover becomes a gap.
    """
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(binding.template_dir),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    elements = list(iter_elements(definition))
    result = GenerationResult(
        gaps=[Gap(e.id, e.kind) for e in elements if e.kind not in binding.covers]
    )
    for output in binding.outputs:
        for context in _contexts(output, definition, elements):
            path = environment.from_string(output.path).render(context)
            content = environment.get_template(output.template).render(context)
            result.files.append(GeneratedFile(path, content))
    return result


def _contexts(
    output: Output, definition: AppDefinition, elements: list[DefinitionElement]
) -> list[dict[str, Any]]:
    """Return the template context for each file that an output rule makes."""
    base: dict[str, Any] = {"definition": definition, "app": definition.app}
    if output.for_each is None:
        return [base]
    return [
        {
            **base,
            "element": e.element,
            "element_id": e.id,
            "name": e.name,
        }
        for e in elements
        if e.kind == output.for_each
    ]
