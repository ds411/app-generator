"""The sign-in of the front ends (React and Next.js): the shared parts (ADR 0011).

Each binding has its own `src/shared/auth/` with `signIn`, `signOut`,
and the calls of the password reset (ADR 0017), of the verification of
the email address (ADR 0023), and of the second factor (ADR 0024). The
sign-in form, the sign-up form (ADR 0016), the forms of the password
reset, the page of the verification link, the page of the second
factor, and the sign-out button are shared templates. Each binding has its own
`src/features/sign-up/api/` with `signUp`. The table of the permissions
of the roles (ADR 0012) is a shared template too. The checks of the app
and the menus, the links, and the actions of the UI read it. Each
binding has its own `src/shared/lib/access` with the hook `useAccess`,
because each binding finds the role of the user in another way. The
table has the owner rules too (ADR 0018): the data access of each
binding uses only the records of the user, and the forms hide the owner.
"""

from dataclasses import dataclass

from appgen.dsl.model import AppDefinition
from appgen.gen.binding import Output
from appgen.gen.naming import camel


@dataclass(frozen=True, slots=True)
class AuthPages:
    """The pages of a front end for the sign-in, next to the sign-in page."""

    sign_up: bool
    """The page `/sign-up` (ADR 0016)."""
    password_reset: bool
    """The pages `/forgot-password` and `/reset-password` (ADR 0017)."""
    verify_email: bool = False
    """The page `/verify-email` of the link that confirms the email address (ADR 0023)."""
    second_factor: bool = False
    """The page `/second-factor` of the account, and the code step of the sign-in (ADR 0024)."""


def auth_pages(definition: AppDefinition, server: bool) -> AuthPages:
    """Return the pages of the sign-in of a front end.

    `server` is True if the app has a server that sends the reset links:
    the Next.js app, or the React app with the FastAPI app. An app with
    mock data has no password reset pages, and no verification of the
    email address: its sign-up signs in at once. The second factor needs
    no server: the React app with mock data has it as a demonstration.
    """
    auth = definition.auth
    if auth is None:
        return AuthPages(sign_up=False, password_reset=False)
    return AuthPages(
        sign_up=auth.sign_up is not None,
        password_reset=auth.password_reset is not None and server,
        verify_email=auth.sign_up is not None and auth.sign_up.verify_email is not None and server,
        second_factor=auth.second_factor is not None and auth.password,
    )


@dataclass(frozen=True, slots=True)
class OwnerRule:
    """The owner of the records of an entity with owner rules (ADR 0018), in TypeScript terms."""

    relation: str
    """The many-to-one relation to the user entity, for example `organizer`."""
    key: str
    """The key of the ID of the owner in the record, for example `organizerId`."""
    element_id: str
    """The element ID of the relation."""


def owner_rules(definition: AppDefinition) -> dict[str, OwnerRule]:
    """Return the owner of each entity that an owner rule of a role names, by entity.

    All rules of an entity with an owner use the same owner (the validator
    checks it). Only a direct many-to-one owner counts (ADR 0018).
    """
    if definition.access is None:
        return {}
    found: dict[str, OwnerRule] = {}
    for role in definition.access.roles.values():
        for entity, rule in role.records.items():
            relation = definition.entities[entity].relations.get(rule.owner or "")
            if relation is not None and relation.kind == "many_to_one":
                assert rule.owner is not None
                found[entity] = OwnerRule(rule.owner, camel(rule.owner) + "Id", relation.id)
    return found


def auth_rules() -> tuple[Output, ...]:
    """Return the output rules of the forms of the sign-in, the sign-out, and the permissions."""
    return (
        *(
            Output(template=template, path=path, when="definition.auth")
            for template, path in (
                ("ui/features/sign-in/index.ts.j2", "src/features/sign-in/index.ts"),
                (
                    "ui/features/sign-in/sign-in-form.tsx.j2",
                    "src/features/sign-in/ui/sign-in-form.tsx",
                ),
                ("ui/features/sign-out/index.ts.j2", "src/features/sign-out/index.ts"),
                (
                    "ui/features/sign-out/sign-out-button.tsx.j2",
                    "src/features/sign-out/ui/sign-out-button.tsx",
                ),
            )
        ),
        *(
            Output(template=template, path=path, when="definition.auth and definition.auth.sign_up")
            for template, path in (
                ("ui/features/sign-up/index.ts.j2", "src/features/sign-up/index.ts"),
                ("ui/features/sign-up/schema.ts.j2", "src/features/sign-up/model/schema.ts"),
                (
                    "ui/features/sign-up/sign-up-form.tsx.j2",
                    "src/features/sign-up/ui/sign-up-form.tsx",
                ),
            )
        ),
        *(
            Output(template=template, path=path, when="auth_pages.password_reset")
            for template, path in (
                ("ui/features/password-reset/index.ts.j2", "src/features/password-reset/index.ts"),
                (
                    "ui/features/password-reset/forgot-password-form.tsx.j2",
                    "src/features/password-reset/ui/forgot-password-form.tsx",
                ),
                (
                    "ui/features/password-reset/reset-password-form.tsx.j2",
                    "src/features/password-reset/ui/reset-password-form.tsx",
                ),
            )
        ),
        *(
            Output(template=template, path=path, when="auth_pages.verify_email")
            for template, path in (
                (
                    "ui/features/email-verification/index.ts.j2",
                    "src/features/email-verification/index.ts",
                ),
                (
                    "ui/features/email-verification/verify-email-form.tsx.j2",
                    "src/features/email-verification/ui/verify-email-form.tsx",
                ),
            )
        ),
        *(
            Output(
                template=f"ui/features/second-factor/{name}.j2",
                path=f"src/features/second-factor/{'' if name == 'index.ts' else 'ui/'}{name}",
                when="auth_pages.second_factor",
            )
            for name in (
                "index.ts",
                "qr-code.tsx",
                "second-factor-link.tsx",
                "second-factor-page.tsx",
                "second-factor-setup.tsx",
            )
        ),
        Output(
            template="ui/lib/permissions.ts.j2",
            path="src/shared/lib/permissions.ts",
            when="definition.access",
        ),
    )


def public_kinds(definition: AppDefinition, entity: str) -> list[str]:
    """Return the kinds of the public operations of an entity, for example `list`."""
    if definition.auth is None:
        return []
    return sorted(
        {
            definition.operations[name].kind
            for name in definition.auth.public_operations
            if definition.operations[name].entity == entity
        }
    )


def kind_operations(definition: AppDefinition, entity: str) -> dict[str, str]:
    """Return the name of the first operation of each kind of an entity, for the permissions."""
    result: dict[str, str] = {}
    for name, operation in definition.operations.items():
        if operation.entity == entity:
            result.setdefault(operation.kind, name)
    return result
