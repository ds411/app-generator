"""Design tokens: the model, the token table, and the token checks (ADR 0003).

The tokens follow the format of the W3C Design Tokens Community Group
where it fits. A token is a mapping with `$value`. A group is a mapping
without `$value`. Each top-level group of `ui.tokens` sets the type of
its tokens.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Literal

import pydantic
from pydantic import ConfigDict, Discriminator, JsonValue, Tag

from appgen.dsl.diagnostics import Diagnostic, Location
from appgen.dsl.element import Element, Text

TOKEN_NAME_PATTERN = r"^[a-z0-9][a-z0-9_]*$"
"""The rule for the name of a token or a group. A scale step can be a number."""

TOKEN_REFERENCE_PATTERN = r"^\{([a-z0-9][a-z0-9_]*(?:\.[a-z0-9][a-z0-9_]*)*)\}$"
"""A reference to a token: the token path below `ui.tokens`, in braces."""

type TokenType = Literal[
    "color",
    "dimension",
    "fontFamily",
    "fontWeight",
    "number",
    "duration",
    "typography",
    "shadow",
]
type Mode = Literal["light", "dark"]

MODES: tuple[Mode, ...] = ("light", "dark")

GROUP_TYPES: dict[str, TokenType] = {
    "color": "color",
    "font_family": "fontFamily",
    "font_size": "dimension",
    "font_weight": "fontWeight",
    "line_height": "number",
    "letter_spacing": "dimension",
    "typography": "typography",
    "spacing": "dimension",
    "size": "dimension",
    "radius": "dimension",
    "shadow": "shadow",
    "breakpoint": "dimension",
    "duration": "duration",
}
"""The top-level token groups, and the type of the tokens in each group."""

_DIMENSION_UNITS: dict[str, tuple[str, ...]] = {
    "font_size": ("px", "rem"),
    "letter_spacing": ("px", "rem", "em"),
    "spacing": ("px", "rem"),
    "size": ("px", "rem"),
    "radius": ("px", "rem"),
    "breakpoint": ("px",),
}
_SHADOW_UNITS = ("px", "rem")
_TYPOGRAPHY_MEMBERS: dict[str, TokenType] = {
    "font_family": "fontFamily",
    "font_size": "dimension",
    "font_weight": "fontWeight",
    "line_height": "number",
    "letter_spacing": "dimension",
}
_TYPOGRAPHY_OPTIONAL = frozenset({"letter_spacing"})
_SHADOW_MEMBERS: dict[str, TokenType] = {
    "color": "color",
    "offset_x": "dimension",
    "offset_y": "dimension",
    "blur": "dimension",
    "spread": "dimension",
}
_COLOR = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$|^(?:oklch|rgb|hsl)\([^()]*\)$"
)
_DURATION = re.compile(r"^\d+(?:\.\d+)?ms$")
_REFERENCE = re.compile(TOKEN_REFERENCE_PATTERN)
_NAME = re.compile(TOKEN_NAME_PATTERN)
_KNOWN_DOLLAR_KEYS = "$value, $type, $description, $modes"


class Token(Element):
    """A design token: a named value, with an optional value for each mode."""

    value: JsonValue = pydantic.Field(alias="$value")
    type: TokenType | None = pydantic.Field(default=None, alias="$type")
    description: Text | None = pydantic.Field(default=None, alias="$description")
    modes: dict[Mode, JsonValue] = pydantic.Field(
        default_factory=dict[Mode, JsonValue], alias="$modes"
    )

    def mode_value(self, mode: Mode) -> JsonValue:
        """Return the value of the token in a mode."""
        return self.modes.get(mode, self.value)


def _node_tag(value: object) -> str:
    return "tag-token" if isinstance(value, dict) and "$value" in value else "tag-group"


type TokenNode = Annotated[
    Annotated[Token, Tag("tag-token")] | Annotated[TokenGroup, Tag("tag-group")],
    Discriminator(_node_tag),
]
"""A token or a group. A mapping with `$value` is a token."""


class TokenGroup(Element):
    """A group of tokens and groups. The keys that do not start with `$` are names."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, TokenNode] = pydantic.Field(init=False)  # pyright: ignore[reportIncompatibleVariableOverride]

    type: TokenType | None = pydantic.Field(default=None, alias="$type")
    description: Text | None = pydantic.Field(default=None, alias="$description")

    @property
    def children(self) -> dict[str, Token | TokenGroup]:
        """The tokens and groups in this group, in source order."""
        return dict(self.__pydantic_extra__)


class Motion(Element):
    """The motion of the UI: the animations of charts, dialogs, menus, and transitions.

    `full` keeps all animations. `reduced` stops them for users who ask
    their system for reduced motion. `none` stops them for all users.
    """

    value: Literal["full", "reduced", "none"] = pydantic.Field(alias="$value")
    description: Text | None = pydantic.Field(default=None, alias="$description")


class Tokens(Element):
    """The design tokens of the app: one group for each kind of token."""

    color: TokenGroup | None = None
    font_family: TokenGroup | None = None
    font_size: TokenGroup | None = None
    font_weight: TokenGroup | None = None
    line_height: TokenGroup | None = None
    letter_spacing: TokenGroup | None = None
    typography: TokenGroup | None = None
    spacing: TokenGroup | None = None
    size: TokenGroup | None = None
    radius: TokenGroup | None = None
    shadow: TokenGroup | None = None
    breakpoint: TokenGroup | None = None
    duration: TokenGroup | None = None
    motion: Motion | None = None


@dataclass(frozen=True, slots=True)
class TokenEntry:
    """A token in the token table."""

    path: str
    """The path below `ui.tokens`, for example `color.primary`."""
    group: str
    """The top-level group, for example `color`."""
    type: TokenType
    token: Token

    @property
    def element_id(self) -> str:
        return f"ui.tokens.{self.path}"


@dataclass(slots=True)
class TokenTable:
    """All tokens and groups of a definition, by path."""

    tokens: dict[str, TokenEntry] = field(default_factory=dict[str, TokenEntry])
    groups: dict[str, TokenGroup] = field(default_factory=dict[str, TokenGroup])

    @classmethod
    def build(cls, tokens: Tokens | None) -> TokenTable:
        table = cls()
        if tokens is None:
            return table
        for group_name, token_type in GROUP_TYPES.items():
            group = getattr(tokens, group_name)
            if isinstance(group, TokenGroup):
                table._add_group(group_name, group_name, token_type, group)
        return table

    def _add_group(self, path: str, top: str, token_type: TokenType, group: TokenGroup) -> None:
        self.groups[path] = group
        for name, child in group.children.items():
            child_path = f"{path}.{name}"
            if isinstance(child, Token):
                self.tokens[child_path] = TokenEntry(child_path, top, token_type, child)
            else:
                self._add_group(child_path, top, token_type, child)

    def reference_target(self, reference: str) -> str | None:
        """Return the path in a reference such as `{color.primary}`, or None."""
        match = _REFERENCE.match(reference)
        return match.group(1) if match else None

    def resolve(self, path: str, mode: Mode) -> JsonValue:
        """Return the final value of a token in a mode. The tokens must be valid."""
        value = self.tokens[path].token.mode_value(mode)
        return self._resolve_value(value, mode)

    def _resolve_value(self, value: JsonValue, mode: Mode) -> JsonValue:
        if isinstance(value, str) and (target := self.reference_target(value)):
            return self.resolve(target, mode)
        if isinstance(value, dict):
            return {key: self._resolve_value(item, mode) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(item, mode) for item in value]
        return value


def check_tokens(tokens: Tokens | None) -> list[Diagnostic]:
    """Check the names, types, values, and references of the design tokens."""
    if tokens is None:
        return []
    return _TokenChecker(TokenTable.build(tokens)).run()


class _TokenChecker:
    def __init__(self, table: TokenTable) -> None:
        self.table = table
        self.diagnostics: list[Diagnostic] = []
        self.references: dict[str, list[str]] = {}

    def run(self) -> list[Diagnostic]:
        for path, group in self.table.groups.items():
            self._check_group(path, group)
        for entry in self.table.tokens.values():
            self._check_token(entry)
        self._check_loops()
        return self.diagnostics

    def _error(
        self,
        code: str,
        message: str,
        element: Element,
        element_id: str,
        *,
        at: str | None = None,
        hint: str | None = None,
    ) -> None:
        location = element.location_of(at) if at else element.location
        self.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                location=location or Location("<unknown>", 1, 1),
                element_id=element.id or element_id,
                hint=hint,
            )
        )

    def _check_group(self, path: str, group: TokenGroup) -> None:
        top = path.split(".")[0]
        if group.type is not None and group.type != GROUP_TYPES[top]:
            self._error(
                "token-type-mismatch",
                f"The group '{path}' has the type '{group.type}', "
                f"but the tokens in '{top}' have the type '{GROUP_TYPES[top]}'.",
                group,
                f"ui.tokens.{path}",
                at="$type",
            )
        for name, child in group.children.items():
            if not _NAME.match(name):
                hint = (
                    f"The known keys that start with '$' are {_KNOWN_DOLLAR_KEYS}."
                    if name.startswith("$")
                    else None
                )
                self._error(
                    "invalid-name",
                    f"The token name '{name}' does not match the pattern {TOKEN_NAME_PATTERN}.",
                    child,
                    f"ui.tokens.{path}.{name}",
                    hint=hint,
                )

    def _check_token(self, entry: TokenEntry) -> None:
        token = entry.token
        if token.type is not None and token.type != entry.type:
            self._error(
                "token-type-mismatch",
                f"The token has the type '{token.type}', "
                f"but the tokens in '{entry.group}' have the type '{entry.type}'.",
                token,
                entry.element_id,
            )
        self.references[entry.path] = []
        values: list[tuple[str, JsonValue]] = [("$value", token.value)]
        values += [(f"$modes.{mode}", value) for mode, value in token.modes.items()]
        for where, value in values:
            for problem in self._value_problems(entry, value):
                self._error(
                    "invalid-token-value",
                    f"{where}: {problem}",
                    token,
                    entry.element_id,
                    at=where.partition(".")[0],
                )

    def _value_problems(self, entry: TokenEntry, value: JsonValue) -> Iterator[str]:
        """Yield the problems of a token value. Record the references."""
        if isinstance(value, str) and value.startswith("{"):
            yield from self._reference_problems(entry, value, entry.type)
            return
        match entry.type:
            case "typography":
                yield from self._composite_problems(
                    entry, value, _TYPOGRAPHY_MEMBERS, _TYPOGRAPHY_OPTIONAL
                )
            case "shadow":
                layers = value if isinstance(value, list) and value else [value]
                for layer in layers:
                    yield from self._composite_problems(
                        entry, layer, _SHADOW_MEMBERS, frozenset(), extra={"inset"}
                    )
            case _:
                problem = _literal_problem(entry.type, entry.group, value)
                if problem:
                    yield problem

    def _composite_problems(
        self,
        entry: TokenEntry,
        value: JsonValue,
        members: dict[str, TokenType],
        optional: frozenset[str],
        extra: set[str] | None = None,
    ) -> Iterator[str]:
        if not isinstance(value, dict):
            yield f"A {entry.type} value must be a mapping with the keys {', '.join(members)}."
            return
        extra = extra or set()
        for key in value:
            if key not in members and key not in extra:
                yield f"The key '{key}' is not known in a {entry.type} value."
        for key, member_type in members.items():
            if key not in value:
                if key not in optional:
                    yield f"The key '{key}' is missing in the {entry.type} value."
                continue
            member = value[key]
            if isinstance(member, str) and member.startswith("{"):
                yield from self._reference_problems(entry, member, member_type)
                continue
            group = key if member_type == "dimension" and key in _DIMENSION_UNITS else None
            problem = _literal_problem(member_type, group, member)
            if problem:
                yield f"{key}: {problem}"
        if "inset" in value and not isinstance(value["inset"], bool):
            yield "inset: Expected true or false."

    def _reference_problems(
        self, entry: TokenEntry, reference: str, expected: TokenType
    ) -> Iterator[str]:
        target = self.table.reference_target(reference)
        if target is None:
            yield f"The reference {reference!r} is not valid. Write a token path in braces."
            return
        if target in self.table.groups:
            yield f"The reference {reference!r} refers to a group, not to a token."
            return
        found = self.table.tokens.get(target)
        if found is None:
            yield f"The token '{target}' does not exist."
            return
        self.references[entry.path].append(target)
        if found.type != expected:
            yield (
                f"The reference {reference!r} refers to a token of the type '{found.type}', "
                f"but this value needs the type '{expected}'."
            )

    def _check_loops(self) -> None:
        state: dict[str, int] = {}  # 1: on the stack, 2: done
        stack: list[str] = []
        reported: set[frozenset[str]] = set()

        def visit(path: str) -> None:
            state[path] = 1
            stack.append(path)
            for target in self.references.get(path, []):
                if state.get(target) == 1:
                    loop = stack[stack.index(target) :]
                    if frozenset(loop) not in reported:
                        reported.add(frozenset(loop))
                        entry = self.table.tokens[loop[0]]
                        chain = " -> ".join([*loop, loop[0]])
                        self._error(
                            "token-loop",
                            f"The tokens refer to each other in a loop: {chain}.",
                            entry.token,
                            entry.element_id,
                        )
                elif target not in state:
                    visit(target)
            stack.pop()
            state[path] = 2

        for path in self.references:
            if path not in state:
                visit(path)


def _literal_problem(token_type: TokenType, group: str | None, value: JsonValue) -> str | None:
    """Return the problem of a literal value of a type, or None."""
    match token_type:
        case "color":
            if isinstance(value, str) and _COLOR.match(value):
                return None
            return f"The value {value!r} is not a color. Write #rrggbb, or oklch(), rgb(), hsl()."
        case "dimension":
            units = _DIMENSION_UNITS.get(group or "", _SHADOW_UNITS)
            if value == 0 and not isinstance(value, bool):
                return None
            if isinstance(value, str) and re.fullmatch(
                rf"-?\d+(?:\.\d+)?(?:{'|'.join(units)})", value
            ):
                return None
            return (
                f"The value {value!r} is not a dimension. Write a number with {', '.join(units)}."
            )
        case "fontFamily":
            if isinstance(value, str) and value:
                return None
            if (
                isinstance(value, list)
                and value
                and all(isinstance(item, str) and item for item in value)
            ):
                return None
            return f"The value {value!r} is not a font family. Write a name or a list of names."
        case "fontWeight":
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000:
                return None
            return f"The value {value!r} is not a font weight. Write an integer from 1 to 1000."
        case "number":
            if isinstance(value, int | float) and not isinstance(value, bool):
                return None
            return f"The value {value!r} is not a number."
        case "duration":
            if isinstance(value, str) and _DURATION.match(value):
                return None
            return f"The value {value!r} is not a duration. Write a number with ms."
        case "typography" | "shadow":
            return f"The value {value!r} is not a {token_type} value."
