"""Sign in to the room booking example with each role, and check what the front ends show.

ADR 0012: the menus, the links, and the actions of the front ends show
only the pages and the operations that the role of the user allows. This
test proves it for the room booking example (`examples/room-booking`):

1. Generate the example with the binding, install it, and build it.
2. Start the app: React with `vite preview` and its mock users, Next.js
   with `pnpm start`, PGlite, and the seed users (`DATABASE_SEED` and
   `SEED_PASSWORD`).
3. Run the UI test `ui-tests/tests/auth.spec.ts` in the light and the
   dark mode. For each role, it signs in as a user of the role, and
   compares the menu with the menu that the definition allows and with
   an approved screenshot. It also opens the pages that the role may not
   open ("not found"), and checks the page actions. Without a session,
   the menu of a public page shows only the public pages. Last, it
   compares the sign-up page with an approved screenshot, and signs up a
   new user (ADR 0016). In the Next.js app, the new user confirms the
   email address with the link of an email before the sign-in (ADR
   0023), and the test compares the page of the link with an approved
   screenshot. In the Next.js app, it compares the password reset pages
   with approved screenshots, resets the password of a user with the
   link of an email, and signs in with the new password (ADR 0017). The
   Next.js app sends the emails to the mock SMTP server of
   scripts/mock_smtp.py (`auth.delivery: smtp`), and the test reads them
   in its file. For each record rule (ADR 0018), it signs in as a
   user of the role, and checks that the list and the detail page show
   only the records of the rule, and that the form of a new record does
   not show the owner. For each provider that makes users (ADR 0020), it
   signs in with the button of the provider, and compares the menu with
   the menu of the role of the new user. With a second factor (ADR 0024),
   a user turns it on, signs out, and signs in with a code that the test
   computes from the key on the page. Next.js signs in through the
   mock provider of scripts/mock_oidc.py. React with mock data signs in
   a mock user at once. The receiver of a change finds the notice in the
   bell (ADR 0041), and a user that a text mentions finds one too (ADR
   0043). The receiver turns off the emails of a notification on the
   page /notice-settings. In the Next.js app, the test first calls the
   route of the job `notice_emails` (`JOBS_SECRET`), and finds the email
   of the notice in the file of the mock SMTP server (ADR 0044).
4. For React and Next.js, generate tests/fixtures/record-rules.yaml too,
   and run only the tests of the record rules (ADR 0025): a member sees
   the records of the teams of the member through an owner path, with a
   condition on the status of the tasks, and a reviewer sees only the
   records with the values of the conditions. The form of a new task of
   a reviewer does not show the status, which the rule sets.
5. The binding `react-api` is the React app with `x-react-data: api` and
   the FastAPI app of the example (SQLite). The script starts both and
   the mock provider, and runs only the test of the sign-in with a
   provider: the browser goes through the flow of the FastAPI app, and
   comes back to the React app with a token.
6. For Next.js and react-api, generate tests/fixtures/cognito-sign-in.yaml
   too, and run only the test of the sign-in with a provider, through the
   mock user pool of Amazon Cognito of scripts/mock_oidc.py: the
   authorization request has `identity_provider`, the endpoints are on
   another origin than the issuer, and the ID token does not mark the
   email address as verified (`trust_email`, ADR 0020). One user signs
   in with a group of each role of `roles` in turn, and then without a
   group, and sees the menu of the role each time: the test changes the
   redirect of the start of the sign-in, so that the authorization
   request has `login_hint` and the mock parameter `groups`.

Run it from the repository root:

    uv run scripts/auth_ui_test.py [binding ...] [--out folder]

Without a binding, the script tests React, Next.js, and react-api. It
needs uv, pnpm, and the Chromium of Playwright (see scripts/smoke_test.py).
It uses the ports 5440 (React), 3440 (Next.js), 5441 and 8440 (react-api),
9440 (the mock provider), and 2440 (the mock SMTP server). It does not need
Docker.

Environment variables:
    APPGEN_UPDATE_SCREENSHOTS     1: write the approved screenshots again
                                  (ui-tests/approved/<binding>/room-booking/).
    PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the test, instead of the one
                                  that Playwright installs. Without both, the test
                                  uses /opt/pw-browsers/chromium if it exists.
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for an app to start (default 180).
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import mock_oidc
import mock_smtp
from smoke_test import expected_ui

from appgen.bindings.nextjs.db import build_tables
from appgen.bindings.react.api_client import DATA_KEY
from appgen.bindings.shared.auth import record_rules
from appgen.bindings.shared.mock_data import mock_data
from appgen.bindings.shared.notices import email_notifications
from appgen.bindings.shared.views import definition_display, label
from appgen.dsl import AppDefinition, load_definition
from appgen.dsl.access import ALL, RecordRule
from appgen.dsl.model import Page
from appgen.dsl.rules import EntityOverlapRule
from appgen.dsl.ui.common import FormAction, NavigateAction, OperationAction
from appgen.dsl.ui.states import effective_states
from appgen.gen.naming import kebab

DEFINITION = Path("examples/room-booking/app.yaml")
UI_TESTS = Path("ui-tests")
BINDINGS = ("react", "nextjs", "react-api")
PORTS = {"react": 5440, "nextjs": 3440, "react-api": 5441}
PASSWORDS = {"react": "password", "nextjs": "auth-ui-test-password"}
"""The password of the users: the mock password of React, and SEED_PASSWORD of Next.js."""
API_PORT = 8440
"""The port of the FastAPI app of the binding `react-api`."""
OIDC_PORT = 9440
"""The port of the mock OpenID Connect provider. scripts/check-fastapi.sh uses the default port."""
SMTP_PORT = 2440
"""The port of the mock SMTP server, for the emails of the Next.js app."""
MAILBOX = "messages.jsonl"
"""The file in the app folder that gets each email of the mock SMTP server as a JSON line."""
JOBS_SECRET = "auth-ui-test-jobs-secret"
"""The secret of the routes of the jobs of the Next.js app (ADR 0029)."""
PROVIDER_TEST = "signs in with the provider"
"""The part of the name of the UI test of the sign-in with a provider, for `react-api`."""
RULES_DEFINITION = Path("tests/fixtures/record-rules.yaml")
"""The definition with record rules of conditions and owner paths (ADR 0025)."""
RULES_TEST = "the record rule of the role"
"""The part of the names of the UI tests of the record rules, for RULES_DEFINITION."""
COGNITO_DEFINITION = Path("tests/fixtures/cognito-sign-in.yaml")
"""The definition with a user pool of Amazon Cognito as its provider (ADR 0020)."""


class AuthUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"auth-ui-test: {binding}: {message}", flush=True)


def run(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, quiet: bool = False
) -> None:
    output = subprocess.DEVNULL if quiet else None
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})}, stdout=output)


class Permissions:
    """The pages and the operations that a role may use, as the apps check them."""

    def __init__(self, definition: AppDefinition, role: str | None) -> None:
        assert definition.auth is not None and definition.access is not None
        self.auth = definition.auth
        self.role = definition.access.roles.get(role) if role is not None else None

    def page(self, name: str) -> bool:
        if name in self.auth.public_pages:
            return True
        return self.role is not None and (ALL in self.role.pages or name in self.role.pages)

    def operation(self, name: str) -> bool:
        if name in self.auth.public_operations:
            return True
        return self.role is not None and (
            ALL in self.role.operations or name in self.role.operations
        )


def menu_labels(definition: AppDefinition, allowed: Permissions) -> list[str]:
    """Return the labels of the menu of the start page that a role sees, in order."""
    ui = definition.ui
    assert ui is not None and ui.defaults is not None
    page = definition.pages.get("dashboard")
    layout = ui.layouts[(page.layout if page and page.layout else None) or str(ui.defaults.layout)]
    assert layout.sidebar is not None and layout.sidebar.navigation is not None
    menu = ui.navigation[layout.sidebar.navigation]
    items = [*menu.items.values(), *(i for g in menu.groups.values() for i in g.items.values())]
    labels: list[str] = []
    for item in items:
        subs = [s for s in item.items.values() if allowed.page(s.page)]
        if allowed.page(item.page) or subs:
            labels.append(str(item.label or definition.pages[item.page].title))
            labels += [str(s.label or definition.pages[s.page].title) for s in subs]
    return labels


def page_actions(definition: AppDefinition, allowed: Permissions) -> list[dict[str, Any]]:
    """Return the actions of the pages without path parameters, and if the role sees them."""
    ui = definition.ui
    assert ui is not None
    found: list[dict[str, Any]] = []
    for name, page in definition.pages.items():
        if "{" in page.path or not allowed.page(name):
            continue
        for action_name, action in page.actions.items():
            if isinstance(action, FormAction):
                shown = allowed.operation(ui.forms[action.form].operation)
            elif isinstance(action, NavigateAction):
                shown = allowed.page(action.page)
            elif isinstance(action, OperationAction):
                continue
            else:
                shown = True
            title = str(page.title)
            found.append(
                {
                    "path": page.path,
                    "title": title,
                    "label": str(action.label or label(action_name)),
                    "shown": shown,
                }
            )
    return found


def expected_sign_up(binding: str, definition: AppDefinition, app: Path) -> dict[str, Any] | None:
    """Return the values of the sign-up: the required fields, and the menu of a new user.

    Only the Next.js app has the page of the verification link: the React
    app with mock data signs in a new user at once. The Next.js app sends
    each link in an email to the mock SMTP server.
    """
    auth, access = definition.auth, definition.access
    assert auth is not None and access is not None
    if auth.sign_up is None:
        return None
    entity = definition.entities[auth.user_entity]
    fields: list[dict[str, str]] = []
    for name in auth.sign_up.fields:
        field = entity.fields[name]
        if not field.required or field.default is not None:
            continue
        values = {"email": "new.user.{n}@example.com", "url": "https://example.com/{n}"}
        if field.type not in ("string", "text", *values):
            raise AuthUiTestError(f"The test cannot fill the required sign-up field {name!r}.")
        fields.append({"id": f"sign-up-{kebab(name)}", "value": values.get(field.type, "New {n}")})
    role = auth.sign_up.default_role or str(entity.fields[access.role_field].default)
    address = definition.address_field()
    verify: dict[str, str] | None = None
    if auth.sign_up.verify_email is not None and binding == "nextjs" and address is not None:
        verify = {"addressId": f"sign-up-{kebab(address)}", "mailbox": str(app / MAILBOX)}
    return {
        "fields": fields,
        "usernameId": f"sign-up-{kebab(auth.username_field)}",
        "password": "a-new-password-for-the-test",
        "menu": menu_labels(definition, Permissions(definition, role)),
        "verifyEmail": verify,
    }


def expected_password_reset(
    binding: str, definition: AppDefinition, app: Path, used: set[str]
) -> dict[str, Any] | None:
    """Return the values of the password reset: a user apart from the users of the other tests.

    Only the Next.js app has the reset pages: the React app with mock data
    has no server that sends the links. The Next.js app sends each link in
    an email to the mock SMTP server, and the test reads it in its file.
    """
    auth = definition.auth
    assert auth is not None
    if auth.password_reset is None or binding != "nextjs":
        return None
    users = [
        u for u in mock_data(definition)[auth.user_entity] if u[auth.username_field] not in used
    ]
    return {"username": users[-1][auth.username_field], "mailbox": str(app / MAILBOX)}


def expected_second_factor(definition: AppDefinition, used: set[str]) -> dict[str, Any] | None:
    """Return the values of the second factor: a user apart from the users of the other tests.

    The test turns on the factor on the page `/second-factor`, signs out,
    and signs in with a code that it computes from the key on the page
    (ADR 0024). The React app with mock data keeps the factor in the
    browser tab, as a demonstration.
    """
    auth, access = definition.auth, definition.access
    assert auth is not None and access is not None
    if auth.second_factor is None:
        return None
    users = [
        u for u in mock_data(definition)[auth.user_entity] if u[auth.username_field] not in used
    ]
    user = users[-1]
    role = user.get(access.role_field)
    if not isinstance(role, str) or role in auth.second_factor.required_roles:
        raise AuthUiTestError("The user of the second factor needs a role that may turn it off.")
    return {
        "username": user[auth.username_field],
        "menu": menu_labels(definition, Permissions(definition, role)),
    }


def overlaps(definition: AppDefinition, entity: str, record: dict[str, Any]) -> bool:
    """Return True if a record breaks a `no_overlap` rule of its entity: a change of it fails."""
    records = mock_data(definition)[entity]
    for rule in definition.entities[entity].rules.values():
        if not isinstance(rule, EntityOverlapRule):
            continue
        for other in records:
            if other["id"] == record["id"] or any(
                other.get(name) != record.get(name) for name in rule.scope
            ):
                continue
            if str(other[rule.start]) < str(record[rule.end]) and str(record[rule.start]) < str(
                other[rule.end]
            ):
                return True
    return False


def expected_notice(definition: AppDefinition, used: set[str]) -> dict[str, Any] | None:
    """Return the values of the test of the notices (ADR 0041): a change, and its receiver.

    The first notification of a transition without `run`, with a receiver
    of one relation, gives the values. A user of a role with all
    operations changes the state of a record of another user with the edit
    form of the detail page. Then the receiver signs in, and finds the
    notice in the bell of the top bar. The record breaks no `no_overlap`
    rule, because the Next.js app checks the rules of a change. The
    receiver is a user of the other tests if one fits. The React app with
    mock data keeps the notices in the browser tab.
    """
    auth, access = definition.auth, definition.access
    assert auth is not None and access is not None
    data = mock_data(definition)
    users = data[auth.user_entity]
    actor = next(
        (u for u in users if Permissions(definition, u.get(access.role_field)).operation(ALL)),
        None,
    )
    for name, notification in definition.notifications.items():
        parts = notification.transition_parts()
        page = next(
            (
                p
                for p in definition.pages.values()
                if p.entity == notification.entity and p.path.endswith("/{id}")
            ),
            None,
        )
        if parts is None or actor is None or page is None:
            continue
        entity = definition.entities[notification.entity]
        workflow = next(
            w
            for w in definition.workflows.values()
            if w.entity == notification.entity and parts[1] in w.transitions
        )
        transition = workflow.transitions[parts[1]]
        if transition.run is not None:
            # The custom operation of the transition is a stub: the change fails.
            continue
        receivers = [
            r
            for r in notification.receivers
            if "." not in r and entity.relations[r].kind == "many_to_one"
        ]
        records = [
            (record, user)
            for receiver in receivers
            for record in data[notification.entity]
            if record.get(workflow.field) in transition.from_
            for user in users
            if user["id"] == record.get(receiver)
            and user["id"] != actor["id"]
            and not overlaps(definition, notification.entity, record)
        ]
        records.sort(key=lambda item: item[1][auth.username_field] not in used)
        if not records:
            continue
        record, user = records[0]
        values: dict[str, str] = {}
        for name in notification.values():
            if name in entity.fields:
                values[name] = str(record.get(name) or "")
                continue
            target = entity.relations[name].target
            display = definition_display(definition.entities[target])
            related = next((r for r in data[target] if r["id"] == record.get(name)), {})
            values[name] = str(related.get(display) or "")
        return {
            "notification": name,
            "actor": actor[auth.username_field],
            "receiver": user[auth.username_field],
            "path": page.path.replace("{id}", str(record["id"])),
            "field": label(workflow.field),
            "value": label(transition.to),
            "text": notification.text.format_map(values),
        }
    return None


def expected_notice_emails(
    binding: str, definition: AppDefinition, app: Path, notice: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the values of the test of the emails of the notices (ADR 0044), or None.

    After the test of the notices, the receiver opens the page
    /notice-settings with the link of the bell, finds a switch for each
    notification with emails, and turns off the first one. In the Next.js
    app, the test first calls the route of the job `notice_emails`, and
    finds the email of the notice in the file of the mock SMTP server. The
    React app with mock data sends no emails.
    """
    auth = definition.auth
    emails = email_notifications(definition)
    if auth is None or notice is None or not emails:
        return None
    address = definition.address_field()
    assert address is not None
    users = mock_data(definition)[auth.user_entity]
    receiver = next(u for u in users if u[auth.username_field] == notice["receiver"])
    sent = binding == "nextjs" and any(n.name == notice["notification"] for n in emails)
    return {
        "labels": [n.label for n in emails],
        "mailbox": str(app / MAILBOX) if sent else None,
        "to": receiver[address],
        "secret": JOBS_SECRET,
    }


def expected_mention(definition: AppDefinition, used: set[str]) -> dict[str, Any] | None:
    """Return the values of the test of the mentions (ADR 0043): a text, and the user it mentions.

    A user of a role with all operations edits a record of the first entity
    with a text with mentions and a detail page, with the edit form of the
    page, and mentions another user from the list of the text area. The
    detail page shows the mention as a link to the page of the user, if one
    exists. Then the user signs in, and finds the notice in the bell. The
    user is not a user of the other tests, and the record breaks no
    `no_overlap` rule.
    """
    auth, access = definition.auth, definition.access
    assert auth is not None and access is not None
    data = mock_data(definition)
    users = data[auth.user_entity]
    actor = next(
        (u for u in users if Permissions(definition, u.get(access.role_field)).operation(ALL)),
        None,
    )
    if actor is None:
        return None
    names = definition_display(definition.entities[auth.user_entity])
    receiver = next(
        (
            u
            for u in users
            if u["id"] != actor["id"] and u[auth.username_field] not in used and u.get(names)
        ),
        None,
    )
    user_page = detail_page(definition, auth.user_entity)
    for entity_name, entity in definition.entities.items():
        field = next((n for n, f in entity.fields.items() if f.mentions), None)
        page = detail_page(definition, entity_name)
        record = next(
            (r for r in data[entity_name] if not overlaps(definition, entity_name, r)), None
        )
        if field is None or page is None or record is None or receiver is None:
            continue
        title = record.get(definition_display(entity)) or record["id"]
        return {
            "actor": actor[auth.username_field],
            "receiver": receiver[auth.username_field],
            "name": str(receiver[names]),
            "path": page.path.replace("{id}", str(record["id"])),
            "field": str(entity.fields[field].label or label(field)),
            "userPath": user_page.path.replace("{id}", str(receiver["id"])) if user_page else None,
            "text": f"You are mentioned in {title}.",
        }
    return None


def detail_page(definition: AppDefinition, entity: str) -> Page | None:
    """Return the first page of a record of an entity, with the path parameter `{id}`."""
    return next(
        (p for p in definition.pages.values() if p.entity == entity and p.path.endswith("/{id}")),
        None,
    )


def entity_pages(
    definition: AppDefinition, entity: str, allowed: Permissions
) -> tuple[str | None, str | None]:
    """Return the first list page and the first detail page of an entity that a role may open."""
    ui = definition.ui
    assert ui is not None
    lists: list[str] = []
    details: list[str] = []
    for name, page in definition.pages.items():
        view = ui.views.get(page.content.view or "") if page.content else None
        if view is None or view.entity != entity or not allowed.page(name):
            continue
        if view.kind == "detail" and page.path.endswith("/{id}"):
            details.append(name)
        elif view.kind != "detail" and "{" not in page.path:
            lists.append(name)
    return (lists[0] if lists else None), (details[0] if details else None)


def owns_join_table(definition: AppDefinition, entity: str, name: str) -> bool:
    """Return True if the Next.js table of an entity has the join table of a relation."""
    relation = definition.entities[entity].relations[name]
    table = next(t for t in build_tables(definition) if t.entity == entity)
    return any(join.element_id == relation.id for join in table.join_tables)


def linked_ids(
    binding: str,
    definition: AppDefinition,
    data: dict[str, Any],
    entity: str,
    name: str,
    record: Any,
) -> list[str]:
    """Return the IDs of the targets of a relation of a mock record, as the app has them.

    The mock data has a list on each side of a many-to-many relation. The
    mock store of React reads the list of the record. The seed of Next.js
    fills the join table with the lists of the side that has the table, and
    the other side reads the join table.
    """
    relation = definition.entities[entity].relations[name]
    value = record.get(name)
    if relation.kind != "many_to_many":
        return [value] if isinstance(value, str) else []
    if binding == "nextjs" and relation.inverse and not owns_join_table(definition, entity, name):
        targets = data[relation.target]
        return [t["id"] for t in targets if record["id"] in (t.get(relation.inverse) or [])]
    return [str(item) for item in cast(list[Any], value or [])]


def in_rule(
    binding: str,
    definition: AppDefinition,
    data: dict[str, Any],
    entity: str,
    rule: RecordRule,
    record: Any,
    user_id: str,
) -> bool:
    """Return True if a user of a record rule may use a mock record (ADR 0018, ADR 0025)."""
    if any(record.get(f) not in values for f, values in rule.conditions().items()):
        return False
    if rule.owner is None:
        return True
    records, current = [record], entity
    steps = rule.owner.split(".")
    for index, step in enumerate(steps):
        ids = [i for r in records for i in linked_ids(binding, definition, data, current, step, r)]
        if index == len(steps) - 1:
            return user_id in ids
        current = definition.entities[current].relations[step].target
        records = [r for r in data[current] if r["id"] in ids]
    return False


def rule_form(
    definition: AppDefinition, entity: str, rule: RecordRule, page: Page, allowed: Permissions
) -> dict[str, Any] | None:
    """Return the form of a new record on a list page, if a record rule hides fields of it.

    For a user of the rule, a form does not show the owner of one
    many-to-one relation, and the fields that a condition with one value
    sets.
    """
    ui = definition.ui
    assert ui is not None
    direct = rule.owner is not None and record_rules(definition)[entity].direct
    hidden = {f for f, values in rule.conditions().items() if len(values) == 1}
    if direct and rule.owner is not None:
        hidden.add(rule.owner)
    for action_name, action in page.actions.items():
        if not isinstance(action, FormAction):
            continue
        form = ui.forms[action.form]
        if (
            form.entity != entity
            or definition.operations[form.operation].kind != "create"
            or not allowed.operation(form.operation)
        ):
            continue
        shown = [f for f in form.fields if f not in hidden]
        fixed = [f for f in form.fields if f in hidden]
        if shown and fixed:
            return {
                "label": str(action.label or label(action_name)),
                "firstId": f"{kebab(action.form)}-{kebab(shown[0])}",
                "hiddenIds": [f"{kebab(action.form)}-{kebab(f)}" for f in fixed],
            }
    return None


def expected_record_rules(binding: str, definition: AppDefinition) -> list[dict[str, Any]]:
    """Return the checks of the record rules of `read` (ADR 0018, ADR 0025): what a user sees.

    For a rule with an owner, the user is the user of the role with the
    most records of the rule in the mock data (the Next.js app seeds the
    same records). Else it is the first user of the role. The list page
    shows the titles of the records of the rule, and no title of another
    record. A detail page of another record shows "not found" (Next.js)
    or the empty state of the view (React). The form of a new record on
    the list page does not show the fields that the rule sets.
    """
    auth, access, ui = definition.auth, definition.access, definition.ui
    assert auth is not None and access is not None and ui is not None
    data = mock_data(definition)
    checks: list[dict[str, Any]] = []
    for role_name, role in access.roles.items():
        allowed = Permissions(definition, role_name)
        users = [u for u in data[auth.user_entity] if u.get(access.role_field) == role_name]
        for entity, rule in role.records.items():
            if "read" not in rule.operations:
                continue
            records = data[entity]
            title = definition_display(definition.entities[entity])

            def shown(user: Any, entity: str = entity, rule: RecordRule = rule) -> list[Any]:
                return [
                    r
                    for r in data[entity]
                    if in_rule(binding, definition, data, entity, rule, r, user["id"])
                ]

            user = max(users, key=lambda u: len(shown(u))) if rule.owner else users[0]
            own = shown(user)
            own_ids = {r["id"] for r in own}
            own_titles = {str(r[title]) for r in own}
            others = [r for r in records if r["id"] not in own_ids]
            others = [r for r in others if str(r[title]) not in own_titles]
            list_page, detail_page = entity_pages(definition, entity, allowed)
            if not own or not others or list_page is None or detail_page is None:
                raise AuthUiTestError(
                    f"The record rule of {role_name!r} on {entity!r} needs records in the rule "
                    "and out of it in the mock data, a list page, and a detail page."
                )
            detail = definition.pages[detail_page]
            view = ui.views[str(detail.content.view if detail.content else "")]
            page = definition.pages[list_page]
            checks.append(
                {
                    "role": role_name,
                    "entity": entity,
                    "username": user[auth.username_field],
                    "listPath": page.path,
                    "listTitle": str(page.title),
                    "own": sorted(own_titles),
                    "others": sorted({str(r[title]) for r in others}),
                    "ownPath": detail.path.replace("{id}", str(own[0]["id"])),
                    "ownTitle": str(own[0][title]),
                    "otherPath": detail.path.replace("{id}", str(others[0]["id"])),
                    "otherTitle": str(others[0][title]),
                    "otherMessage": "This page does not exist"
                    if binding == "nextjs"
                    else str(effective_states(definition, view).empty.title or "No records yet"),
                    "form": rule_form(definition, entity, rule, page, allowed),
                }
            )
    return checks


def expected_providers(binding: str, definition: AppDefinition) -> list[dict[str, Any]]:
    """Return the sign-ins with each provider that makes users: the button, and the menus.

    Through the mock provider, the user is a new user with the default
    role of the provider. With `roles`, one user signs in with a group of
    each role in turn, and then without a group: the user gets the role of
    the group each time, and at last the default role. With mock data, the
    React app signs in the mock user of the provider: the first one with
    the first role of `roles`, or else with the default role.
    """
    auth, access = definition.auth, definition.access
    assert auth is not None and access is not None
    users = mock_data(definition)[auth.user_entity]
    default = definition.entities[auth.user_entity].fields[access.role_field].default

    def menu(role: str | None) -> list[str]:
        return menu_labels(definition, Permissions(definition, role))

    checks: list[dict[str, Any]] = []
    for name, provider in auth.providers.items():
        if not provider.create_users:
            continue
        role = provider.default_role or default
        roles = provider.roles
        if binding == "react":
            wanted = next(iter(roles.map.values())) if roles else role
            user = next((u for u in users if u.get(access.role_field) == wanted), users[0])
            value = user.get(access.role_field)
            role = value if isinstance(value, str) else None
        sign_ins: list[dict[str, Any]] = [{"menu": menu(role)}]
        if roles is not None and binding != "react":
            email = f"{name}.grouped@example.com"
            groups = {group_role: group for group, group_role in reversed(roles.map.items())}
            sign_ins = [
                {"loginHint": email, "groups": [groups[r]], "menu": menu(r)}
                for r in dict.fromkeys(roles.map.values())
            ]
            if provider.default_role is not None:
                sign_ins.append(
                    {"loginHint": email, "groups": [], "menu": menu(provider.default_role)}
                )
        checks.append({"name": name, "title": str(provider.title or name), "signIns": sign_ins})
    return checks


def expected_auth(binding: str, definition: AppDefinition, app: Path) -> dict[str, Any]:
    """Return the values of the UI test: the users, and what each role sees."""
    auth, access = definition.auth, definition.access
    assert auth is not None and access is not None
    users = mock_data(definition)[auth.user_entity]
    roles: list[dict[str, Any]] = []
    for role in access.roles:
        user = next((u for u in users if u.get(access.role_field) == role), None)
        if user is None:
            raise AuthUiTestError(f"No mock user of {auth.user_entity} has the role {role!r}.")
        allowed = Permissions(definition, role)
        roles.append(
            {
                "role": role,
                "username": user[auth.username_field],
                "menu": menu_labels(definition, allowed),
                "deniedPaths": [
                    p.path
                    for n, p in definition.pages.items()
                    if "{" not in p.path and not allowed.page(n)
                ],
                "actions": page_actions(definition, allowed),
            }
        )
    record_checks = expected_record_rules(binding, definition)
    used = {check["username"] for check in [*roles, *record_checks]}
    notice = expected_notice(definition, used)
    if notice is not None:
        used.add(notice["receiver"])
    password_reset = expected_password_reset(binding, definition, app, used)
    if password_reset is not None:
        used.add(password_reset["username"])
    mention = expected_mention(definition, used)
    if mention is not None:
        used.add(mention["receiver"])
    anonymous = Permissions(definition, None)
    public = next(
        definition.pages[n] for n in auth.public_pages if "{" not in definition.pages[n].path
    )
    return {
        "app": definition.app.name,
        "password": PASSWORDS[binding],
        "roles": roles,
        "anonymous": {
            "path": public.path,
            "title": str(public.title),
            "menu": menu_labels(definition, anonymous),
            "actions": [a for a in page_actions(definition, anonymous) if a["path"] == public.path],
        },
        "signUp": expected_sign_up(binding, definition, app),
        "passwordReset": password_reset,
        "secondFactor": expected_second_factor(definition, used),
        "recordRules": record_checks,
        "providers": expected_providers(binding, definition),
        "notice": notice,
        "noticeEmails": expected_notice_emails(binding, definition, app, notice),
        "mention": mention,
    }


def wait_for(binding: str, url: str) -> None:
    """Wait until a URL answers with 200."""
    timeout = float(os.environ.get("APPGEN_SMOKE_TIMEOUT", "180"))
    deadline = time.monotonic() + timeout
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    return
                last = f"status {response.status}"
        except (OSError, urllib.error.HTTPError) as error:
            last = str(error)
        time.sleep(1)
    raise AuthUiTestError(f"{binding}: {url} did not answer in {timeout:.0f} s ({last}).")


@contextmanager
def started(binding: str, app: Path, definition: Path = DEFINITION) -> Generator[None]:
    """Start the built app of a definition, and stop it at the end."""
    port = str(PORTS[binding])
    env = {**os.environ, "PORT": port}
    if binding in ("react", "react-api"):
        command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    else:
        run("pnpm", "--silent", "db:generate", cwd=app, quiet=True)
        env |= {
            "DATABASE_URL": f"pglite:{app / '.pglite'}",
            "DATABASE_MIGRATE": "true",
            "DATABASE_SEED": "true",
            "SEED_PASSWORD": PASSWORDS[binding],
            "AUTH_SECRET": "auth-ui-test-secret",
            "ENVIRONMENT": "development",
            "PUBLIC_URL": f"http://localhost:{port}",
            # The password reset and the sign-up send the links to the mock SMTP server.
            "SMTP_HOST": "127.0.0.1",
            "SMTP_PORT": str(SMTP_PORT),
            "SMTP_TLS": "none",
            "SMTP_FROM": "no-reply@example.com",
            # The test calls the route of the job of the emails of the notices.
            "JOBS_SECRET": JOBS_SECRET,
            **provider_env(load_definition(definition)),
        }
        command = ["pnpm", "--silent", "start"]
    log_file = app / "server.log"
    with log_file.open("w") as output:
        # A new session, so that the stop also ends the child processes of pnpm.
        process = subprocess.Popen(
            command,
            cwd=app,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        yield
    except BaseException:
        print(log_file.read_text()[-4000:], file=sys.stderr)
        raise
    finally:
        os.killpg(process.pid, 15)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)


def provider_env(definition: AppDefinition) -> dict[str, str]:
    """Return the settings of an app that make each provider the mock provider."""
    assert definition.auth is not None
    env: dict[str, str] = {}
    for name, provider in definition.auth.providers.items():
        env[f"{name.upper()}_ISSUER"] = mock_oidc.issuer_of(OIDC_PORT, provider.authorize_params)
        env[provider.client_id_env] = mock_oidc.DEFAULT_CLIENT_ID
        env[provider.client_secret_env] = mock_oidc.DEFAULT_CLIENT_SECRET
    return env


def check_ui(
    binding: str,
    definition: AppDefinition,
    app: Path,
    rules: bool = False,
    providers_only: bool = False,
) -> None:
    """Run the UI test of the sign-in and the permissions on the app that runs.

    With `rules`, run only the tests of the record rules: the app is of
    RULES_DEFINITION. With `providers_only`, run only the test of the
    sign-in with a provider: the app is of COGNITO_DEFINITION.
    """
    if rules:
        name = f"{binding}-record-rules"
    else:
        name = f"{binding}-cognito" if providers_only else f"{binding}-auth"
    providers_only = providers_only or binding == "react-api"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    if rules:
        auth = {
            "app": definition.app.name,
            "password": PASSWORDS[binding],
            "roles": [],
            "recordRules": expected_record_rules(binding, definition),
            "providers": [],
        }
        expected = {**expected_ui(binding, definition), "auth": auth}
    elif providers_only:
        # Only the test of the sign-in with a provider: the FastAPI app has no seed users.
        auth = {
            "app": definition.app.name,
            "password": "",
            "roles": [],
            "providers": expected_providers(binding, definition),
        }
        ui_binding = "react" if binding == "react-api" else binding
        expected = {**expected_ui(ui_binding, definition), "auth": auth}
    else:
        expected = {
            **expected_ui(binding, definition),
            "auth": expected_auth(binding, definition, app),
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
    command = ["pnpm", "exec", "playwright", "test", "tests/auth.spec.ts"]
    if rules:
        command += ["--grep", RULES_TEST]
    elif providers_only:
        command += ["--grep", PROVIDER_TEST]
    if os.environ.get("APPGEN_UPDATE_SCREENSHOTS") == "1":
        command.append("--update-snapshots")
    run(*command, cwd=UI_TESTS, env=env)


def generate(definition: Path, binding: str, app: Path) -> None:
    log(binding, f"generate {definition} in {app}")
    run(
        "uv",
        "run",
        "--locked",
        "appgen",
        "generate",
        str(definition),
        "-b",
        binding,
        "-o",
        str(app),
        quiet=True,
    )


@contextmanager
def started_api(
    app: Path, settings: dict[str, str] | None = None, definition: Path = DEFINITION
) -> Generator[None]:
    """Start the FastAPI app of a definition with SQLite and the mock provider, and stop it at
    the end.

    `settings` are more environment variables of the app, for example the seed.
    """
    port, web = str(API_PORT), f"http://localhost:{PORTS['react-api']}"
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env |= {
        "DATABASE_URL": f"sqlite+aiosqlite:///{app / 'local.db'}",
        "AUTH_SECRET": "auth-ui-test-secret",
        "CORS_ORIGINS": json.dumps([web]),
        "PUBLIC_URL": f"http://127.0.0.1:{port}",
        "LOG_JSON": "false",
        **provider_env(load_definition(definition)),
        **(settings or {}),
    }
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=app, env=env, check=True)
    log_file = app / "server.log"
    with log_file.open("w") as output:
        process = subprocess.Popen(
            ["uv", "run", "fastapi", "run", "app/main.py", "--port", port],
            cwd=app,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        wait_for("react-api", f"http://127.0.0.1:{port}/health")
        yield
    except BaseException:
        print(log_file.read_text()[-4000:], file=sys.stderr)
        raise
    finally:
        os.killpg(process.pid, 15)
        process.wait(timeout=30)


def react_api_test(out: Path, path: Path = DEFINITION) -> None:
    """Sign in to the React app with the FastAPI app through the mock provider (ADR 0020).

    With COGNITO_DEFINITION, the provider is the mock user pool.
    """
    binding, definition = "react-api", load_definition(path)
    suffix = "-cognito" if path == COGNITO_DEFINITION else ""
    source = out / f"app{suffix}.yaml"
    marker = "\napp:\n"
    text = path.read_text()
    if marker not in text:
        raise AuthUiTestError(f"{path} has no 'app:' line.")
    source.write_text(text.replace(marker, f"{marker}  {DATA_KEY}: api\n", 1))
    api, web = out / f"react-api{suffix}-fastapi", out / f"{binding}{suffix}"
    generate(source, "fastapi", api)
    generate(source, "react", web)
    log(binding, "uv sync, pnpm install, and pnpm build")
    # The FastAPI app has its own virtual environment.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    subprocess.run(["uv", "sync", "--quiet"], cwd=api, env=env, check=True)
    run("pnpm", "install", "--silent", cwd=web)
    run("pnpm", "--silent", "build", cwd=web, env={"VITE_API_URL": f"http://127.0.0.1:{API_PORT}"})
    with (
        mock_oidc.serving(port=OIDC_PORT),
        started_api(api, definition=path),
        started(binding, web, path),
    ):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, f"UI test of the sign-in with a provider of {path} (Playwright)")
        check_ui(binding, definition, web, providers_only=bool(suffix))
    log(binding, f"{path}: passed")


def cognito_test(binding: str, out: Path) -> None:
    """Sign in to the app of COGNITO_DEFINITION through the mock user pool (ADR 0020)."""
    if binding == "react-api":
        react_api_test(out, COGNITO_DEFINITION)
        return
    definition = load_definition(COGNITO_DEFINITION)
    app = out / f"{binding}-cognito"
    generate(COGNITO_DEFINITION, binding, app)
    log(binding, "cognito: pnpm install and pnpm build")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "build", cwd=app)
    with mock_oidc.serving(port=OIDC_PORT), started(binding, app, COGNITO_DEFINITION):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the sign-in through the mock user pool (Playwright)")
        check_ui(binding, definition, app, providers_only=True)


def auth_ui_test(binding: str, out: Path) -> None:
    if binding == "react-api":
        react_api_test(out)
        cognito_test(binding, out)
        return
    definition = load_definition(DEFINITION)
    app = out / binding
    generate(DEFINITION, binding, app)
    log(binding, "pnpm install and pnpm build")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "build", cwd=app)
    mailbox = app / MAILBOX
    with (
        mock_oidc.serving(port=OIDC_PORT),
        mock_smtp.serving(port=SMTP_PORT, out=mailbox),
        started(binding, app),
    ):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the sign-in and the permissions (Playwright)")
        check_ui(binding, definition, app)
    record_rules_test(binding, out)
    if binding == "nextjs":
        cognito_test(binding, out)
    log(binding, "passed")


def record_rules_test(binding: str, out: Path) -> None:
    """Sign in to the app of RULES_DEFINITION as a user of each record rule (ADR 0025).

    The rules have conditions and owner paths: a member sees the projects
    and the open tasks of the teams of the member, and a reviewer sees the
    done tasks and the projects that are not archived.
    """
    definition = load_definition(RULES_DEFINITION)
    app = out / f"{binding}-record-rules"
    generate(RULES_DEFINITION, binding, app)
    log(binding, "record rules: pnpm install and pnpm build")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "build", cwd=app)
    with started(binding, app):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the record rules (Playwright)")
        check_ui(binding, definition, app, rules=True)


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
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-auth-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    try:
        for binding in bindings:
            auth_ui_test(binding, out)
    except (AuthUiTestError, subprocess.CalledProcessError) as error:
        print(f"auth-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
