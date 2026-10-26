"""Badges and views: tables, card lists, boards, and detail views (ADR 0003)."""

from typing import Annotated, Any, Literal, Self

import pydantic
from pydantic import Discriminator, StringConstraints, Tag, model_validator
from pydantic_core import PydanticCustomError

from appgen.dsl.apis import OPERATION_ID_PATTERN
from appgen.dsl.element import (
    ENTITY_NAME_PATTERN,
    MEMBER_NAME_PATTERN,
    Element,
    EntityName,
    MemberName,
    Text,
)
from appgen.dsl.ui.common import (
    Action,
    BreakpointName,
    FieldPath,
    Grid,
    IconName,
    States,
    TokenRef,
    kind_tag,
)

type FieldRef = Annotated[
    str,
    StringConstraints(pattern=ENTITY_NAME_PATTERN[:-1] + r"\." + MEMBER_NAME_PATTERN[1:]),
]
"""A field of an entity, for example `Task.status`."""

PROPERTY_PATH_PATTERN = r"^[^.\s]+(?:\.[^.\s]+)*$"
type PropertyPath = Annotated[str, StringConstraints(pattern=PROPERTY_PATH_PATTERN)]
"""A property of an API answer, with a dot between nested properties, for example `address.city`."""

API_SOURCE_PATTERN = r"^apis\.[a-z][a-z0-9_]*\.operations\." + OPERATION_ID_PATTERN[1:]
type ApiSource = Annotated[str, StringConstraints(pattern=API_SOURCE_PATTERN)]
"""An operation of a third-party API, for example `apis.holidays.operations.getPublicHolidays`."""

type Format = Literal[
    "text",
    "number",
    "currency",
    "percent",
    "date",
    "datetime",
    "relative_time",
    "boolean",
    "badge",
    "email",
    "url",
    "avatar",
]
type Direction = Literal["asc", "desc"]
type JsonScalar = str | int | float | bool | None


class BadgeValue(Element):
    """The look of one enum value."""

    label: Text | None = None
    color: TokenRef | None = None
    """A color token."""
    icon: IconName | None = None


class BadgeSet(Element):
    """A label, a color, and an icon for each value of an enum field."""

    field: FieldRef
    values: dict[MemberName, BadgeValue] = pydantic.Field(default_factory=dict[str, BadgeValue])


class BadgeRef(Element):
    """A field that shows as a badge."""

    field: FieldPath
    badge: MemberName | None = None
    """A badge set. Without it, the badge shows the value and the default color."""


class Sort(Element):
    """A sort order."""

    field: FieldPath
    direction: Direction = "asc"


class Pagination(Element):
    """The pages of a list."""

    page_size: Annotated[int, pydantic.Field(ge=1)] | None = None
    """The default comes from `ui.defaults.page_size`."""
    page_sizes: list[Annotated[int, pydantic.Field(ge=1)]] = pydantic.Field(
        default_factory=list[int]
    )


class Column(Element):
    """A column of a table."""

    field: FieldPath | None = None
    """The default is the column name."""
    label: Text | None = None
    format: Format | None = None
    """The default comes from the field type."""
    badge: MemberName | None = None
    width: TokenRef | None = None
    """A size token."""
    align: Literal["start", "center", "end"] = "start"
    sortable: bool = True
    link: MemberName | None = None
    """A page that the cell opens, with the ID of the record."""
    hide_below: BreakpointName | None = None
    """The column hides on screens narrower than this breakpoint."""


class FilterBase(Element):
    label: Text | None = None
    default: JsonScalar | list[JsonScalar] = None


class SearchFilter(FilterBase):
    """A text search in one or more fields."""

    kind: Literal["search"]
    fields: Annotated[list[FieldPath], pydantic.Field(min_length=1)]


class SelectFilter(FilterBase):
    """A choice of enum values or related records."""

    kind: Literal["select"]
    field: FieldPath
    multiple: bool = False


class BooleanFilter(FilterBase):
    """A yes or no filter on a boolean field."""

    kind: Literal["boolean"]
    field: FieldPath


class DateRangeFilter(FilterBase):
    """A range of dates."""

    kind: Literal["date_range"]
    field: FieldPath


type Filter = Annotated[
    Annotated[SearchFilter, Tag("tag-search")]
    | Annotated[SelectFilter, Tag("tag-select")]
    | Annotated[BooleanFilter, Tag("tag-boolean")]
    | Annotated[DateRangeFilter, Tag("tag-date_range")],
    Discriminator(kind_tag),
]


class Card(Element):
    """The content of a card in a card list or a board."""

    title: FieldPath | None = None
    """The default is the display field of the entity."""
    subtitle: FieldPath | None = None
    badge: BadgeRef | None = None
    image: FieldPath | None = None
    """An `image` field: the cover image at the top of the card."""
    fields: list[FieldPath] = pydantic.Field(default_factory=list[str])
    footer: list[FieldPath] = pydantic.Field(default_factory=list[str])


class BoardColumn(Element):
    """The look of a column of a board: one enum value."""

    label: Text | None = None
    color: TokenRef | None = None
    limit: Annotated[int, pydantic.Field(ge=1)] | None = None
    """A work in progress limit."""


class ViewBase(Element):
    """The keys of all views."""

    entity: EntityName
    title: Text | None = None
    description: Text | None = None
    actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])
    states: States | None = None
    """The default comes from `ui.defaults.states`, and then from the binding."""


class ListViewBase(ViewBase):
    """The keys of the views that show many records."""

    sort: Sort | None = None
    filters: dict[MemberName, Filter] = pydantic.Field(default_factory=dict[str, Filter])
    pagination: Pagination | None = None
    row_actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])


class TableView(ListViewBase):
    """A table of records."""

    kind: Literal["table"]
    columns: Annotated[dict[MemberName, Column], pydantic.Field(min_length=1)]
    row_click: MemberName | None = None
    """A row action that runs when the user clicks a row."""
    selection: bool = False
    bulk_actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])


class CardsView(ListViewBase):
    """A grid of cards."""

    kind: Literal["cards"]
    card: Card | None = None
    grid: Grid | None = None


class ViewResponsive(Element):
    """How a view shows on screens narrower than a breakpoint."""

    below: BreakpointName
    """A breakpoint token, for example `md`."""
    layout: Literal["stack", "scroll"]
    """`stack`: the board columns show one under the other. `scroll`: they scroll sideways."""


class BoardView(ViewBase):
    """Cards in columns, one column for each value of an enum field."""

    kind: Literal["board"]
    group_by: MemberName
    columns: dict[MemberName, BoardColumn] = pydantic.Field(default_factory=dict[str, BoardColumn])
    card: Card | None = None
    sort: Sort | None = None
    move: MemberName | None = None
    responsive: ViewResponsive | None = None
    """The layout on narrow screens. Without it, the columns scroll sideways."""
    """The operation that runs when the user moves a card to another column."""
    row_actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])


class CalendarView(ViewBase):
    """The records on a calendar, by a date or a date-time field, in a week or a month."""

    kind: Literal["calendar"]
    start: FieldPath
    """A date or a date-time field: the day and the start time of each record."""
    end: FieldPath | None = None
    """A field of the same type as `start`: the end. Without it, a record has no length."""
    label: FieldPath | None = None
    """The text of a record. The default is the display field of the entity."""
    mode: Literal["week", "month"] = "month"
    """The first mode. The user can switch between the week and the month."""
    link: MemberName | None = None
    """A page that a record opens, with the ID of the record."""


class DetailHeader(Element):
    """The header of a detail view."""

    title: FieldPath | None = None
    """The default is the display field of the entity."""
    subtitle: FieldPath | None = None
    badges: list[FieldPath] = pydantic.Field(default_factory=list[str])
    """Enum fields that show as badges, with the badge set of each field."""


class DetailSection(Element):
    """A card with fields of the record, or a generation gap."""

    title: Text | None = None
    description: Text | None = None
    fields: list[FieldPath] = pydantic.Field(default_factory=list[str])
    columns: Annotated[int, pydantic.Field(ge=1, le=4)] = 1
    custom: bool = False
    """Hand-written code gives the content (a generation gap)."""


class DetailTab(Element):
    """A tab of a detail view: sections, a list of related records, or a gap."""

    label: Text | None = None
    icon: IconName | None = None
    sections: dict[MemberName, DetailSection] = pydantic.Field(
        default_factory=dict[str, DetailSection]
    )
    relation: MemberName | None = None
    """A one_to_many or many_to_many relation of the entity."""
    view: MemberName | None = None
    """A table or a card list of the target entity of the relation."""
    custom: bool = False

    @model_validator(mode="after")
    def _one_content(self) -> Self:
        related = self.relation is not None or self.view is not None
        if sum([bool(self.sections), related, self.custom]) != 1:
            raise PydanticCustomError(
                "tab_content",
                "Set exactly one of: sections, relation and view, or custom: true",
            )
        if related and (self.relation is None or self.view is None):
            raise PydanticCustomError("tab_content", "Set both relation and view")
        return self


class DetailView(ViewBase):
    """One record in sections and tabs. The page gives the record."""

    kind: Literal["detail"]
    header: DetailHeader | None = None
    sections: dict[MemberName, DetailSection] = pydantic.Field(
        default_factory=dict[str, DetailSection]
    )
    tabs: dict[MemberName, DetailTab] = pydantic.Field(default_factory=dict[str, DetailTab])


class ApiColumn(Element):
    """A column of a table of API data."""

    field: PropertyPath | None = None
    """A property of the items. The default is the column name."""
    label: Text | None = None
    format: Format | None = None
    """The default comes from the type of the property."""
    width: TokenRef | None = None
    """A size token."""
    align: Literal["start", "center", "end"] = "start"
    sortable: bool = True
    hide_below: BreakpointName | None = None
    """The column hides on screens narrower than this breakpoint."""


class ApiSort(Element):
    """The sort order of the items of an API answer."""

    field: PropertyPath
    direction: Direction = "asc"


class ApiSearchFilter(Element):
    """A text search in properties of the loaded items."""

    kind: Literal["search"]
    label: Text | None = None
    fields: Annotated[list[PropertyPath], pydantic.Field(min_length=1)]


class ApiCard(Element):
    """The content of a card of API data."""

    title: PropertyPath
    subtitle: PropertyPath | None = None
    fields: list[PropertyPath] = pydantic.Field(default_factory=list[str])
    footer: list[PropertyPath] = pydantic.Field(default_factory=list[str])


class ApiDetailHeader(Element):
    """The header of a detail view of API data."""

    title: PropertyPath | None = None
    """The default is the title of the view."""
    subtitle: PropertyPath | None = None


class ApiDetailSection(Element):
    """A card with properties of the answer."""

    title: Text | None = None
    description: Text | None = None
    fields: Annotated[list[PropertyPath], pydantic.Field(min_length=1)]
    columns: Annotated[int, pydantic.Field(ge=1, le=4)] = 1


_RECORD_KEYS = {
    "entity": "A view has an entity or a source, not both",
    "actions": "A view of API data has no actions",
    "row_actions": "A view of API data has no row actions: its items are not records",
    "bulk_actions": "A view of API data has no bulk actions: its items are not records",
    "selection": "A view of API data has no selection",
    "row_click": "A view of API data has no row actions",
    "tabs": "A detail view of API data has no tabs",
}
"""The keys of the views of records that a view of API data cannot have, with the reason."""


class ApiViewBase(Element):
    """The keys of all views of API data: the operation and its parameters (ADR 0022)."""

    source: ApiSource
    """The operation whose answer the view shows."""
    params: dict[str, JsonScalar] = pydantic.Field(default_factory=dict[str, JsonScalar])
    """The value of each parameter of the operation, by its name in the document. The
    value `$route.<name>` is a path parameter of the page."""
    title: Text | None = None
    description: Text | None = None
    states: States | None = None
    """The default comes from `ui.defaults.states`, and then from the binding."""

    @model_validator(mode="before")
    @classmethod
    def _no_record_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key, reason in _RECORD_KEYS.items():
                if key in data:
                    raise PydanticCustomError(
                        "api_view_key", "{reason} (key '{key}')", {"reason": reason, "key": key}
                    )
        return data  # pyright: ignore[reportUnknownVariableType]

    @property
    def api(self) -> str:
        """The name of the API, for example `holidays`."""
        return self.source.split(".")[1]

    @property
    def operation(self) -> str:
        """The operation ID, for example `getPublicHolidays`."""
        return self.source.split(".")[3]


class ApiListViewBase(ApiViewBase):
    """The keys of the views of a list in an API answer."""

    items: PropertyPath | None = None
    """The property of the answer with the list of items. Without it, the answer is the list."""
    sort: ApiSort | None = None
    filters: dict[MemberName, ApiSearchFilter] = pydantic.Field(
        default_factory=dict[str, ApiSearchFilter]
    )
    pagination: Pagination | None = None


class ApiTableView(ApiListViewBase):
    """A table of the items of an API answer."""

    kind: Literal["table"]
    columns: Annotated[dict[MemberName, ApiColumn], pydantic.Field(min_length=1)]


class ApiCardsView(ApiListViewBase):
    """A grid of cards, one for each item of an API answer."""

    kind: Literal["cards"]
    card: ApiCard
    grid: Grid | None = None


class ApiDetailView(ApiViewBase):
    """An object of an API answer in sections."""

    kind: Literal["detail"]
    header: ApiDetailHeader | None = None
    sections: Annotated[dict[MemberName, ApiDetailSection], pydantic.Field(min_length=1)]


type ApiView = ApiTableView | ApiCardsView | ApiDetailView
"""A view of API data (`source`)."""

type EntityView = TableView | CardsView | BoardView | CalendarView | DetailView
"""A view of the records of an entity."""


def view_tag(value: object) -> str | None:
    """Return the union tag of a view: `tag-api-<kind>` for a view with `source`."""
    tag = kind_tag(value)
    if tag is not None and isinstance(value, dict) and "source" in value:
        return "tag-api-" + tag.removeprefix("tag-")
    return tag


type View = Annotated[
    Annotated[TableView, Tag("tag-table")]
    | Annotated[CardsView, Tag("tag-cards")]
    | Annotated[BoardView, Tag("tag-board")]
    | Annotated[CalendarView, Tag("tag-calendar")]
    | Annotated[DetailView, Tag("tag-detail")]
    | Annotated[ApiTableView, Tag("tag-api-table")]
    | Annotated[ApiCardsView, Tag("tag-api-cards")]
    | Annotated[ApiDetailView, Tag("tag-api-detail")],
    Discriminator(view_tag),
]
"""A view of the records of an entity, or of API data (`source`). The `kind` key selects the
type."""
