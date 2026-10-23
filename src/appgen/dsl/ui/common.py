"""Types and elements that more than one part of the UI uses (ADR 0003)."""

from typing import Annotated, Literal

import pydantic
from pydantic import Discriminator, StringConstraints, Tag

from appgen.dsl.element import Element, MemberName, Text
from appgen.dsl.ui.tokens import TOKEN_NAME_PATTERN, TOKEN_REFERENCE_PATTERN

ICON_NAME_PATTERN = r"^[a-z][a-z0-9-]*$"
FIELD_PATH_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"

type TokenRef = Annotated[str, StringConstraints(pattern=TOKEN_REFERENCE_PATTERN)]
"""A reference to a design token, for example `{color.primary}`."""
type IconName = Annotated[str, StringConstraints(pattern=ICON_NAME_PATTERN)]
"""The kebab-case name of a Lucide icon, for example `folder-kanban`."""
type BreakpointName = Annotated[str, StringConstraints(pattern=TOKEN_NAME_PATTERN)]
"""The name of a token in `ui.tokens.breakpoint`, for example `md`."""
type FieldPath = Annotated[str, StringConstraints(pattern=FIELD_PATH_PATTERN)]
"""A field or a relation of an entity, through relations, for example `project.name`."""
type Variant = Literal["default", "secondary", "outline", "ghost", "destructive"]
"""A button variant of shadcn/ui."""


def kind_tag(value: object) -> str | None:
    """Return the union tag of a mapping with a `kind` key, for example `tag-form`."""
    if isinstance(value, dict):
        kind = value.get("kind")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(kind, str):
            return f"tag-{kind}"
    return None


class Grid(Element):
    """A column grid. Forms, card lists, and dashboards use grids."""

    columns: Annotated[int, pydantic.Field(ge=1, le=12)] = 1
    gap: TokenRef | None = None
    """A spacing token."""


class Confirm(Element):
    """A question that the user must confirm before an action runs."""

    title: Text
    message: Text | None = None
    confirm_label: Text | None = None


class OnSuccess(Element):
    """What the app does after an action or a form succeeds."""

    toast: Text | None = None
    navigate: MemberName | None = None
    """A page to open."""


class ActionBase(Element):
    """The keys of all actions."""

    label: Text | None = None
    icon: IconName | None = None
    variant: Variant = "default"
    confirm: Confirm | None = None


class NavigateAction(ActionBase):
    """Open a page."""

    kind: Literal["navigate"]
    page: MemberName
    params: dict[MemberName, FieldPath] = pydantic.Field(default_factory=dict[str, str])
    """A mapping from a path parameter of the page to a field path of the record."""


class FormAction(ActionBase):
    """Open a form."""

    kind: Literal["form"]
    form: MemberName
    on_success: OnSuccess | None = None


class OperationAction(ActionBase):
    """Run an operation, for example a delete."""

    kind: Literal["operation"]
    operation: MemberName
    on_success: OnSuccess | None = None


class CustomAction(ActionBase):
    """An action that hand-written code gives (a generation gap)."""

    kind: Literal["custom"]


type Action = Annotated[
    Annotated[NavigateAction, Tag("tag-navigate")]
    | Annotated[FormAction, Tag("tag-form")]
    | Annotated[OperationAction, Tag("tag-operation")]
    | Annotated[CustomAction, Tag("tag-custom")],
    Discriminator(kind_tag),
]
"""An action. The `kind` key selects the type."""
