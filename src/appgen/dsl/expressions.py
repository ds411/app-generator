"""The expressions of computed fields: a small language of numbers and field paths.

An expression has numbers, field paths, the operators `+`, `-`, `*`, and
`/`, parentheses, the functions `hours(start, end)` and
`days(start, end)`, which give the time between two dates or date-times,
and the totals of a relation to many records: `count(<relation>)`, and
`sum`, `avg`, `min`, and `max` of `<relation>.<field>`. The bindings
write each expression in their language, so that an expression has the
same value in each app. An empty operand gives an empty value. A total
of no records is 0 for `count` and `sum`, and empty for the others.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

FUNCTIONS: dict[str, int] = {"hours": 2, "days": 2}
"""The functions of the expressions, with their number of arguments."""
TOTALS: tuple[str, ...] = ("count", "sum", "avg", "min", "max")
"""The functions of the totals of a relation: `count(<relation>)`, `sum(<relation>.<field>)`."""

_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+(?:\.\d+)?)|(?P<name>[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)"
    r"|(?P<op>[-+*/(),]))"
)


class ExpressionError(ValueError):
    """An expression that does not parse."""


@dataclass(frozen=True, slots=True)
class Number:
    """A number literal, as it is in the text."""

    value: str


@dataclass(frozen=True, slots=True)
class FieldRef:
    """A field path, from the entity of the computed field."""

    path: str


@dataclass(frozen=True, slots=True)
class Call:
    """A call of a function, for example `hours(starts_at, ends_at)`."""

    name: str
    args: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class Total:
    """A total of the records of a relation, for example `sum(lines.amount)` or `count(votes)`."""

    function: str
    relation: str
    field: str | None = None
    """The number field of the related records. None for `count`."""

    def __str__(self) -> str:
        path = self.relation if self.field is None else f"{self.relation}.{self.field}"
        return f"{self.function}({path})"


@dataclass(frozen=True, slots=True)
class Binary:
    """An operation on two operands: `+`, `-`, `*`, or `/`."""

    op: str
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class Negate:
    """The negative of an operand."""

    operand: Expression


type Expression = Number | FieldRef | Call | Total | Binary | Negate


def parse_expression(text: str) -> Expression:
    """Parse an expression. Raise ExpressionError if it is not valid."""
    tokens = _tokens(text)
    parser = _Parser(tokens)
    expression = parser.sum()
    if parser.position < len(tokens):
        raise ExpressionError(f"Unexpected '{tokens[parser.position][1]}'.")
    return expression


def expression_paths(expression: Expression) -> Iterator[str]:
    """Yield the field paths of the record in an expression, in source order.

    The paths of the totals are not paths of the record: `expression_totals` gives them.
    """
    match expression:
        case FieldRef(path):
            yield path
        case Call(_, args):
            for arg in args:
                yield from expression_paths(arg)
        case Binary(_, left, right):
            yield from expression_paths(left)
            yield from expression_paths(right)
        case Negate(operand):
            yield from expression_paths(operand)
        case Number() | Total():
            pass


def expression_totals(expression: Expression) -> Iterator[Total]:
    """Yield the totals of an expression, in source order."""
    match expression:
        case Total():
            yield expression
        case Binary(_, left, right):
            yield from expression_totals(left)
            yield from expression_totals(right)
        case Negate(operand):
            yield from expression_totals(operand)
        case Number() | FieldRef() | Call():
            pass


def date_paths(expression: Expression) -> Iterator[str]:
    """Yield the field paths that are arguments of a time function (dates or date-times)."""
    match expression:
        case Call(_, args):
            for arg in args:
                if isinstance(arg, FieldRef):
                    yield arg.path
                else:
                    yield from date_paths(arg)
        case Binary(_, left, right):
            yield from date_paths(left)
            yield from date_paths(right)
        case Negate(operand):
            yield from date_paths(operand)
        case Number() | FieldRef() | Total():
            pass


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    text = text.rstrip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise ExpressionError(f"Unexpected '{text[position:].strip()[:1]}'.")
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        position = match.end()
    if not tokens:
        raise ExpressionError("The expression is empty.")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position][1] if self.position < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        if self.position >= len(self.tokens):
            raise ExpressionError("The expression ends too early.")
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expect(self, value: str) -> None:
        kind, found = self.take()
        if (kind, found) != ("op", value):
            raise ExpressionError(f"Expected '{value}', not '{found}'.")

    def sum(self) -> Expression:
        result = self.product()
        while self.peek() in ("+", "-"):
            op = self.take()[1]
            result = Binary(op, result, self.product())
        return result

    def product(self) -> Expression:
        result = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()[1]
            result = Binary(op, result, self.unary())
        return result

    def unary(self) -> Expression:
        if self.peek() == "-":
            self.take()
            return Negate(self.unary())
        return self.atom()

    def atom(self) -> Expression:
        kind, value = self.take()
        if kind == "number":
            return Number(value)
        if kind == "name":
            if self.peek() != "(":
                return FieldRef(value)
            if value in TOTALS:
                return self.total(value)
            if value not in FUNCTIONS:
                names = ", ".join(f"'{name}'" for name in [*FUNCTIONS, *TOTALS])
                raise ExpressionError(f"Unknown function '{value}'. The functions are {names}.")
            self.take()
            args = [self.sum()]
            while self.peek() == ",":
                self.take()
                args.append(self.sum())
            self.expect(")")
            if len(args) != FUNCTIONS[value]:
                raise ExpressionError(
                    f"The function '{value}' takes {FUNCTIONS[value]} arguments, not {len(args)}."
                )
            return Call(value, tuple(args))
        if value == "(":
            inner = self.sum()
            self.expect(")")
            return inner
        raise ExpressionError(f"Unexpected '{value}'.")

    def total(self, function: str) -> Total:
        """Parse the argument of a total: a relation, or a field of a relation."""
        self.take()
        kind, path = self.take()
        segments = path.split(".")
        if function == "count":
            if kind != "name" or len(segments) != 1:
                raise ExpressionError(
                    f"The function 'count' takes a relation, not '{path}', for example "
                    "count(lines)."
                )
        elif kind != "name" or len(segments) != 2:
            raise ExpressionError(
                f"The function '{function}' takes a field of a relation, not '{path}', for "
                f"example {function}(lines.amount)."
            )
        self.expect(")")
        return Total(function, segments[0], segments[1] if len(segments) == 2 else None)
