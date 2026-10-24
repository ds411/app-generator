"""The sign-in of the front ends (React and Next.js): the shared parts (ADR 0011).

Each binding has its own `src/shared/auth/` with `signIn` and `signOut`.
The sign-in form, the sign-up form (ADR 0016), and the sign-out button
are shared templates. Each binding has its own `src/features/sign-up/api/`
with `signUp`. The table of the permissions of the roles (ADR 0012) is a
shared template too. The checks of the app and the menus, the links, and
the actions of the UI read it. Each binding has its own
`src/shared/lib/access` with the hook `useAccess`, because each binding
finds the role of the user in another way.
"""

from appgen.dsl.model import AppDefinition
from appgen.gen.binding import Output


def auth_rules() -> tuple[Output, ...]:
    """Return the output rules of the sign-in, the sign-up, the sign-out, and the permissions."""
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
