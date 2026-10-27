"""The sign-in of the front ends (React and Next.js): the shared parts (ADR 0011).

Each binding has its own `src/shared/auth/` with `signIn`, `signOut`,
and the calls of the password reset (ADR 0017), of the verification of
the email address (ADR 0023), of the second factor (ADR 0024), and of the
connections to the APIs (ADR 0033). The sign-in form, the sign-up form
(ADR 0016), the forms of the password reset, the page of the
verification link, the page of the second factor, the page of the
connections, and the sign-out button are shared templates. Each binding has its own
`src/features/sign-up/api/` with `signUp`. The table of the permissions
of the roles (ADR 0012) is a shared template too. The checks of the app
and the menus, the links, and the actions of the UI read it. Each
binding has its own `src/shared/lib/access` with the hook `useAccess`,
because each binding finds the role of the user in another way. The
table has the record rules too (ADR 0018, ADR 0025): the data access of
each binding uses only the records of the rule of the role, and the forms
hide the owner and the fields that a condition of the rule sets.
"""

from dataclasses import dataclass

from appgen.dsl.access import scope_entities
from appgen.dsl.auth import has_me
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.dashboards import CustomWidget
from appgen.dsl.ui.views import AreaFilter, AvailableFilter, ListViewBase, MapView, NearFilter
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
    connections: bool = False
    """The page `/connections` of the accounts of the APIs with the authorization code flow or
    `per_user` (ADR 0033)."""


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
        connections=any(api.per_user for api in definition.apis.values()),
    )


@dataclass(frozen=True, slots=True)
class PathStep:
    """A step of the owner path of an entity (ADR 0025), in TypeScript terms."""

    entity: str
    """The entity of the step, for example `Task`."""
    relation: str
    """The many-to-one or many-to-many relation of the entity, for example `project`."""
    key: str
    """The key of the relation in the record: `projectId`, or `members` for a list."""
    many: bool
    """True for a many-to-many relation: the key has a list of IDs."""
    target: str
    """The target entity of the relation."""
    element_id: str
    """The element ID of the relation."""


@dataclass(frozen=True, slots=True)
class EntityRules:
    """The record rules of the roles on one entity (ADR 0018, ADR 0025), and its scope path.

    An entity of the scope of the memberships (ADR 0048) has rules too: a
    membership gives its operations on the records of its scopes only. An
    entity of the guests (ADR 0050) has rules too: a guest uses only its own
    records.
    """

    path: tuple[PathStep, ...]
    """The steps of the owner path to the user entity, or no steps without an owner."""
    fixed: tuple[str, ...]
    """The fields that a condition with one value can set, sorted: a form hides them."""
    element_ids: tuple[str, ...]
    """The element IDs of the rules, and of the memberships for an entity of the scope."""
    scope: tuple[PathStep, ...] | None = None
    """The steps of the path to the scope entity of the memberships, no steps for the scope
    entity, or None for an entity out of the scope."""
    guest: str | None = None
    """The key of the owner relation of the records of a guest (ADR 0050), for example
    `customerId`, or None for an entity out of `auth.guests`."""

    @property
    def direct(self) -> bool:
        """True for an owner of one many-to-one relation: a create sets it to the user."""
        return len(self.path) == 1 and not self.path[0].many


def record_rules(definition: AppDefinition) -> dict[str, EntityRules]:
    """Return the record rules of the roles by entity, for the entities that a rule names.

    All rules of an entity with an owner use the same owner (the validator
    checks it), so each entity has one path. The entities of the scope of
    the memberships (ADR 0048) have their scope path, and the entities of the
    guests (ADR 0050) the key of their owner relation.
    """
    if definition.access is None:
        return {}
    scoped = scope_entities(definition)
    memberships = definition.access.memberships
    guests = definition.auth.guests if definition.auth is not None else None
    guest_owners = guests.entities if guests is not None else {}
    owners: dict[str, str] = {}
    fixed: dict[str, set[str]] = {}
    ids: dict[str, list[str]] = {}
    for role in definition.access.roles.values():
        for entity, rule in role.records.items():
            if rule.owner is not None:
                owners[entity] = rule.owner
            single = {name for name, values in rule.conditions().items() if len(values) == 1}
            fixed.setdefault(entity, set()).update(single)
            ids.setdefault(entity, []).append(rule.id)
    if memberships is not None:
        for entity in scoped:
            ids.setdefault(entity, []).append(memberships.id)
            fixed.setdefault(entity, set())
    if guests is not None:
        for entity in guests.entities:
            ids.setdefault(entity, []).append(guests.id)
            fixed.setdefault(entity, set())
    found: dict[str, EntityRules] = {}
    for entity in ids:
        steps = path_steps(definition, entity, owners[entity]) if entity in owners else ()
        path = scoped.get(entity)
        scope = None if path is None else path_steps(definition, entity, path) if path else ()
        owner = guest_owners.get(entity)
        guest = None if owner is None else camel(owner) + "Id"
        found[entity] = EntityRules(
            steps, tuple(sorted(fixed[entity])), tuple(ids[entity]), scope, guest
        )
    return found


def path_steps(definition: AppDefinition, entity: str, path: str) -> tuple[PathStep, ...]:
    """Return the steps of a path of relations to the user entity, for example `project.members`.

    The owner paths of the record rules (ADR 0025) and the receiver paths
    of the notifications (ADR 0041) have such paths. The validator checks
    that each step exists.
    """
    steps: list[PathStep] = []
    current = entity
    for name in path.split("."):
        relation = definition.entities[current].relations[name]
        many = relation.kind == "many_to_many"
        key = camel(name) if many else camel(name) + "Id"
        steps.append(PathStep(current, name, key, many, relation.target, relation.id))
        current = relation.target
    return tuple(steps)


def uses_me(definition: AppDefinition) -> bool:
    """Return True if a filter or a default of a form has `$me`, the signed-in user.

    The front ends then have the hook `useMe` in `src/shared/lib/me`: the
    views, the forms, and the widgets read the ID of the user with it. The
    filters of the totals have `$me` too.
    """
    if definition.auth is None:
        return False
    ui = definition.ui
    values: list[object] = [
        spec.filter for entity in definition.entities.values() for spec in entity.fields.values()
    ]
    if ui is not None:
        values += [
            f.default
            for view in ui.views.values()
            if isinstance(view, ListViewBase | MapView)
            for f in view.filters.values()
            # A geo filter (ADR 0046) and an available filter (ADR 0047) have no default.
            if not isinstance(f, NearFilter | AreaFilter | AvailableFilter)
        ]
        values += [form.defaults for form in ui.forms.values()]
        values += [
            widget.filter
            for dashboard in ui.dashboards.values()
            for widget in dashboard.widgets.values()
            if not isinstance(widget, CustomWidget)
        ]
    return has_me(values)


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
        *(
            Output(
                template=f"ui/features/connections/{name}.j2",
                path=f"src/features/connections/{'' if name == 'index.ts' else 'ui/'}{name}",
                when="auth_pages.connections",
            )
            for name in ("index.ts", "connections-link.tsx", "connections-page.tsx")
        ),
        Output(
            template="ui/lib/permissions.ts.j2",
            path="src/shared/lib/permissions.ts",
            when="definition.access",
        ),
        # The operations of the memberships on the records, for the actions of the UI (ADR 0048).
        Output(
            template="ui/lib/member-access.ts.j2",
            path="src/shared/lib/member-access.ts",
            when="memberships",
        ),
        Output(
            template="src/app/providers/member-permissions.ts.j2",
            path="src/app/providers/member-permissions.ts",
            when="memberships",
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
