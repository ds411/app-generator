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
from appgen.dsl.rules import EntityRule
from appgen.dsl.translations import Translations
from appgen.dsl.ui.common import Action
from appgen.dsl.ui.model import UI
from appgen.dsl.ui.page import PageArrangement, PageContent
from appgen.dsl.ui.views import Format
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
]
type RelationKind = Literal["many_to_one", "one_to_many", "one_to_one", "many_to_many"]
type OnDelete = Literal["restrict", "cascade", "set_null"]
type OperationKind = Literal["create", "read", "update", "delete", "list", "custom"]

FIELD_TYPES: tuple[str, ...] = FieldType.__value__.__args__
RELATION_KINDS: tuple[str, ...] = RelationKind.__value__.__args__
OPERATION_KINDS: tuple[str, ...] = OperationKind.__value__.__args__


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
    computed: Text | None = None
    """An expression of other fields (see `appgen.dsl.expressions`). The apps compute the value."""


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

    @property
    def stored_fields(self) -> dict[str, Field]:
        """The fields that the records store: all fields except the computed fields."""
        return {name: f for name, f in self.fields.items() if f.computed is None}

    @property
    def computed_fields(self) -> dict[str, Field]:
        """The computed fields, whose values come from other fields."""
        return {name: f for name, f in self.fields.items() if f.computed is not None}


class Operation(Element):
    """An action that the app can do on an entity."""

    kind: OperationKind
    entity: EntityName
    description: Text | None = None
    params: dict[MemberName, Field] = pydantic.Field(default_factory=dict[str, Field])
    returns: Text = "none"
    """An entity name, or `none`."""
    apis: list[MemberName] = pydantic.Field(default_factory=list[str])
    """The third-party APIs that the logic of a custom operation calls (ADR 0019)."""


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

    _index: dict[str, Element] = PrivateAttr(default_factory=dict[str, Element])

    @property
    def elements(self) -> Mapping[str, Element]:
        """All elements of the definition by ID, in source order."""
        return MappingProxyType(self._index)

    def find(self, element_id: str) -> Element | None:
        """Return the element with an ID, or None if no element has the ID."""
        return self._index.get(element_id)
