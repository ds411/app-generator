"""The sign-in of the apps: the entity that holds the users, and the open parts."""

from typing import Annotated, Any, Literal, cast

import pydantic
from pydantic import BeforeValidator

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
VERIFY_EMAIL_PATH = "/verify-email"
"""The path of the page of the link that confirms an email address, with `verify_email`."""
SECOND_FACTOR_PATH = "/second-factor"
"""The path of the page that turns the second factor on and off, with `auth.second_factor`."""
CONNECTIONS_PATH = "/connections"
"""The path of the page of the connections of a user to the APIs with the authorization code
flow (ADR 0033), and the start of the paths of the flow in the Next.js app."""
NOTICE_SETTINGS_PATH = "/notice-settings"
"""The path of the page that turns the emails of the notifications on and off (ADR 0044), with a
notification with `email: true`."""
PROVIDER_PATHS = "/auth/"
"""With `auth.providers`: the start of the paths of the provider sign-in in the front ends."""
MIN_PASSWORD_LENGTH = 8
"""The default and the lowest value of `auth.min_password_length`."""
ME = "$me"
"""The signed-in user, as the value of a relation to the user entity: in the filters of the
views, the widgets, and the totals, and in the defaults of the forms."""


def has_me(value: object) -> bool:
    """Return True if a value of a filter or of a default is `$me` or has it: in a list, or
    as an operand of a condition."""
    if isinstance(value, dict):
        return any(has_me(item) for item in cast(dict[str, object], value).values())
    if isinstance(value, list):
        return any(has_me(item) for item in cast(list[object], value))
    return value == ME


type Claim = Annotated[str, pydantic.StringConstraints(pattern=r"^[^\s\"\\]+$")]
"""The name of a claim of an ID token, or of a scope, for example `email`."""
type ParamName = Annotated[str, pydantic.StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]
"""The name of a parameter of the authorization request, for example `identity_provider`."""
FLOW_PARAMS = frozenset(
    {
        "client_id",
        "code_challenge",
        "code_challenge_method",
        "nonce",
        "redirect_uri",
        "response_type",
        "scope",
        "state",
    }
)
"""The parameters of the authorization request that the flow sets (ADR 0020)."""


def flag_input(value: object) -> object:
    """Return the mapping form of a flag: `true` becomes an empty mapping, `false` None."""
    if value is True:
        return {}
    if value is False:
        return None
    return value


def flag_schema(schema: dict[str, Any]) -> None:
    """Add the short form `true` to the JSON Schema of a key."""
    schema["anyOf"] = [{"type": "boolean"}, *schema.get("anyOf", [])]


class EmailVerification(Element):
    """The verification of the email address of a new user (ADR 0023).

    After the sign-up, the app sends a message with a link to the address.
    The user can sign in only after the user opens the link.
    """

    token_minutes: Annotated[int, pydantic.Field(ge=5, le=10080)] = 1440
    """The time that a verification link stays valid."""


class SignUp(Element):
    """The sign-up of new users (ADR 0016): the fields of the form, and the role of a new user."""

    fields: Annotated[list[MemberName], pydantic.Field(min_length=1)]
    """The fields of the user entity that the sign-up form asks for, with the user name."""
    default_role: MemberName | None = None
    """With `access`: the role of a new user. The default is the default of the role field."""
    verify_email: Annotated[EmailVerification | None, BeforeValidator(flag_input)] = pydantic.Field(
        default=None, json_schema_extra=flag_schema
    )
    """`true`: a new user confirms the email address with a link before the first sign-in."""


class PasswordReset(Element):
    """The reset of a forgotten password (ADR 0017): a message with a one-time link.

    The definition does not know the mail service, so the delivery of the
    message is a generation gap.
    """

    token_minutes: Annotated[int, pydantic.Field(ge=5, le=1440)] = 60
    """The time that a reset link stays valid."""


class SecondFactor(Element):
    """A second factor of the sign-in (ADR 0024): the codes of an authenticator app.

    Each user with a password can turn it on. Then a sign-in needs the
    password and a code, or a recovery code.
    """

    totp: bool = False
    """`true`: time-based one-time passwords (RFC 6238). It is the only method now."""
    required_roles: list[MemberName] = pydantic.Field(default_factory=list[str])
    """With `access`: the roles that must use the second factor."""


class ProviderRoles(Element):
    """The roles of the users from a claim of a provider, for example the groups of Entra ID.

    At each sign-in, the app sets the role of the user to the first role of
    `map` whose group is in the claim. Without a match, the user gets the
    `default_role` of the provider, or the app refuses the sign-in.
    """

    claim: Claim
    """The claim with the groups of the user, for example `groups` or `custom:groups`. Its value
    is a list, or a text in the form `[a, b]`, `a,b`, or `a`."""
    map: Annotated[dict[Text, MemberName], pydantic.Field(min_length=1)]
    """A group of the claim to a role of `access`, in the order of the check."""


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
    """With `create_users` and `access`: the role of a new user. With `roles`: the role of a user
    whose groups have no role."""
    claims: dict[MemberName, Claim] = pydantic.Field(default_factory=dict[str, str])
    """With `create_users`: the fields of a new user from claims, for example `name: name`."""
    roles: ProviderRoles | None = None
    """With `access`: the role of the user at each sign-in, from the groups in a claim."""
    authorize_params: dict[ParamName, Text] = pydantic.Field(default_factory=dict[str, str])
    """Fixed parameters of the authorization request, for example `identity_provider: EntraID`:
    a user pool of Amazon Cognito then sends the user at once to that identity provider."""
    trust_email: bool = False
    """Accept the email address of an ID token also when `email_verified` is missing or false.
    Only for a provider that gives only the addresses of the company, for example a user pool
    of Amazon Cognito with a single-tenant Entra ID as its SAML identity provider."""


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
    delivery: Literal["extension", "smtp"] = "extension"
    """The delivery of the messages of the password reset and of the email verification.

    `extension`: the extension file of the app sends them (ADR 0017). `smtp`:
    the apps send them with the SMTP server of the settings `SMTP_*`.
    """
    password: bool = True
    """The sign-in with a user name and a password. `false`: only the sign-in with `providers`."""
    second_factor: SecondFactor | None = None
    """A second factor of the sign-in with a password. Off by default."""
    providers: dict[MemberName, Provider] = pydantic.Field(default_factory=dict[str, Provider])
    """The OpenID Connect providers that the users can sign in with."""
