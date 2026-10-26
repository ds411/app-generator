"""The rules of an entity: checks over more than one field, or over more than one record."""

from typing import Annotated, Literal

import pydantic
from pydantic import Discriminator, StringConstraints, Tag

from appgen.dsl.element import Element, MemberName, Text
from appgen.dsl.ui.common import kind_tag
from appgen.dsl.ui.forms import CompareOp

TOTAL_OPERAND_PATTERN = r"^(count|sum|avg|min|max)\(\s*[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?\s*\)$"
"""A total of the lines of a record in a compare rule, for example `sum(lines.debit)`."""

type CompareOperand = Annotated[
    str, StringConstraints(pattern=rf"^[a-z][a-z0-9_]*$|{TOTAL_OPERAND_PATTERN}")
]
"""A side of a compare rule: a field, or a total of the lines of the record (ADR 0034)."""


def is_total_operand(operand: str) -> bool:
    """Return True if a side of a compare rule is a total, for example `count(lines)`."""
    return "(" in operand


class EntityCompareRule(Element):
    """A rule that compares two values of a record, for example `ends_at` after `starts_at`.

    A value is a field, or a total of the lines of the record, for example
    `sum(lines.debit)`: the apps check a rule with a total after they write
    the lines (ADR 0034).
    """

    kind: Literal["compare"]
    field: CompareOperand
    op: CompareOp
    other: CompareOperand
    message: Text

    @property
    def totals(self) -> list[str]:
        """Return the sides of the rule that are totals."""
        return [side for side in (self.field, self.other) if is_total_operand(side)]


class EntityUniqueRule(Element):
    """A rule that no two records have the same values in a set of fields and relations."""

    kind: Literal["unique"]
    fields: Annotated[list[MemberName], pydantic.Field(min_length=2)]
    """Fields, and `many_to_one` or `one_to_one` relations (their foreign keys)."""
    message: Text | None = None


class EntityOverlapRule(Element):
    """A rule that the time ranges of two records with the same scope do not overlap."""

    kind: Literal["no_overlap"]
    start: MemberName
    end: MemberName
    scope: list[MemberName] = pydantic.Field(default_factory=list[str])
    """Fields and relations: only records with the same values must not overlap."""
    message: Text


type EntityRule = Annotated[
    Annotated[EntityCompareRule, Tag("tag-compare")]
    | Annotated[EntityUniqueRule, Tag("tag-unique")]
    | Annotated[EntityOverlapRule, Tag("tag-no_overlap")],
    Discriminator(kind_tag),
]
