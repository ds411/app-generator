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
    excluded_kinds: tuple[str, ...] = ()
    """The element kinds that are out of the scope of the binding, sorted."""
    elements: dict[str, str] = field(default_factory=dict[str, str])
    """The kind of each element of the definition, by ID, in source order."""


def generate(definition: AppDefinition, binding: Binding) -> GenerationResult:
    """Render the templates of a binding for a definition.

    Each element of a kind that the binding does not cover becomes a gap,
    unless its kind, or the kind of an element above it, is excluded. The
    files are sorted by path, and the gaps are in source order. Raise
    GenerationError if a template needs a value that does not exist, if
    two output rules write the same path, or if a file that can hold
    comments has no trace (ADR 0004).
    """
    environment = make_environment(binding.template_dir, binding.shared_template_dirs)
    environment.globals.update(binding.helpers)
    environment.globals.update(trace_globals(definition))
    environment.filters.update(binding.filters)
    base = _base_context(binding, definition)
    elements = list(iter_elements(definition))
    in_scope = _in_scope(elements, binding.excludes)
    gap_elements = [e for e in in_scope if e.kind not in binding.covers]
    files: dict[str, GeneratedFile] = {}

    def add(generated: GeneratedFile) -> None:
        if generated.path in files:
            raise GenerationError(f"Two output rules write the file '{generated.path}'.")
        files[generated.path] = generated

    for output in binding.outputs:
        for context in _contexts(base, output, elements):
            if _applies(environment, output, context):
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
    return GenerationResult(
        files=[files[path] for path in sorted(files)],
        gaps=gaps,
        excluded_kinds=tuple(sorted(binding.excludes)),
        elements={e.id: e.kind for e in elements},
    )


def _in_scope(
    elements: list[DefinitionElement], excludes: frozenset[str]
) -> list[DefinitionElement]:
    """Return the elements that are not of an excluded kind, and not under such an element."""
    roots: list[str] = []
    kept: list[DefinitionElement] = []
    for element in elements:
        if element.kind in excludes:
            roots.append(element.id)
        elif not any(element.id.startswith(f"{root}.") for root in roots):
            kept.append(element)
    return kept


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


def _applies(environment: jinja2.Environment, output: Output, context: dict[str, Any]) -> bool:
    """Return True if the `when` expression of an output rule is true in a context."""
    if output.when is None:
        return True
    where = f"'{output.template}'"
    if "element_id" in context:
        where += f" for '{context['element_id']}'"
    try:
        return bool(environment.compile_expression(output.when, undefined_to_none=False)(**context))
    except jinja2.UndefinedError as error:
        raise GenerationError(
            f"The condition of the rule {where} needs a missing value: {error}"
        ) from None
    except jinja2.TemplateSyntaxError as error:
        raise GenerationError(f"The condition of the rule {where} is not valid: {error}") from None


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
    the resolved design tokens, sorted by path. The context function of
    the binding adds its values, but it cannot replace a value of the
    generator.
    """
    base: dict[str, Any] = {
        "definition": definition,
        "app": definition.app,
        "binding": {"name": binding.name, "covers": sorted(binding.covers)},
        "tokens": resolve_tokens(definition),
    }
    if binding.context is None:
        return base
    extra = dict(binding.context(definition))
    clash = sorted((set(base) | _ELEMENT_KEYS) & set(extra))
    if clash:
        names = ", ".join(clash)
        raise GenerationError(
            f"The context of the binding replaces values of the generator: {names}."
        )
    return {**base, **extra}


_ELEMENT_KEYS = frozenset(
    {"element", "element_id", "element_kind", "name", "output_path", "output_kind"}
)


def _element_context(base: dict[str, Any], element: DefinitionElement) -> dict[str, Any]:
    return {
        **base,
        "element": element.element,
        "element_id": element.id,
        "element_kind": element.kind,
        "name": element.name,
    }
