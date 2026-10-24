"""The sign-in of the apps: the entity that holds the users, and the open parts."""

from typing import Annotated

import pydantic

from appgen.dsl.element import Element, EntityName, MemberName

SIGN_IN_PATH = "/sign-in"
"""The path of the sign-in page of the front ends. A page of the definition cannot use it."""


class Auth(Element):
    """The sign-in with a user name and a password (ADR 0011).

    The users are the records of `user_entity`. Each app stores the
    password hashes apart from the records. All pages and operations need
    a signed-in user, except the public ones.
    """

    user_entity: EntityName
    username_field: MemberName
    """A required, unique `string` or `email` field of the user entity."""
    public_pages: list[MemberName] = pydantic.Field(default_factory=list[str])
    """The pages that a user can open without a sign-in."""
    public_operations: list[MemberName] = pydantic.Field(default_factory=list[str])
    """The operations that a client can call without a sign-in."""
    session_hours: Annotated[int, pydantic.Field(ge=1, le=720)] = 8
    """The time after which a user must sign in again."""
