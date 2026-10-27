"""Forms: create, edit, and custom operation forms (ADR 0003)."""

from typing import Annotated, Literal

import pydantic
from pydantic import Discriminator, JsonValue, Tag

from appgen.dsl.element import Element, EntityName, MemberName, Text
from appgen.dsl.ui.common import Grid, kind_tag

type Widget = Literal[
    "text",
    "textarea",
    "number",
    "select",
    "radio",
    "checkbox",
    "switch",
    "date",
    "datetime",
    "relation",
    "file",
    "lines",
    "custom",
]
type FormMode = Literal["dialog", "sheet", "page"]
type CompareOp = Literal["eq", "ne", "lt", "lte", "gt", "gte"]


class RequiredRule(Element):
    """The field needs a value."""

    message: Text | None = None


class LengthRule(Element):
    """A minimum or a maximum number of characters."""

    value: Annotated[int, pydantic.Field(ge=0)]
    message: Text | None = None


class NumberRule(Element):
    """A minimum or a maximum value."""

    value: int | float
    message: Text | None = None


class PatternRule(Element):
    """A regular expression that the value must match."""

    value: Text
    message: Text | None = None


class FieldRules(Element):
    """Validation rules of a form field, in addition to the rules of the field type."""

    required: RequiredRule | None = None
    min_length: LengthRule | None = None
    max_length: LengthRule | None = None
    pattern: PatternRule | None = None
    min: NumberRule | None = None
    max: NumberRule | None = None


class FormField(Element):
    """A field of a form: a field or a relation of the entity, or an operation parameter."""

    widget: Widget | None = None
    """The default comes from the field type."""
    label: Text | None = None
    placeholder: Text | None = None
    help: Text | None = None
    span: Annotated[int, pydantic.Field(ge=1, le=12)] = 1
    """The number of grid columns."""
    rows: Annotated[int, pydantic.Field(ge=1)] | None = None
    """The number of text lines of a `textarea`."""
    step: Annotated[float, pydantic.Field(gt=0)] | Annotated[int, pydantic.Field(gt=0)] | None = (
        None
    )
    """The step of a `number`."""
    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)] | None = None
    """For `widget: lines`: the fields of the related records, one column each (ADR 0035)."""
    rules: FieldRules | None = None


class FormSection(Element):
    """A group of form fields with a title."""

    title: Text | None = None
    description: Text | None = None
    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)]


class CompareRule(Element):
    """A rule that compares two fields of the form."""

    kind: Literal["compare"]
    field: MemberName
    op: CompareOp
    other: MemberName
    message: Text


class CustomRule(Element):
    """A rule that hand-written code checks (a generation gap)."""

    kind: Literal["custom"]
    fields: list[MemberName] = pydantic.Field(default_factory=list[str])
    """The fields that show the message."""
    message: Text | None = None


type FormRule = Annotated[
    Annotated[CompareRule, Tag("tag-compare")] | Annotated[CustomRule, Tag("tag-custom")],
    Discriminator(kind_tag),
]


class FormOnSuccess(Element):
    """What the app does after the submit succeeds."""

    toast: Text | None = None
    close: bool = True
    navigate: MemberName | None = None
    """A page to open."""


class Form(Element):
    """A form that calls an operation on submit."""

    entity: EntityName
    operation: MemberName
    """A `create`, `update`, or `custom` operation on the entity."""
    mode: FormMode = "dialog"
    title: Text | None = None
    description: Text | None = None
    submit_label: Text | None = None
    cancel_label: Text | None = None
    fields: Annotated[dict[MemberName, FormField], pydantic.Field(min_length=1)]
    sections: dict[MemberName, FormSection] = pydantic.Field(default_factory=dict[str, FormSection])
    grid: Grid | None = None
    rules: dict[MemberName, FormRule] = pydantic.Field(default_factory=dict[str, FormRule])
    defaults: dict[MemberName, JsonValue] = pydantic.Field(default_factory=dict[str, JsonValue])
    """A literal, `$route.<param>` for a path parameter of the page, or `$me` for the signed-in
    user (a relation to the user entity)."""
    on_success: FormOnSuccess | None = None
