"""Generate the files of a binding from an app definition."""

from dataclasses import dataclass, field, replace
from typing import Any, Literal

import jinja2

from appgen.dsl.model import AppDefinition
from appgen.gen.binding import Binding, Output
from appgen.gen.elements import DefinitionElement, iter_elements
from appgen.gen.render import GenerationError, make_environment, normalize_content, normalize_path
from appgen.gen.tokens import resolve_tokens
from appgen.gen.traces import comment_style, trace_globals


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """One file that the generator writes."""

    path: str
    """The path relative to the output folder, with `/` as separator."""
    content: str
    kind: Literal["generated", "extension"] = "generated"
    """A generated file is written on each run. An extension file is created once."""
    element_id: str | None = None
    """The element of the output rule, for a rule with `for_each`."""
    traces: tuple[str, ...] = ()
    """For a file type without comments: the element IDs that the manifest records."""


@dataclass(frozen=True, slots=True)
class Gap:
    """A definition element that the binding does not generate code for."""

    element_id: str
    kind: str
    path: str | None = None
    """The extension file of the gap, if the binding has a gap rule."""


@dataclass(slots=True)
class GenerationResult:
    """The output of one generator run, before the generator writes it to disk."""

    files: list[GeneratedFile] = field(default_factory=list[GeneratedFile])
    gaps: list[Gap] = field(default_factory=list[Gap])


def generate(definition: AppDefinition, binding: Binding) -> GenerationResult:
    """Render the templates of a binding for a definition.

    Each element of a kind that the binding does not cover becomes a gap.
    The files are sorted by path, and the gaps are in source order. Raise
    GenerationError if a template needs a value that does not exist, if
    two output rules write the same path, or if a file that can hold
    comments has no trace (ADR 0004).
    """
    environment = make_environment(binding.template_dir)
    environment.globals.update(binding.helpers)
    environment.globals.update(trace_globals(definition))
    base = _base_context(binding, definition)
    elements = list(iter_elements(definition))
    gap_elements = [e for e in elements if e.kind not in binding.covers]
    files: dict[str, GeneratedFile] = {}

    def add(generated: GeneratedFile) -> None:
        if generated.path in files:
            raise GenerationError(f"Two output rules write the file '{generated.path}'.")
        files[generated.path] = generated

    for output in binding.outputs:
        for context in _contexts(base, output, elements):
            add(_render(environment, output, context))

    gaps: list[Gap] = []
    for element in gap_elements:
        if binding.gap_rule is None:
            gaps.append(Gap(element.id, element.kind))
            continue
        rule = replace(binding.gap_rule, for_each=element.kind, extension=True)
        context = _element_context(base, element)
        generated = _render(environment, rule, context)
        if "TODO(appgen)" not in generated.content:
            raise GenerationError(
                f"The gap rule writes the file '{generated.path}' without a TODO(appgen) comment."
            )
        add(generated)
        gaps.append(Gap(element.id, element.kind, generated.path))
    return GenerationResult(files=[files[path] for path in sorted(files)], gaps=gaps)


def _render(
    environment: jinja2.Environment, output: Output, context: dict[str, Any]
) -> GeneratedFile:
    where = f"'{output.template}'"
    if "element_id" in context:
        where += f" for '{context['element_id']}'"
    kind: Literal["generated", "extension"] = "extension" if output.extension else "generated"
    try:
        path = normalize_path(environment.from_string(output.path).render(context))
        context = {**context, "output_path": path, "output_kind": kind}
        content = environment.get_template(output.template).render(context)
    except jinja2.UndefinedError as error:
        raise GenerationError(f"The template {where} needs a missing value: {error}") from None
    except GenerationError as error:
        raise GenerationError(f"The template {where}: {error}") from None
    element_id: str | None = context.get("element_id")
    traces: tuple[str, ...] = ()
    if comment_style(path) is None:
        traces = (element_id or "app",)
    elif "@trace" not in content:
        raise GenerationError(f"The template {where} writes the file '{path}' with no trace.")
    return GeneratedFile(
        path,
        normalize_content(content),
        kind=kind,
        element_id=element_id,
        traces=traces,
    )


def _contexts(
    base: dict[str, Any], output: Output, elements: list[DefinitionElement]
) -> list[dict[str, Any]]:
    """Return the template context for each file that an output rule makes."""
    if output.for_each is None:
        return [base]
    return [_element_context(base, e) for e in elements if e.kind == output.for_each]


def _base_context(binding: Binding, definition: AppDefinition) -> dict[str, Any]:
    """Return the context that all templates share.

    The context holds no clock or random values. A set has no order, so
    the context gives the covered kinds as a sorted list. `tokens` holds
    the resolved design tokens, sorted by path.
    """
    return {
        "definition": definition,
        "app": definition.app,
        "binding": {"name": binding.name, "covers": sorted(binding.covers)},
        "tokens": resolve_tokens(definition),
    }


def _element_context(base: dict[str, Any], element: DefinitionElement) -> dict[str, Any]:
    return {
        **base,
        "element": element.element,
        "element_id": element.id,
        "element_kind": element.kind,
        "name": element.name,
    }
