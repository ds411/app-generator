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
   new user (ADR 0016). In the Next.js app, it compares the password
   reset pages with approved screenshots, resets the password of a user
   with the link in the log of the app, and signs in with the new
   password (ADR 0017).

Run it from the repository root:

    uv run scripts/auth_ui_test.py [binding ...] [--out folder]

Without a binding, the script tests React and Next.js. It needs pnpm
and the Chromium of Playwright (see scripts/smoke_test.py). It uses the
ports 5440 (React) and 3440 (Next.js). It does not need Docker.

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
from typing import Any

from smoke_test import expected_ui

from appgen.bindings.shared.mock_data import mock_data
from appgen.bindings.shared.views import label
from appgen.dsl import AppDefinition, load_definition
from appgen.dsl.access import ALL
from appgen.dsl.ui.common import FormAction, NavigateAction, OperationAction
from appgen.gen.naming import kebab

DEFINITION = Path("examples/room-booking/app.yaml")
UI_TESTS = Path("ui-tests")
BINDINGS = ("react", "nextjs")
PORTS = {"react": 5440, "nextjs": 3440}
PASSWORDS = {"react": "password", "nextjs": "auth-ui-test-password"}
"""The password of the users: the mock password of React, and SEED_PASSWORD of Next.js."""


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


def expected_sign_up(definition: AppDefinition) -> dict[str, Any] | None:
    """Return the values of the sign-up: the required fields, and the menu of a new user."""
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
    return {
        "fields": fields,
        "usernameId": f"sign-up-{kebab(auth.username_field)}",
        "password": "a-new-password-for-the-test",
        "menu": menu_labels(definition, Permissions(definition, role)),
    }


def expected_password_reset(
    binding: str, definition: AppDefinition, app: Path, roles: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the values of the password reset: a user apart from the users of the roles.

    Only the Next.js app has the reset pages: the React app with mock data
    has no server that sends the links. With `ENVIRONMENT=development`, the
    Next.js app writes each link to its log, and the test reads it there.
    """
    auth = definition.auth
    assert auth is not None
    if auth.password_reset is None or binding != "nextjs":
        return None
    used = {role["username"] for role in roles}
    users = [
        u for u in mock_data(definition)[auth.user_entity] if u[auth.username_field] not in used
    ]
    return {"username": users[-1][auth.username_field], "serverLog": str(app / "server.log")}


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
        "signUp": expected_sign_up(definition),
        "passwordReset": expected_password_reset(binding, definition, app, roles),
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
def started(binding: str, app: Path) -> Generator[None]:
    """Start the built app, and stop it at the end."""
    port = str(PORTS[binding])
    env = {**os.environ, "PORT": port}
    if binding == "react":
        command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    else:
        run("pnpm", "--silent", "db:generate", cwd=app, quiet=True)
        env |= {
            "DATABASE_URL": f"pglite:{app / '.pglite'}",
            "DATABASE_MIGRATE": "true",
            "DATABASE_SEED": "true",
            "SEED_PASSWORD": PASSWORDS[binding],
            "AUTH_SECRET": "auth-ui-test-secret",
            # The password reset writes the links to the log (server.log).
            "ENVIRONMENT": "development",
            "PUBLIC_URL": f"http://localhost:{port}",
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


def check_ui(binding: str, definition: AppDefinition, app: Path) -> None:
    """Run the UI test of the sign-in and the permissions on the app that runs."""
    name = f"{binding}-auth"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
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
    if os.environ.get("APPGEN_UPDATE_SCREENSHOTS") == "1":
        command.append("--update-snapshots")
    run(*command, cwd=UI_TESTS, env=env)


def auth_ui_test(binding: str, out: Path) -> None:
    definition = load_definition(DEFINITION)
    app = out / binding
    log(binding, f"generate {DEFINITION} in {app}")
    run(
        "uv",
        "run",
        "--locked",
        "appgen",
        "generate",
        str(DEFINITION),
        "-b",
        binding,
        "-o",
        str(app),
        quiet=True,
    )
    log(binding, "pnpm install and pnpm build")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "build", cwd=app)
    with started(binding, app):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the sign-in and the permissions (Playwright)")
        check_ui(binding, definition, app)
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
