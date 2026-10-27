"""Fill a cart as a guest in the shop fixture, sign up or sign in, and find the cart.

The guests of M36 (ADR 0050): a visitor without a sign-in calls the guest
operations on its own records, and the records move to the user at the
sign-up and at the sign-in. This test proves it for
tests/fixtures/shop.yaml:

1. Generate the fixture with the binding, install it, run the lint, the
   type check, and `appgen check`, and build it.
2. Start the app: React with `vite preview` and its mock data, Next.js
   with `pnpm start`, PGlite, and the seed users (`DATABASE_SEED` and
   `SEED_PASSWORD`). The binding `react-api` is the React app with
   `x-react-data: api` and the FastAPI app of the fixture (SQLite, with
   the seed users).
3. Run the UI test `ui-tests/tests/guests.spec.ts`. A guest opens the
   cart, sees no items of the customers, and adds an item. Another guest
   does not see the item. The guest signs up, and the cart of the new
   customer has the item. A second guest adds an item, signs in as a
   customer of the seed records, and the cart has the item and the own
   items of the customer.

Run it from the repository root:

    uv run scripts/guests_ui_test.py [binding ...] [--out folder]

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
from typing import Any

from auth_ui_test import (
    API_PORT,
    PASSWORDS,
    PORTS,
    UI_TESTS,
    expected_sign_up,
    generate,
    run,
    started,
    started_api,
    wait_for,
)
from smoke_test import expected_ui

from appgen.bindings.react.api_client import DATA_KEY
from appgen.bindings.shared.mock_data import mock_data
from appgen.bindings.shared.views import definition_display, label
from appgen.dsl import AppDefinition, load_definition
from appgen.dsl.ui.common import FormAction
from appgen.gen.naming import kebab

DEFINITION = Path("tests/fixtures/shop.yaml")
BINDINGS = ("react", "nextjs", "react-api")
NUMBERS = ("3", "4")
"""The numbers of the items that the guests add."""


class GuestsUiTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"guests-ui-test: {binding}: {message}", flush=True)


def menu_label(definition: AppDefinition, page: str) -> str:
    """Return the label of the menu item of a page."""
    ui = definition.ui
    assert ui is not None
    for menu in ui.navigation.values():
        items = [*menu.items.values(), *(i for g in menu.groups.values() for i in g.items.values())]
        for item in items:
            if item.page == page:
                return str(item.label or definition.pages[page].title)
    raise GuestsUiTestError(f"The page {page!r} has no menu item.")


def expected_guests(binding: str, definition: AppDefinition, app: Path) -> dict[str, Any]:
    """Return the values of the UI test of the guests.

    The page is the list page of the first entity of the guests with a
    form action of a guest create operation. The form has a many-to-one
    relation and an integer field. The user is the owner of the first
    record of the entity in the seed data.
    """
    auth, ui = definition.auth, definition.ui
    assert auth is not None and auth.guests is not None and ui is not None
    entity_name, owner = next(iter(auth.guests.entities.items()))
    entity = definition.entities[entity_name]
    found = [
        (name, page, action_name, action)
        for name, page in definition.pages.items()
        if page.entity == entity_name
        for action_name, action in page.actions.items()
        if isinstance(action, FormAction)
        and ui.forms[action.form].operation in auth.guests.operations
        and definition.operations[ui.forms[action.form].operation].kind == "create"
    ]
    if not found:
        raise GuestsUiTestError(f"No list page of {entity_name} has a form of a guest create.")
    name, page, action_name, action = found[0]
    form = ui.forms[action.form]
    relations = entity.relations
    relation_name = next(
        f for f in form.fields if f in relations and relations[f].kind == "many_to_one"
    )
    number = next(
        f for f in form.fields if f in entity.fields and entity.fields[f].type == "integer"
    )
    relation = entity.relations[relation_name]
    target = definition_display(definition.entities[relation.target])
    data = mock_data(definition)
    titles = {str(r["id"]): str(r[target]) for r in data[relation.target]}
    records = data[entity_name]
    users = {str(u["id"]): u for u in data[auth.user_entity]}
    owned = [r for r in records if r.get(owner)]
    if not owned:
        raise GuestsUiTestError(f"The seed data has no record of {entity_name} with an owner.")
    user = users[str(owned[0][owner])]
    own = sorted({titles[str(r[relation_name])] for r in owned if r[owner] == user["id"]})
    others = sorted({titles[str(r[relation_name])] for r in owned})
    free = [title for title in titles.values() if title not in others]
    if len(free) < len(NUMBERS):
        raise GuestsUiTestError(f"The test needs {len(NUMBERS)} records of {relation.target}.")
    sign_up = expected_sign_up(binding, definition, app)
    if sign_up is None:
        raise GuestsUiTestError("The test needs the sign-up.")
    return {
        "path": page.path,
        "title": str(page.title),
        "menu": menu_label(definition, name),
        "add": str(action.label or label(action_name)),
        "submit": str(form.submit_label or "Create"),
        "relation": str(form.fields[relation_name].label or relation.label or label(relation_name)),
        "numberId": f"{kebab(action.form)}-{kebab(number)}",
        "items": [{"related": title, "number": n} for title, n in zip(free, NUMBERS, strict=False)],
        "others": others,
        "user": {
            "username": str(user[auth.username_field]),
            "password": PASSWORDS["nextjs" if binding == "react-api" else binding],
            "own": own,
        },
        "signUp": {"fields": sign_up["fields"], "password": sign_up["password"]},
    }


def check_ui(binding: str, definition: AppDefinition, app: Path) -> None:
    """Run the UI test of the guests on the app that runs."""
    name = f"{binding}-guests"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    ui_binding = "react" if binding == "react-api" else binding
    expected = {
        **expected_ui(ui_binding, definition),
        "guests": expected_guests(binding, definition, app),
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
    command = ["pnpm", "exec", "playwright", "test", "tests/guests.spec.ts", "--project", "light"]
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
    """Fill a cart in the React app with the FastAPI app of the fixture, with the seed users."""
    binding, definition = "react-api", load_definition(DEFINITION)
    source = out / "shop.yaml"
    marker = "\napp:\n"
    text = DEFINITION.read_text()
    if marker not in text:
        raise GuestsUiTestError(f"{DEFINITION} has no 'app:' line.")
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
        log(binding, "UI test of the guests (Playwright)")
        check_ui(binding, definition, web)
    log(binding, "passed")


def guests_ui_test(binding: str, out: Path) -> None:
    if binding == "react-api":
        react_api_test(out)
        return
    definition = load_definition(DEFINITION)
    app = out / binding
    generate(DEFINITION, binding, app)
    build(binding, DEFINITION, app)
    with started(binding, app):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/sign-in")
        log(binding, "UI test of the guests (Playwright)")
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
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-guests-ui.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    out.mkdir(parents=True, exist_ok=True)
    try:
        for binding in bindings:
            guests_ui_test(binding, out)
    except (GuestsUiTestError, subprocess.CalledProcessError) as error:
        print(f"guests-ui-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
