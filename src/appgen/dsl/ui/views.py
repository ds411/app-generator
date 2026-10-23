"""Badges and views: tables, card lists, boards, and detail views (ADR 0003)."""

from typing import Annotated, Literal, Self

import pydantic
from pydantic import Discriminator, StringConstraints, Tag, model_validator
from pydantic_core import PydanticCustomError

from appgen.dsl.element import (
    ENTITY_NAME_PATTERN,
    MEMBER_NAME_PATTERN,
    Element,
    EntityName,
    MemberName,
    Text,
)
from appgen.dsl.ui.common import Action, FieldPath, Grid, IconName, TokenRef, kind_tag

type FieldRef = Annotated[
    str,
    StringConstraints(pattern=ENTITY_NAME_PATTERN[:-1] + r"\." + MEMBER_NAME_PATTERN[1:]),
]
"""A field of an entity, for example `Task.status`."""

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


class BoardView(ViewBase):
    """Cards in columns, one column for each value of an enum field."""

    kind: Literal["board"]
    group_by: MemberName
    columns: dict[MemberName, BoardColumn] = pydantic.Field(default_factory=dict[str, BoardColumn])
    card: Card | None = None
    sort: Sort | None = None
    move: MemberName | None = None
    """The operation that runs when the user moves a card to another column."""
    row_actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])


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


type View = Annotated[
    Annotated[TableView, Tag("tag-table")]
    | Annotated[CardsView, Tag("tag-cards")]
    | Annotated[BoardView, Tag("tag-board")]
    | Annotated[DetailView, Tag("tag-detail")],
    Discriminator(kind_tag),
]
"""A view of the records of an entity. The `kind` key selects the type."""
