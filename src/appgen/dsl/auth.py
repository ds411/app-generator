"""The sign-in of the apps: the entity that holds the users, and the open parts."""

from typing import Annotated

import pydantic

from appgen.dsl.element import Element, EntityName, MemberName

SIGN_IN_PATH = "/sign-in"
"""The path of the sign-in page of the front ends. A page of the definition cannot use it."""
SIGN_UP_PATH = "/sign-up"
"""The path of the sign-up page of the front ends, with `auth.sign_up`."""
FORGOT_PASSWORD_PATH = "/forgot-password"
"""The path of the page that asks for a password reset, with `auth.password_reset`."""
RESET_PASSWORD_PATH = "/reset-password"
"""The path of the page that sets a new password with a reset link, with `auth.password_reset`."""
MIN_PASSWORD_LENGTH = 8
"""The default and the lowest value of `auth.min_password_length`."""


class SignUp(Element):
    """The sign-up of new users (ADR 0016): the fields of the form, and the role of a new user."""

    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)]
    """The fields of the user entity that the sign-up form asks for, with the user name."""
    default_role: MemberName | None = None
    """With `access`: the role of a new user. The default is the default of the role field."""


class PasswordReset(Element):
    """The reset of a forgotten password (ADR 0017): a message with a one-time link.

    The definition does not know the mail service, so the delivery of the
    message is a generation gap.
    """

    token_minutes: Annotated[int, pydantic.Field(ge=5, le=1440)] = 60
    """The time that a reset link stays valid."""


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
    min_password_length: Annotated[int, pydantic.Field(ge=MIN_PASSWORD_LENGTH, le=128)] = (
        MIN_PASSWORD_LENGTH
    )
    """The lowest number of characters of a new password: a sign-up or a change."""
    sign_up: SignUp | None = None
    """The sign-up of new users. Without it, only an administrator makes users."""
    password_reset: PasswordReset | None = None
    """The reset of a forgotten password with a link in a message. Off by default."""
