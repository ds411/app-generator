"""The typed model of an app definition (DSL version 0, see ADR 0002)."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

import pydantic
from pydantic import BeforeValidator, JsonValue, PrivateAttr, StringConstraints

from appgen.dsl.access import Access
from appgen.dsl.apis import Api
from appgen.dsl.auth import Auth
from appgen.dsl.crud import Crud, crud_input, crud_schema
from appgen.dsl.element import AppName, Element, EntityName, MemberName, Text
from appgen.dsl.element import is_extension_key as is_extension_key
from appgen.dsl.events import EventInput, EventName
from appgen.dsl.history import HistoryInput
from appgen.dsl.jobs import Job
from appgen.dsl.notifications import Notification
from appgen.dsl.rules import EntityRule
from appgen.dsl.seed import EntitySeed
from appgen.dsl.storage import (
    DEFAULT_IMAGE_TYPES,
    DEFAULT_MAX_SIZE,
    FILE_TYPES,
    MEDIA_TYPE_PATTERN,
    Storage,
    size_input,
    size_schema,
)
from appgen.dsl.translations import Translations
from appgen.dsl.ui.common import Action, FieldPath
from appgen.dsl.ui.dashboards import RecordFilter
from appgen.dsl.ui.model import UI
from appgen.dsl.ui.page import PageArrangement, PageContent
from appgen.dsl.ui.views import Format
from appgen.dsl.webhooks import Webhook
from appgen.dsl.workflows import Workflow

DSL_VERSION = 0
"""The DSL version that this loader reads."""
RESERVED_SECTIONS: tuple[str, ...] = ()
"""Top-level sections that a later DSL version adds (ADR 0002).

ADR 0003 adds `ui`. The sections `translations`, `workflows`, `auth`, and `access` that
ADR 0002 reserved are now part of the DSL. The loader keeps the check for a later section.
"""

type FieldType = Literal[
    "string",
    "text",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "uuid",
    "email",
    "url",
    "enum",
    "json",
    "file",
    "image",
]
type RelationKind = Literal["many_to_one", "one_to_many", "one_to_one", "many_to_many"]
type OnDelete = Literal["restrict", "cascade", "set_null"]
type OperationKind = Literal["create", "read", "update", "delete", "list", "custom", "query"]

FIELD_TYPES: tuple[str, ...] = FieldType.__value__.__args__
RELATION_KINDS: tuple[str, ...] = RelationKind.__value__.__args__
OPERATION_KINDS: tuple[str, ...] = OperationKind.__value__.__args__

SEQUENCE_TYPES = ("string", "integer")
"""The field types that take a `sequence`."""
MAX_SEQUENCE_START = 10**15
"""The largest first number of a sequence. The numbers stay exact in JavaScript."""
MAX_SEQUENCE_WIDTH = 15
"""The largest `width` of a sequence: the digits of the largest number."""


class Sequence(Element):
    """The numbers of a database sequence: a new record gets the next number."""

    start: Annotated[int, pydantic.Field(ge=1, le=MAX_SEQUENCE_START)] = 1
    """The number of the first record."""
    prefix: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._/#-]{1,20}$")] | None = None
    """`string` fields: the text before the number, for example `INV-`."""
    width: Annotated[int, pydantic.Field(ge=1, le=MAX_SEQUENCE_WIDTH)] | None = None
    """`string` fields: the least number of digits. Zeros fill the number on the left."""

    def text(self, number: int) -> str:
        """Return the value of a `string` field for a number, for example `INV-0042`."""
        return f"{self.prefix or ''}{number:0{self.width or 1}d}"


class Field(Element):
    """A field of an entity, or a param of a custom operation."""

    type: FieldType
    description: Text | None = None
    label: Text | None = None
    required: bool = False
    unique: bool = False
    default: JsonValue = None
    min_length: Annotated[int, pydantic.Field(ge=0)] | None = None
    max_length: Annotated[int, pydantic.Field(ge=1)] | None = None
    pattern: Text | None = None
    min: float | None = None
    max: float | None = None
    precision: Annotated[int, pydantic.Field(ge=1)] | None = None
    scale: Annotated[int, pydantic.Field(ge=0)] | None = None
    values: list[MemberName] | None = None
    format: Format | None = None
    """The display format in all views. A view column can set another format."""
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    """The ISO 4217 code of the currency of the `currency` format, for example `EUR`."""
    currency_field: FieldPath | None = None
    """Number fields: the path of a `string` or an `enum` field with the ISO 4217 code of
    the currency of each record, for example `customer.currency`. `currency` is the
    currency of a record without a code."""
    computed: Text | None = None
    """An expression of other fields (see `appgen.dsl.expressions`). The apps compute the value."""
    filter: RecordFilter | None = None
    """A computed field: the related records that its totals use (the filter of the dashboards)."""
    translatable: bool = False
    """The records have a value of the field in each language of `translations` (ADR 0026)."""
    max_size: Annotated[int, pydantic.Field(ge=1), BeforeValidator(size_input)] | None = (
        pydantic.Field(default=None, json_schema_extra=size_schema)
    )
    """`file` and `image`: the largest file in bytes. A text can give a unit, for example `5MB`."""
    types: list[Annotated[str, StringConstraints(pattern=MEDIA_TYPE_PATTERN)]] | None = None
    """`file` and `image`: the media types that the field allows, for example `image/*`."""
    sequence: Sequence | None = None
    """`string` and `integer` fields: a new record gets the next number of a database
    sequence. The inputs and the forms do not have the field."""

    @property
    def is_file(self) -> bool:
        """True for a field that holds a file: a `file` or an `image` field (ADR 0027)."""
        return self.type in FILE_TYPES

    @property
    def size_limit(self) -> int:
        """The largest file of a file field in bytes: `max_size`, else 10 MB."""
        return self.max_size if self.max_size is not None else DEFAULT_MAX_SIZE

    @property
    def media_types(self) -> list[str]:
        """The media types that a file field allows. An empty list allows all types.

        An `image` field without `types` allows PNG, JPEG, GIF, and WebP images.
        """
        if self.types is not None:
            return list(self.types)
        return list(DEFAULT_IMAGE_TYPES) if self.type == "image" else []


class Relation(Element):
    """A relation from one entity to another entity."""

    kind: RelationKind
    target: EntityName
    description: Text | None = None
    label: Text | None = None
    required: bool = False
    inverse: MemberName | None = None
    on_delete: OnDelete | None = None


class Entity(Element):
    """A kind of record that the app stores, for example a task."""

    description: Text | None = None
    label: Text | None = None
    plural_label: Text | None = None
    display_field: MemberName | None = None
    fields: Annotated[dict[MemberName, Field], pydantic.Field(min_length=1)]
    relations: dict[MemberName, Relation] = pydantic.Field(default_factory=dict[str, Relation])
    rules: dict[MemberName, EntityRule] = pydantic.Field(default_factory=dict[str, EntityRule])
    """Rules over more than one field, or over more than one record."""
    crud: Annotated[Crud | None, BeforeValidator(crud_input)] = pydantic.Field(
        default=None, json_schema_extra=crud_schema
    )
    """The CRUD shorthand. The loader expands it to operations, views, and forms."""
    events: dict[EventName, EventInput] = pydantic.Field(
        default_factory=dict[EventName, EventInput]
    )
    """The custom operations that run after a record is created, changed, or deleted (ADR 0031)."""
    history: HistoryInput = None
    """The change log of the records (ADR 0040)."""

    @property
    def stored_fields(self) -> dict[str, Field]:
        """The fields that the records store: all fields except the computed fields."""
        return {name: f for name, f in self.fields.items() if f.computed is None}

    @property
    def computed_fields(self) -> dict[str, Field]:
        """The computed fields, whose values come from other fields."""
        return {name: f for name, f in self.fields.items() if f.computed is not None}

    @property
    def file_fields(self) -> dict[str, Field]:
        """The fields that hold a file: the `file` and the `image` fields (ADR 0027)."""
        return {name: f for name, f in self.fields.items() if f.is_file}

    @property
    def sequence_fields(self) -> dict[str, Field]:
        """The fields whose values come from a database sequence (`sequence`)."""
        return {name: f for name, f in self.fields.items() if f.sequence is not None}

    @property
    def history_members(self) -> list[str]:
        """The fields and the relations that the change log keeps, in source order (ADR 0040).

        They are the names in `history.fields`, else the stored fields
        except the file fields, and the `many_to_one` relations. Without
        `history`, the list is empty.
        """
        if self.history is None:
            return []
        fields = [n for n, f in self.stored_fields.items() if not f.is_file]
        relations = [n for n, r in self.relations.items() if r.kind == "many_to_one"]
        if self.history.fields is None:
            return fields + relations
        return [n for n in fields + relations if n in self.history.fields]


class Operation(Element):
    """An action that the app can do on an entity, or a query that returns a list (ADR 0045)."""

    kind: OperationKind
    entity: EntityName
    """The entity of the operation. A query is in the slice of the entity."""
    description: Text | None = None
    params: dict[MemberName, Field] = pydantic.Field(default_factory=dict[str, Field])
    returns: Text = "none"
    """An entity name, or `none`. A query with `returns` gives records of the entity."""
    result: dict[MemberName, Field] | None = None
    """A query: the fields of each row, for rows that are not records (ADR 0045)."""
    apis: list[MemberName] = pydantic.Field(default_factory=list[str])
    """The third-party APIs that the logic of a custom operation calls (ADR 0019)."""
    lines: list[MemberName] = pydantic.Field(default_factory=list[str])
    """A create or an update operation: the `one_to_many` relations whose records it writes
    with the record, in one transaction (ADR 0035)."""

    @property
    def row_entity(self) -> str | None:
        """A query that gives records: the entity of the records, else None."""
        if self.kind != "query" or self.returns == "none":
            return None
        return self.returns


RECORD_PREFIX = "$record."
"""The prefix of a value that is a field of the record of a page, for example `$record.summary`."""


class PageMeta(Element):
    """The metadata of a page for search engines and link previews."""

    description: Text | None = None
    """A text, or `$record.<field>` for a `string` or a `text` field of the record of the page."""
    image: str | None = None
    """The URL of an image (absolute, or a path of the app), or `$record.<field>` for an `image`
    or a `url` field of the record of the page."""


class Page(Element):
    """A screen of a front-end app."""

    path: Annotated[str, StringConstraints(pattern=r"^/")]
    """The route of the page, for example `/projects/{id}`."""
    title: Text
    entity: EntityName | None = None
    description: Text | None = None
    layout: MemberName | None = None
    """A layout in `ui.layouts`. The default is `ui.defaults.layout`."""
    content: PageContent | None = None
    actions: dict[MemberName, Action] = pydantic.Field(default_factory=dict[str, Action])
    """The actions in the page header."""
    breadcrumb: Text | None = None
    """The label of the page in the breadcrumbs. The default is the menu label, else the title."""
    arrangement: PageArrangement | None = None
    """Layout hints: the order and the place of the title, the actions, and the content."""
    embed: Annotated[list[Text], pydantic.Field(min_length=1)] | None = None
    """The origins of the websites that can show the page in a frame, for example
    `https://www.example.com`. Only a public page takes them. The page then shows without the
    app shell (ADR 0032)."""
    meta: PageMeta | None = None
    """The description and the image of the page for search engines and link previews."""
    share: bool = False
    """True if a user that may change the record of a detail page makes a secret link of it
    (ADR 0049). A guest opens the link without a sign-in, and sees the record read-only."""

    @property
    def shared_path(self) -> str:
        """The path of the shared page of a page with `share` (ADR 0049): `/shared` and the path
        with the token in the place of the ID, for example `/shared/lessons/{token}`."""
        return "/shared" + self.path.removesuffix("{id}") + "{token}"


class App(Element):
    """The name and the description of the app."""

    name: AppName
    title: Text
    description: Text | None = None


class AppDefinition(Element):
    """The root of an app definition."""

    version: Literal[0]
    app: App
    entities: Annotated[dict[EntityName, Entity], pydantic.Field(min_length=1)]
    operations: dict[MemberName, Operation] = pydantic.Field(default_factory=dict[str, Operation])
    pages: dict[MemberName, Page] = pydantic.Field(default_factory=dict[str, Page])
    ui: UI | None = None
    auth: Auth | None = None
    """The sign-in of the users (ADR 0011)."""
    access: Access | None = None
    """The roles of the users and their permissions (ADR 0012)."""
    translations: Translations | None = None
    """The languages of the UI text (the front ends)."""
    workflows: dict[MemberName, Workflow] = pydantic.Field(default_factory=dict[str, Workflow])
    """The state machines of the enum fields of the entities."""
    apis: dict[MemberName, Api] = pydantic.Field(default_factory=dict[str, Api])
    """The third-party APIs that OpenAPI documents describe (ADR 0019)."""
    webhooks: dict[MemberName, Webhook] = pydantic.Field(default_factory=dict[str, Webhook])
    """The endpoints that other systems send signed events to (ADR 0028)."""
    seed: dict[EntityName, EntitySeed] = pydantic.Field(default_factory=dict[str, EntitySeed])
    """The seed records of the entities: the data that the apps start with (ADR 0021)."""
    storage: Storage | None = None
    """The storage of the files of the file fields (ADR 0027)."""
    jobs: dict[MemberName, Job] = pydantic.Field(default_factory=dict[str, Job])
    """The work that the apps run on a schedule, or at the time of a date field (ADR 0029)."""
    notifications: dict[MemberName, Notification] = pydantic.Field(
        default_factory=dict[str, Notification]
    )
    """The notices that users get when a record that concerns them changes (ADR 0041)."""

    _index: dict[str, Element] = PrivateAttr(default_factory=dict[str, Element])

    @property
    def elements(self) -> Mapping[str, Element]:
        """All elements of the definition by ID, in source order."""
        return MappingProxyType(self._index)

    def find(self, element_id: str) -> Element | None:
        """Return the element with an ID, or None if no element has the ID."""
        return self._index.get(element_id)

    def address_field(self) -> str | None:
        """Return the field of the user entity with the email address of a user, or None.

        It is the user name field if its type is `email`, else the first
        required `email` field of the user entity (ADR 0023).
        """
        if self.auth is None or self.auth.user_entity not in self.entities:
            return None
        fields = self.entities[self.auth.user_entity].stored_fields
        username = fields.get(self.auth.username_field)
        if username is not None and username.type == "email":
            return self.auth.username_field
        return next((n for n, f in fields.items() if f.type == "email" and f.required), None)
