"""Generate the files of a binding from an app definition."""

from dataclasses import dataclass, field
from typing import Any

import jinja2

from appgen.dsl.model import AppDefinition
from appgen.gen.binding import Binding, Output
from appgen.gen.elements import DefinitionElement, iter_elements
from appgen.gen.render import GenerationError, make_environment, normalize_content, normalize_path


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
    The files are sorted by path, and the gaps are in source order. Raise
    GenerationError if a template needs a value that does not exist, or if
    two output rules write the same path.
    """
    environment = make_environment(binding.template_dir)
    elements = list(iter_elements(definition))
    result = GenerationResult(
        gaps=[Gap(e.id, e.kind) for e in elements if e.kind not in binding.covers]
    )
    files: dict[str, GeneratedFile] = {}
    for output in binding.outputs:
        for context in _contexts(binding, output, definition, elements):
            generated = _render(environment, output, context)
            if generated.path in files:
                raise GenerationError(f"Two output rules write the file '{generated.path}'.")
            files[generated.path] = generated
    result.files = [files[path] for path in sorted(files)]
    return result


def _render(
    environment: jinja2.Environment, output: Output, context: dict[str, Any]
) -> GeneratedFile:
    where = f"'{output.template}'"
    if "element_id" in context:
        where += f" for '{context['element_id']}'"
    try:
        path = environment.from_string(output.path).render(context)
        content = environment.get_template(output.template).render(context)
    except jinja2.UndefinedError as error:
        raise GenerationError(f"The template {where} needs a missing value: {error}") from None
    return GeneratedFile(normalize_path(path), normalize_content(content))


def _contexts(
    binding: Binding, output: Output, definition: AppDefinition, elements: list[DefinitionElement]
) -> list[dict[str, Any]]:
    """Return the template context for each file that an output rule makes.

    The context holds no clock or random values. A set has no order, so
    the context gives the covered kinds as a sorted list.
    """
    base: dict[str, Any] = {
        "definition": definition,
        "app": definition.app,
        "binding": {"name": binding.name, "covers": sorted(binding.covers)},
    }
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
