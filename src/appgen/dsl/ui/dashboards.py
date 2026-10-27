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

A value is a literal, `$today` or `$now` for a date, or `$me` for the signed-in user (a
relation to the user entity).
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


type PeriodRange = Literal[
    "today",
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "last_365_days",
    "this_week",
    "this_month",
    "this_year",
    "last_week",
    "last_month",
    "last_year",
    "all",
    "custom",
]
"""A range of the period of a dashboard. `this_*` ends today, `last_week`, `last_month`, and
`last_year` are the whole unit before, `all` has no limits, and `custom` lets the user pick
the first and the last day."""

PERIOD_RANGES: tuple[str, ...] = PeriodRange.__value__.__args__
DEFAULT_RANGES: tuple[PeriodRange, ...] = (
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_month",
    "last_month",
    "this_year",
    "all",
)
"""The ranges of a period without `ranges`."""


class DashboardPeriod(Element):
    """The period of a dashboard: the user picks a range, and the widgets with a
    `period_field` show the records of the range."""

    default: PeriodRange = "last_30_days"
    ranges: Annotated[list[PeriodRange], pydantic.Field(min_length=1)] = pydantic.Field(
        default_factory=lambda: list(DEFAULT_RANGES)
    )
    """The ranges that the picker offers, in their order."""


class WidgetBase(Element):
    """The keys of all widgets."""

    label: Text | None = None
    span: Annotated[int, pydantic.Field(ge=1, le=12)] = 1
    """The number of grid columns."""


class PeriodWidget(WidgetBase):
    """The keys of the widgets that can show the records of the period of the dashboard."""

    period_field: MemberName | None = None
    """A date or a date-time field of the entity: the widget shows the records whose value is
    in the period of the dashboard."""


class StatWidget(PeriodWidget):
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
    compare: Literal["previous"] | None = None
    """`previous` shows the change from the period of the same length before the period."""
    snapshots: Literal["daily"] | None = None
    """`daily`: a job stores the value each day, for a line chart (ADR 0042)."""


class ChartWidget(PeriodWidget):
    """A chart of an aggregate for each group of records, or of the daily values of a stat."""

    kind: Literal["chart"]
    chart: Literal["bar", "line", "donut"]
    entity: EntityName | None = None
    """The entity of the records. Not with `snapshots`."""
    group_by: FieldPath | None = None
    """An enum, date, or relation field. Not with `snapshots`."""
    interval: Literal["day", "week", "month", "year"] = "month"
    """The interval of each group of a date or a date-time field."""
    aggregate: Aggregate = "count"
    field: FieldPath | None = None
    filter: RecordFilter = pydantic.Field(default_factory=dict[str, JsonValue])
    badge: MemberName | None = None
    """A badge set that gives the colors of the groups."""
    snapshots: MemberName | None = None
    """A stat widget of the dashboard with `snapshots: daily`: the line chart shows its daily
    values (ADR 0042)."""
    days: Annotated[int, pydantic.Field(ge=2, le=366)] = 30
    """With `snapshots`: the count of days that the chart shows, up to today."""


class ListWidget(PeriodWidget):
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
    period: DashboardPeriod | None = None
    """The period that the user picks for the widgets with a `period_field`."""
    widgets: Annotated[dict[MemberName, Widget], pydantic.Field(min_length=1)]
