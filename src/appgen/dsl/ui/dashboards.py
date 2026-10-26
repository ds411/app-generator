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


def single_value(record_filter: RecordFilter, path: str) -> str | None:
    """Return the one text that a filter allows for a field path, or None.

    The condition is the text, `{eq: <text>}`, or `{in: [<text>]}`. A stat
    of an amount with a currency field shows the currency of this value.
    """
    condition = record_filter.get(path)
    if isinstance(condition, dict):
        if set(condition) == {"eq"}:
            condition = condition["eq"]
        elif set(condition) == {"in"} and isinstance(condition["in"], list):
            values = condition["in"]
            condition = values[0] if len(values) == 1 else None
    return condition if isinstance(condition, str) else None


def currency_path(field_path: str, currency_field: str) -> str:
    """Return the path of the currency field of an amount, from the entity of the amount path.

    The currency field is a path from the entity of the amount: for the
    amount `invoice.total` and the currency field `customer.currency`, the
    result is `invoice.customer.currency`.
    """
    prefix = field_path.rpartition(".")[0]
    return f"{prefix}.{currency_field}" if prefix else currency_field


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
    format: Literal["number", "currency", "percent"] | None = None
    """The default is the format of the field (for an aggregate of a field), else `number`."""
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
    interval: Literal["day", "week", "month", "year"] = "month"
    """The interval of each group of a date or a date-time field."""
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
