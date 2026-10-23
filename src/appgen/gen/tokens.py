"""Resolve the design tokens of a definition for the bindings (ADR 0003).

The Next.js and the React bindings both turn the tokens into a theme.
The generator resolves the references once, so that the bindings only
render the final values.
"""

import re
from dataclasses import dataclass

from pydantic import JsonValue

from appgen.dsl.model import AppDefinition
from appgen.dsl.ui import TokenTable
from appgen.dsl.ui.tokens import MODES, Mode, TokenType
from appgen.gen.render import GenerationError

_DIGITS = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class ResolvedToken:
    """A design token with the final value for each mode."""

    path: str
    """The path below `ui.tokens`, for example `color.primary`."""
    element_id: str
    """The element ID for traces, for example `ui.tokens.color.primary`."""
    group: str
    """The top-level group, for example `color`."""
    type: TokenType
    light: JsonValue
    dark: JsonValue
    light_refs: tuple[str, ...] = ()
    """The element IDs of the tokens that the light value refers to, in the order of resolution."""
    dark_refs: tuple[str, ...] = ()
    """The element IDs of the tokens that the dark value refers to, in the order of resolution."""

    def value(self, mode: Mode) -> JsonValue:
        """Return the final value in a mode."""
        return self.light if mode == "light" else self.dark

    def refs(self, mode: Mode) -> tuple[str, ...]:
        """Return the element IDs of the tokens that the value in a mode refers to."""
        return self.light_refs if mode == "light" else self.dark_refs


def token_sort_key(path: str) -> tuple[tuple[int, int, str], ...]:
    """Return a sort key that puts number steps in number order: `blue.50` before `blue.400`."""
    return tuple(
        (0, int(part), "") if _DIGITS.match(part) else (1, 0, part) for part in path.split(".")
    )


def resolve_tokens(definition: AppDefinition) -> list[ResolvedToken]:
    """Return the tokens of a definition with their final values, sorted by path.

    The list is flat: one entry for each token, none for the groups. A
    reference such as `{color.blue.600}` is replaced by the final value of
    its target, also through a chain of references and inside composite
    values (typography and shadows). Raise GenerationError for a reference
    to a token that does not exist, or for a loop of references. The
    validator reports these errors first, so a valid definition has none.
    """
    table = TokenTable.build(definition.ui.tokens if definition.ui else None)
    resolver = _Resolver(table)
    resolved: list[ResolvedToken] = []
    for path in sorted(table.tokens, key=token_sort_key):
        entry = table.tokens[path]
        values: dict[Mode, tuple[JsonValue, tuple[str, ...]]] = {}
        for mode in MODES:
            refs: list[str] = []
            value = resolver.value(entry.token.mode_value(mode), mode, refs, (path,))
            values[mode] = (value, tuple(refs))
        resolved.append(
            ResolvedToken(
                path=path,
                element_id=entry.element_id,
                group=entry.group,
                type=entry.type,
                light=values["light"][0],
                dark=values["dark"][0],
                light_refs=values["light"][1],
                dark_refs=values["dark"][1],
            )
        )
    return resolved


class _Resolver:
    def __init__(self, table: TokenTable) -> None:
        self.table = table

    def value(
        self, value: JsonValue, mode: Mode, refs: list[str], stack: tuple[str, ...]
    ) -> JsonValue:
        if isinstance(value, str) and (target := self.table.reference_target(value)):
            entry = self.table.tokens.get(target)
            if entry is None:
                raise GenerationError(
                    f"The token 'ui.tokens.{stack[-1]}' refers to '{target}', which is not a token."
                )
            if target in stack:
                loop = " -> ".join((*stack, target))
                raise GenerationError(f"The tokens have a loop of references: {loop}.")
            if entry.element_id not in refs:
                refs.append(entry.element_id)
            return self.value(entry.token.mode_value(mode), mode, refs, (*stack, target))
        if isinstance(value, dict):
            return {key: self.value(item, mode, refs, stack) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item, mode, refs, stack) for item in value]
        return value
