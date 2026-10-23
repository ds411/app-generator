"""The binding contract: what a binding declares to plug into the generator."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from appgen.dsl.model import AppDefinition

type ElementKind = str
"""The kind of a definition element, for example `entity` or `field`.

The kind is the class name of the element in snake case. The kinds of
DSL version 0 are `app`, `entity`, `field`, `relation`, `operation`,
`param`, and `page`. The UI adds kinds such as `token`, `token_group`,
`layout`, and `menu_item`. See `appgen.gen.elements`.
"""


@dataclass(frozen=True, slots=True)
class Output:
    """One rule of the output layout of a binding.

    The generator renders `template` to the file at `path`. If `for_each`
    is set, the generator renders the template once for each element of
    that kind. The path is a Jinja2 template too, so that it can contain
    the name of the element, for example `entities/{{ name }}.txt`.
    """

    template: str
    """The name of the template, relative to the template folder of the binding."""
    path: str
    """The output path, relative to the output folder. A Jinja2 template."""
    for_each: ElementKind | None = None
    """The element kind to render the template for, or None to render it once."""
    extension: bool = False
    """True for an extension rule: the file is created once and never overwritten (ADR 0005)."""
    when: str | None = None
    """A Jinja2 expression. If it is false, the rule writes no file.

    For a rule with `for_each`, the generator evaluates the expression
    for each element, with the context of the element. Thus
    `when="element.kind == 'custom'"` writes a file only for the custom
    operations.
    """


@dataclass(frozen=True, slots=True)
class Binding:
    """A target stack that the generator writes code for.

    A binding declares its name, its templates, its output layout, and
    the element kinds that it covers. The generator marks each element
    of a kind that the binding does not cover as a generation gap.
    """

    name: str
    """The name that finds the binding, for example `nextjs`."""
    description: str
    template_dir: Path
    """The folder that holds the Jinja2 templates of the binding."""
    outputs: tuple[Output, ...]
    """The output layout: the rules that map templates to output files."""
    covers: frozenset[ElementKind]
    """The element kinds that the binding generates code for."""
    context: Callable[[AppDefinition], Mapping[str, Any]] | None = None
    """A function that returns more template values for a definition.

    The generator calls it once for each run, and adds the values to the
    context of all templates and output paths. Use it for data that is
    hard to compute in Jinja2, for example the TypeScript type of each
    field. The function must be deterministic, and it cannot replace a
    value of the generator, for example `definition` or `tokens`.
    """
    filters: Mapping[str, Callable[..., Any]] = field(
        default_factory=dict[str, Callable[..., Any]], hash=False, compare=False
    )
    """More Jinja2 filters for the templates and the output paths of the binding.

    All bindings have the naming filters of `appgen.gen.naming`, for example
    `camel` and `kebab`.
    """
    excludes: frozenset[ElementKind] = frozenset()
    """The element kinds that are out of the scope of the binding.

    The generator makes no gap for an element of an excluded kind, or for
    the elements under it. For example, a back-end binding excludes
    `page` and `ui`. The manifest records the kinds, and `appgen check`
    does not count these elements in the coverage.
    """
    gap_rule: Output | None = None
    """The extension file for each element of a kind that the binding does not cover.

    The generator renders the rule once for each gap element, as an
    extension file (ADR 0005). `for_each` and `extension` of the rule do
    not apply. Without a gap rule, the gaps are only listed.
    """
    helpers: Mapping[str, Callable[..., Any]] = field(
        default_factory=dict[str, Callable[..., Any]], hash=False, compare=False
    )
    """Python functions that the templates of the binding can call, by name.

    The generator adds them to the globals of the template environment,
    for example `{{ ts_type(field) }}`. A helper must be deterministic: it
    must not read a clock, random values, or files.
    """
