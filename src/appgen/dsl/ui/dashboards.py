"""Dashboards: stat tiles, charts, and record lists on a grid (ADR 0003)."""

from typing import Annotated, Literal

import pydantic
from pydantic import Discriminator, JsonValue, Tag

from appgen.dsl.element import Element, EntityName, MemberName, Text
from appgen.dsl.ui.common import FieldPath, Grid, IconName, TokenRef, kind_tag
from appgen.dsl.ui.views import Sort

type Aggregate = Literal["count", "sum", "avg", "min", "max"]
type FilterOp = Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"]

FILTER_OPS: tuple[str, ...] = FilterOp.__value__.__args__
RELATIVE_DATES = ("$today", "$now")

type RecordFilter = dict[FieldPath, JsonValue]
"""A mapping from a field path to a value (equal to), or to a mapping of operators.

A value is a literal, or `$today` or `$now` for a date.
"""


class WidgetBase(Element):
    """The keys of all widgets."""

    label: Text | None = None
    span: Annotated[int, pydantic.Field(ge=1, le=12)] = 1
    """The number of grid columns."""


class StatWidget(WidgetBase):
    """A stat tile: a count or another aggregate of records."""

    kind: Literal["stat"]
    entity: EntityName
    aggregate: Aggregate = "count"
    field: FieldPath | None = None
    """A number field. Not for `count`."""
    filter: RecordFilter = pydantic.Field(default_factory=dict[str, JsonValue])
    format: Literal["number", "currency", "percent"] = "number"
    icon: IconName | None = None
    color: TokenRef | None = None
    """A color token."""
    link: MemberName | None = None
    """A page that the tile opens."""


class ChartWidget(WidgetBase):
    """A chart of an aggregate for each group of records."""

    kind: Literal["chart"]
    chart: Literal["bar", "line", "donut"]
    entity: EntityName
    group_by: FieldPath
    """An enum, date, or relation field."""
    aggregate: Aggregate = "count"
    field: FieldPath | None = None
    filter: RecordFilter = pydantic.Field(default_factory=dict[str, JsonValue])
    badge: MemberName | None = None
    """A badge set that gives the colors of the groups."""


class ListWidget(WidgetBase):
    """A short list of records in a table or a card list."""

    kind: Literal["list"]
    view: MemberName
    filter: RecordFilter = pydantic.Field(default_factory=dict[str, JsonValue])
    sort: Sort | None = None
    limit: Annotated[int, pydantic.Field(ge=1)] = 5
    link: MemberName | None = None
    """A page for "View all"."""


class CustomWidget(WidgetBase):
    """A widget that hand-written code gives (a generation gap)."""

    kind: Literal["custom"]


type Widget = Annotated[
    Annotated[StatWidget, Tag("tag-stat")]
    | Annotated[ChartWidget, Tag("tag-chart")]
    | Annotated[ListWidget, Tag("tag-list")]
    | Annotated[CustomWidget, Tag("tag-custom")],
    Discriminator(kind_tag),
]


class Dashboard(Element):
    """Widgets on a grid."""

    title: Text | None = None
    description: Text | None = None
    grid: Grid | None = None
    widgets: Annotated[dict[MemberName, Widget], pydantic.Field(min_length=1)]
