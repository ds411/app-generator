"""Sign in to the course hub fixture, and check the values of the signed-in user in the front ends.

M36 (users and sessions): the value `$me` is the signed-in user in the
filters of the widgets, the views, and the totals, and in the defaults
of the forms. This test proves it for tests/fixtures/courses.yaml:

1. Generate the fixture with the binding, install it, run the lint, the
   type check, and `appgen check`, and build it.
2. Start the app: React with `vite preview` and its mock users, Next.js
   with `pnpm start`, PGlite, and the seed users (`DATABASE_SEED` and
   `SEED_PASSWORD`). The binding `react-api` is the React app with
   `x-react-data: api` and the FastAPI app of the fixture (SQLite, with
   the seed users).
3. Run the UI test `ui-tests/tests/sessions.spec.ts`. For each user with
   records, it signs in, and checks the stat widgets of the start page
   with `$me`, the list page whose filter starts with the user, the
   student of a new record of its form, and the totals of the user in
   the table of the lessons. The values come from the seed records.
   Then a member sees no button "Share" on the page of a lesson, and an
   admin makes a secret link of the lesson (ADR 0049). A guest opens the
   link without a sign-in, the admin revokes it, and the link opens
   nothing. In Next.js and react-api, a member and an admin open the page
   of a lesson in two browsers, and each sees the other (ADR 0052). The
   member sees a note while the admin types in the form "Edit", and sees
   no other user after the admin leaves the page or closes the browser.
   Last, a user with two roles in two courses (ADR 0048) sees and uses
   the button "Edit" on a lesson of the course whose role gives the
   change, and not on a lesson of the other course. The button "New
   lesson" shows for this user, and not for a user whose roles do not
   give the create.

Run it from the repository root:

    uv run scripts/sessions_ui_test.py [binding ...] [--out folder]

Without a binding, the script tests React, Next.js, and react-api.
scripts/check-auth-ui.sh runs it. It needs uv, pnpm, and the Chromium of
Playwright (see scripts/smoke_test.py). It uses the ports of
scripts/auth_ui_test.py. It does not need Docker.
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from auth_ui_test import (
    API_PORT,
    PASSWORDS,
    PORTS,
    UI_TESTS,
    Permissions,
    generate,
    run,
    started,
    started_api,
    wait_for,
)
from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY
from appgen.bindings.shared.mock_data import mock_data
from appgen.bindings.shared.presence import presence_plans
from appgen.bindings.shared.sharing import share_plans
from appgen.bindings.shared.views import definition_display, label
from appgen.dsl import AppDefinition, load_definition
from appgen.dsl.access import membership_roles, scope_entities
from appgen.dsl.auth import ME, has_me
from appgen.dsl.expressions import Total, parse_expression
from appgen.dsl.model import Page
from appgen.dsl.ui.common import FormAction
from appgen.dsl.ui.dashboards import RecordFilter, StatWidget
from appgen.dsl.ui.views import ListViewBase, SelectFilter, TableView
from appgen.gen.naming import kebab

DEFINITION = Path("tests/fixtures/courses.yaml")
BINDINGS = ("react", "nextjs", "react-api")

type Record = dict[str, Any]


class SessionsUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"sessions-ui-test: {binding}: {message}", flush=True)


def ids_of(value: object) -> list[str]:
    """Return the IDs of the value of a relation of a mock record: one, many, or none."""
    if isinstance(value, list):
        return [str(item) for item in cast(list[object], value)]
    return [value] if isinstance(value, str) else []


def passes(record: Record, record_filter: RecordFilter, user: str) -> bool:
    """Return True if a mock record passes a filter, with `$me` as the ID of a user.

    The test knows the conditions of the fixture: a field or a relation of
    the record (no path), and the operators `eq`, `in`, `gte`, and `lte`.
    """
    for path, condition in record_filter.items():
        if "." in path:
            raise SessionsUiTestError(f"The test does not know the path {path!r}.")
        if isinstance(condition, dict):
            items = list(condition.items())
        else:
            items = [("in" if isinstance(condition, list) else "eq", condition)]
        value = record.get(path)
        for op, operand in items:
            operands = cast(list[object], operand) if isinstance(operand, list) else [operand]
            operands = [user if item == ME else item for item in operands]
            values: list[object] = (
                [*ids_of(cast(object, value))] if isinstance(value, list) else [value]
            )
            if op in ("eq", "in"):
                ok = any(v in operands for v in values)
            elif op in ("gte", "lte") and isinstance(value, int | float):
                bound = cast(float, operands[0])
                ok = value >= bound if op == "gte" else value <= bound
            elif op in ("gte", "lte"):
                ok = False
            else:
                raise SessionsUiTestError(f"The test does not know the operator {op!r}.")
            if not ok:
                return False
    return True


def start_dashboard(definition: AppDefinition) -> str:
    """Return the dashboard of the start page."""
    page = next(p for p in definition.pages.values() if p.path == "/")
    if page.content is None or page.content.dashboard is None:
        raise SessionsUiTestError("The start page has no dashboard.")
    return page.content.dashboard


def me_list(definition: AppDefinition) -> tuple[Page, ListViewBase, str]:
    """Return the list page with a select filter of the default `$me`, the view, and the field."""
    ui = definition.ui
    assert ui is not None
    for page in definition.pages.values():
        view_name = page.content.view if page.content else None
        view = ui.views.get(view_name or "")
        if not isinstance(view, ListViewBase) or view_name is None:
            continue
        for f in view.filters.values():
            if isinstance(f, SelectFilter) and f.default == ME and "." not in f.field:
                return page, view, f.field
    raise SessionsUiTestError("No list page has a select filter with the default $me.")


def me_form(definition: AppDefinition, page: Page, user: Record) -> dict[str, str] | None:
    """Return the form of a page action with the default `$me`: its button, widget, and text."""
    ui, auth = definition.ui, definition.auth
    assert ui is not None and auth is not None
    display = definition_display(definition.entities[auth.user_entity])
    for action_name, action in page.actions.items():
        if not isinstance(action, FormAction):
            continue
        form = ui.forms[action.form]
        for name in form.fields:
            if form.defaults.get(name) == ME:
                return {
                    "label": str(action.label or label(action_name)),
                    "id": f"{kebab(action.form)}-{kebab(name)}",
                    "value": str(user[display]),
                }
    return None


def me_totals(
    definition: AppDefinition, data: dict[str, list[Record]], user: str
) -> list[dict[str, Any]]:
    """Return the table pages with a column of a count with `$me`, and the value of each row."""
    ui = definition.ui
    assert ui is not None
    found: list[dict[str, Any]] = []
    for page in definition.pages.values():
        view = ui.views.get(page.content.view or "") if page.content else None
        if not isinstance(view, TableView) or "{" in page.path:
            continue
        entity = definition.entities[view.entity]
        for name, column in view.columns.items():
            spec = entity.fields.get(name)
            if spec is None or spec.computed is None or not has_me(spec.filter):
                continue
            total = parse_expression(spec.computed)
            if not isinstance(total, Total) or total.function != "count":
                raise SessionsUiTestError(f"The test knows only a count, not {spec.computed!r}.")
            relation = entity.relations[total.relation]
            inverse = relation.inverse or ""
            display = definition_display(entity)
            rows = [
                {
                    "title": str(record[display]),
                    "value": str(
                        sum(
                            1
                            for item in data[relation.target]
                            if record["id"] in ids_of(item.get(inverse))
                            and passes(item, spec.filter or {}, user)
                        )
                    ),
                }
                for record in data[view.entity]
            ]
            found.append(
                {
                    "path": page.path,
                    "title": str(page.title),
                    "column": str(column.label or spec.label or label(name)),
                    "rows": rows,
                }
            )
    return found


def role_may(definition: AppDefinition, user: Record, operation: str) -> bool:
    """Return True if the role of `access.roles` of a user gives an operation."""
    access, auth = definition.access, definition.auth
    assert access is not None and auth is not None
    default = definition.entities[auth.user_entity].fields[access.role_field].default
    role = str(user.get(access.role_field) or default)
    return Permissions(definition, role).operation(operation)


def member_scopes(
    definition: AppDefinition, data: dict[str, list[Record]], user: Record, operation: str | None
) -> set[str]:
    """Return the IDs of the scope records whose memberships of a user give an operation.

    Without an operation, the IDs of all scope records of the memberships of the user.
    """
    access = definition.access
    memberships = access.memberships if access is not None else None
    if memberships is None:
        return set()
    roles = membership_roles(definition)
    field = definition.entities[memberships.entity].fields[memberships.role_field]
    return {
        str(record[memberships.scope])
        for record in data[memberships.entity]
        if record[memberships.user] == user["id"]
        and (
            operation is None
            or operation in roles[str(record.get(memberships.role_field) or field.default)]
        )
    }


def scope_of(
    definition: AppDefinition, data: dict[str, list[Record]], entity: str, record: Record
) -> str | None:
    """Return the ID of the scope record of a record (ADR 0048), or None out of the scope."""
    path = scope_entities(definition).get(entity)
    if path is None:
        return None
    current, target = record, entity
    for step in path.split(".") if path else []:
        target = definition.entities[target].relations[step].target
        current = next(r for r in data[target] if r["id"] == current[step])
    return str(current["id"])


def expected_share(binding: str, definition: AppDefinition) -> dict[str, Any] | None:
    """Return the values of the test of the secret links (ADR 0049), or None without `share`.

    The admin may call the update operation of the entity. The member may
    not, also not through a membership in the scope of the record
    (ADR 0048). The guest sees the title of the record and the display
    value of a related record.
    """
    plans = share_plans(definition)
    auth, access = definition.auth, definition.access
    if not plans or auth is None or access is None:
        return None
    plan = next(iter(plans.values()))
    data = mock_data(definition)
    users = data[auth.user_entity]
    record = data[plan.entity][0]
    scope = scope_of(definition, data, plan.entity, record)

    def may(user: Record) -> bool:
        return role_may(definition, user, plan.update) or (
            scope in member_scopes(definition, data, user, plan.update)
        )

    admin = next(u for u in users if role_may(definition, u, plan.update))
    member = next(u for u in users if not may(u))
    entity = definition.entities[plan.entity]
    # The record of the first many-to-one relation: the shared view shows its display value.
    relation, target = next(
        (name, r.target) for name, r in entity.relations.items() if r.kind == "many_to_one"
    )
    related = next(r for r in data[target] if r["id"] == record[relation])
    return {
        "admin": admin[auth.username_field],
        "member": member[auth.username_field],
        "path": plan.path.replace("{id}", str(record["id"])),
        "prefix": plan.shared_prefix,
        "title": str(record[definition_display(entity)]),
        "related": str(related[definition_display(definition.entities[target])]),
        # Next.js shows its page "not found" for a wrong token, React a message.
        "invalid": "This page does not exist" if binding == "nextjs" else "The link is not valid.",
    }


def expected_presence(binding: str, definition: AppDefinition) -> dict[str, Any] | None:
    """Return the values of the test of the users on a record page (ADR 0052), or None.

    The React app with mock data shows no users. The admin may call the
    update operation of the entity, so the admin types in the form of the
    button "Edit". The member reads the record. The page of the list of the
    entity is a link away from the record page.
    """
    plans = presence_plans(definition)
    auth, access, ui = definition.auth, definition.access, definition.ui
    if binding == "react" or not plans or auth is None or access is None or ui is None:
        return None
    plan = next(iter(plans.values()))
    data = mock_data(definition)
    users = data[auth.user_entity]
    default = definition.entities[auth.user_entity].fields[access.role_field].default
    update = next(
        name
        for name, op in definition.operations.items()
        if op.entity == plan.entity and op.kind == "update"
    )

    def may(user: Record, operation: str) -> bool:
        role = str(user.get(access.role_field) or default)
        return Permissions(definition, role).operation(operation)

    admin = next(u for u in users if may(u, update))
    member = next(u for u in users if may(u, plan.read) and not may(u, update))
    record = data[plan.entity][0]
    display = definition_display(definition.entities[auth.user_entity])
    page = definition.pages[plan.page]
    away = next(
        p
        for p in definition.pages.values()
        if p.entity == plan.entity and "{" not in p.path and p.content and p.content.view
    )

    def user(value: Record) -> dict[str, str]:
        name = str(value[display])
        initials = "".join(word[0].upper() for word in name.split()[:2])
        return {"username": value[auth.username_field], "name": name, "initials": initials}

    return {
        "admin": user(admin),
        "member": user(member),
        "path": page.path.replace("{id}", str(record["id"])),
        "title": str(record[definition_display(definition.entities[plan.entity])]),
        "away": {"label": str(away.title), "path": away.path},
    }


def member_record_test(
    definition: AppDefinition, data: dict[str, list[Record]], page: Page, operation: str
) -> dict[str, Any] | None:
    """Return a user with two roles, a record in the scope whose role gives an operation, and a
    record in the scope whose role does not give it. Return None if no user suits."""
    auth = definition.auth
    assert auth is not None and page.entity is not None
    display = definition_display(definition.entities[page.entity])
    records = data[page.entity]

    def record_in(scopes: set[str]) -> Record | None:
        return next(
            (r for r in records if scope_of(definition, data, page.entity or "", r) in scopes),
            None,
        )

    for user in data[auth.user_entity]:
        if role_may(definition, user, operation):
            continue
        allowed = member_scopes(definition, data, user, operation)
        first = record_in(allowed)
        second = record_in(member_scopes(definition, data, user, None) - allowed)
        if first is None or second is None:
            continue
        return {
            "username": user[auth.username_field],
            "pages": [
                {"path": page.path.replace("{id}", str(r["id"])), "title": str(r[display])}
                for r in (first, second)
            ],
        }
    return None


def expected_memberships(definition: AppDefinition) -> dict[str, Any] | None:
    """Return the values of the test of the memberships (ADR 0048), or None without them.

    A user has two roles in two scope records. A form action of a detail
    page changes the record: it shows on a record in the scope whose role
    gives the change, and not on a record in the other scope. A form
    action of a create on a list page shows for the user, and not for a
    user whose roles do not give the create. The roles of `access.roles`
    of the users do not give these operations.
    """
    access, auth, ui = definition.access, definition.auth, definition.ui
    if access is None or access.memberships is None or auth is None or ui is None:
        return None
    data = mock_data(definition)
    users = data[auth.user_entity]
    record_test: dict[str, Any] | None = None
    create_test: dict[str, Any] | None = None
    for page in definition.pages.values():
        if page.entity is None or page.entity not in scope_entities(definition):
            continue
        for action_name, action in page.actions.items():
            if not isinstance(action, FormAction):
                continue
            operation = ui.forms[action.form].operation
            kind = definition.operations[operation].kind
            button = str(action.label or label(action_name))
            if kind == "update" and "{id}" in page.path and record_test is None:
                found = member_record_test(definition, data, page, operation)
                record_test = None if found is None else {**found, "label": button}
            if kind == "create" and "{id}" not in page.path and create_test is None:
                others = [u for u in users if not role_may(definition, u, operation)]
                shown = [u for u in others if member_scopes(definition, data, u, operation)]
                hidden = [u for u in others if not member_scopes(definition, data, u, operation)]
                if shown and hidden:
                    create_test = {
                        "path": page.path,
                        "title": str(page.title),
                        "label": button,
                        "shown": shown[0][auth.username_field],
                        "hidden": hidden[0][auth.username_field],
                    }
    if record_test is None or create_test is None:
        raise SessionsUiTestError("The test needs a user with two roles of the memberships.")
    return {"record": record_test, "create": create_test}


def expected_sessions(binding: str, definition: AppDefinition) -> dict[str, Any]:
    """Return the values of the UI test: for each user with records, what the pages show."""
    ui, auth = definition.ui, definition.auth
    assert ui is not None and auth is not None
    data = mock_data(definition)
    dashboard = ui.dashboards[start_dashboard(definition)]
    page, view, field = me_list(definition)
    title = definition_display(definition.entities[view.entity])
    users: list[dict[str, Any]] = []
    for user in data[auth.user_entity]:
        records = data[view.entity]
        own = [r for r in records if user["id"] in ids_of(r.get(field))]
        if not own:
            continue
        own_titles = {str(r[title]) for r in own}
        stats = [
            {
                "label": str(widget.label or label(name)),
                "value": str(
                    sum(1 for r in data[widget.entity] if passes(r, widget.filter, user["id"]))
                ),
            }
            for name, widget in dashboard.widgets.items()
            if isinstance(widget, StatWidget) and has_me(widget.filter)
        ]
        users.append(
            {
                "username": user[auth.username_field],
                "stats": stats,
                "list": {
                    "path": page.path,
                    "title": str(page.title),
                    "own": sorted(own_titles),
                    "others": sorted({str(r[title]) for r in records} - own_titles),
                },
                "form": me_form(definition, page, user),
                "totals": me_totals(definition, data, user["id"]),
            }
        )
    if len(users) < 2:
        raise SessionsUiTestError("The test needs two users with records in the seed data.")
    return {
        "password": PASSWORDS["nextjs" if binding == "react-api" else binding],
        "users": users,
        "share": expected_share(binding, definition),
        "presence": expected_presence(binding, definition),
        "memberships": expected_memberships(definition),
    }


def check_ui(binding: str, definition: AppDefinition) -> None:
    """Run the UI test of the signed-in users on the app that runs."""
    name = f"{binding}-sessions"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    ui_binding = "react" if binding == "react-api" else binding
    expected = {
        **expected_ui(ui_binding, definition),
        "sessions": expected_sessions(binding, definition),
    }
    expected_file.write_text(json.dumps(expected, indent=2) + "\n")
    env = {
        "APPGEN_BASE_URL": f"http://localhost:{PORTS[binding]}",
        "APPGEN_UI_EXPECTED": str(expected_file),
        "APPGEN_UI_OUTPUT": str((UI_TESTS / "test-results" / name).resolve()),
    }
    with (UI_TESTS / ".install.lock").open("w") as lock:
        # Only one check at a time installs the packages of the UI tests.
        fcntl.flock(lock, fcntl.LOCK_EX)
        run("pnpm", "install", "--silent", "--frozen-lockfile", cwd=UI_TESTS)
    command = ["pnpm", "exec", "playwright", "test", "tests/sessions.spec.ts", "--project", "light"]
    run(*command, cwd=UI_TESTS, env=env)


def build(binding: str, definition: Path, app: Path, env: dict[str, str] | None = None) -> None:
    """Install the front end, run the lint, the type check, and the trace check, and build it."""
    log(binding, "pnpm install, lint, type check, appgen check, and build")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "lint", cwd=app)
    run("pnpm", "--silent", "typecheck", cwd=app, quiet=True)
    run("uv", "run", "--locked", "appgen", "check", str(definition), str(app), quiet=True)
    run("pnpm", "--silent", "build", cwd=app, env=env, quiet=True)


def react_api_test(out: Path) -> None:
    """Sign in to the React app with the FastAPI app of the fixture, with the seed users."""
    binding, definition = "react-api", load_definition(DEFINITION)
    source = out / "courses.yaml"
    marker = "\napp:\n"
    text = DEFINITION.read_text()
    if marker not in text:
        raise SessionsUiTestError(f"{DEFINITION} has no 'app:' line.")
    source.write_text(text.replace(marker, f"{marker}  {DATA_KEY}: api\n", 1))
    api, web = out / "react-api-fastapi", out / binding
    generate(source, "fastapi", api)
    generate(source, "react", web)
    log(binding, "uv sync")
    # The FastAPI app has its own virtual environment.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    subprocess.run(["uv", "sync", "--quiet"], cwd=api, env=env, check=True)
    build(binding, source, web, env={"VITE_API_URL": f"http://127.0.0.1:{API_PORT}"})
    seed = {"DATABASE_SEED": "true", "SEED_PASSWORD": PASSWORDS["nextjs"]}
    with started_api(api, seed), started(binding, web):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the signed-in users (Playwright)")
        check_ui(binding, definition)
    log(binding, "passed")


def sessions_ui_test(binding: str, out: Path) -> None:
    if binding == "react-api":
        react_api_test(out)
        return
    definition = load_definition(DEFINITION)
    app = out / binding
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app)
    with started(binding, app):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the signed-in users (Playwright)")
        check_ui(binding, definition)
    log(binding, "passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("bindings", nargs="*", metavar="binding", help=", ".join(BINDINGS))
    parser.add_argument(
        "--out", type=Path, help="The folder of the apps; the default is a new one."
    )
    args = parser.parse_args()
    bindings: list[str] = args.bindings or list(BINDINGS)
    unknown = [b for b in bindings if b not in BINDINGS]
    if unknown:
        parser.error(f"unknown binding: {', '.join(unknown)}")
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-sessions-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    try:
        for binding in bindings:
            sessions_ui_test(binding, out)
    except (SessionsUiTestError, subprocess.CalledProcessError) as error:
        print(f"sessions-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
