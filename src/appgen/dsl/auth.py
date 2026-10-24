"""The sign-in of the apps: the entity that holds the users, and the open parts."""

from typing import Annotated

import pydantic

from appgen.dsl.apis import EnvName
from appgen.dsl.element import Element, EntityName, MemberName, Text

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

type Claim = Annotated[str, pydantic.StringConstraints(pattern=r"^[^\s\"\\]+$")]
"""The name of a claim of an ID token, or of a scope, for example `email`."""


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


class Provider(Element):
    """An OpenID Connect provider for the sign-in (ADR 0020).

    The app sends the user to the provider, and gets an ID token back: the
    authorization code flow with PKCE. The claim `username_claim` of the
    token gives the user name. The app signs in the user with this user
    name, or with `create_users` makes a new user.
    """

    title: Text | None = None
    """The name on the sign-in button, for example "Company account". Default: the name."""
    issuer: Annotated[str, pydantic.StringConstraints(pattern=r"^https://\S+$")]
    """The issuer URL of the provider. The apps read its discovery document."""
    client_id_env: EnvName
    """The environment variable with the client ID of the app at the provider."""
    client_secret_env: EnvName
    """The environment variable with the client secret of the app at the provider."""
    scopes: list[Claim] = pydantic.Field(default_factory=lambda: ["openid", "email", "profile"])
    """The scopes that the app asks for. They must include `openid`."""
    username_claim: Claim = "email"
    """The claim of the ID token that gives the user name."""
    create_users: bool = False
    """Make a new user at the first sign-in of an unknown user name. Else the app refuses it."""
    default_role: MemberName | None = None
    """With `create_users` and `access`: the role of a new user."""
    claims: dict[MemberName, Claim] = pydantic.Field(default_factory=dict[str, str])
    """With `create_users`: the fields of a new user from claims, for example `name: name`."""


class Auth(Element):
    """The sign-in with a user name and a password (ADR 0011), or with providers (ADR 0020).

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
    password: bool = True
    """The sign-in with a user name and a password. `false`: only the sign-in with `providers`."""
    providers: dict[MemberName, Provider] = pydantic.Field(default_factory=dict[str, Provider])
    """The OpenID Connect providers that the users can sign in with."""
