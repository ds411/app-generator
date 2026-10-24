"""The rules of an entity: checks over more than one field, or over more than one record."""

from typing import Annotated, Literal

import pydantic
from pydantic import Discriminator, Tag

from appgen.dsl.element import Element, MemberName, Text
from appgen.dsl.ui.common import kind_tag
from appgen.dsl.ui.forms import CompareOp


class EntityCompareRule(Element):
    """A rule that compares two fields of a record, for example `ends_at` after `starts_at`."""

    kind: Literal["compare"]
    field: MemberName
    op: CompareOp
    other: MemberName
    message: Text


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
