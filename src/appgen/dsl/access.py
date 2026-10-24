"""The roles of the users and their permissions: the operations and the pages of each role."""

from typing import Annotated

import pydantic

from appgen.dsl.element import Element, MemberName, Text

ALL = "*"
"""In a list of operations or pages: all of them."""


class Role(Element):
    """A role: the operations and the pages that its users may use (ADR 0012)."""

    label: Text | None = None
    operations: list[
        Annotated[str, pydantic.StringConstraints(pattern=r"^([a-z][a-z0-9_]*|\*)$")]
    ] = pydantic.Field(default_factory=list[str])
    """The operations that the role may call, or `["*"]` for all operations."""
    pages: list[Annotated[str, pydantic.StringConstraints(pattern=r"^([a-z][a-z0-9_]*|\*)$")]] = (
        pydantic.Field(default_factory=list[str])
    )
    """The pages that the role may open, or `["*"]` for all pages."""

    def allows_operation(self, name: str) -> bool:
        """Return True if the role may call an operation."""
        return ALL in self.operations or name in self.operations

    def allows_page(self, name: str) -> bool:
        """Return True if the role may open a page."""
        return ALL in self.pages or name in self.pages


class Access(Element):
    """The roles of the users. It needs the section `auth`.

    The value of `role_field` (an enum field of the user entity) is the
    role of a user. A user may call the public operations and open the
    public pages of `auth`, and the operations and the pages of the role.
    """

    role_field: MemberName
    roles: Annotated[dict[MemberName, Role], pydantic.Field(min_length=1)]
    """The roles by value of the role field."""
