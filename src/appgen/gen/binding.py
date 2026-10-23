"""The binding contract: what a binding declares to plug into the generator."""

from dataclasses import dataclass
from pathlib import Path

type ElementKind = str
"""The kind of a definition element, for example `entity` or `field`.

The kinds of DSL version 0 are `app`, `entity`, `field`, `relation`,
`operation`, `param`, and `page`. See `appgen.gen.elements`.
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
