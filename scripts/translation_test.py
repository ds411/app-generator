"""Show the pages of a front end in a test language, and find the text of the default language.

ADR 0010: with a `translations` section, each text that a front end
shows goes through `t`, the fixed text of the components included. This
test proves it for the project tracker:

1. Collect the texts that the app translates (`app_texts`), and write
   the project tracker with a test language instead of its languages.
   The test language changes each text to `⟦text⟧`, and has the
   locale `ja`, so its dates and numbers have no Latin letters.
2. Generate the app, and find the UI text in the code that does not
   call `t` (`scripts/untranslated_text.mjs`).
3. Build and start the app: React with `vite preview`, Next.js with
   `pnpm start` and PGlite.
4. Run the UI test `ui-tests/tests/test-language.spec.ts`: it opens each
   page in the test language, with its search, the menu of a record, and
   a form with its date picker. Each text with a Latin letter must have
   ⟦, or be a value of the records.
5. Next.js: request the pages in the test language and in the default
   language at the same time. The server must render each page in the
   language of its request.

Run it from the repository root:

    uv run scripts/translation_test.py [binding ...] [--out folder]

Without a binding, the script tests React and Next.js. It needs pnpm
and the Chromium of Playwright (see scripts/smoke_test.py). It uses the
ports 5430 (React) and 3430 (Next.js). It does not need Docker.

Environment variables:
    PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the test, instead of the one
                                  that Playwright installs. Without both, the test
                                  uses /opt/pw-browsers/chromium if it exists.
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for an app to start (default 180).
"""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from smoke_test import expected_ui

from appgen.bindings import nextjs, react
from appgen.bindings.shared.i18n import app_texts
from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl import AppDefinition, load_definition
from appgen.gen.binding import Binding

DEFINITION = Path("examples/project-tracker/app.yaml")
UI_TESTS = Path("ui-tests")
BINDINGS: dict[str, Binding] = {"react": react.BINDING, "nextjs": nextjs.BINDING}
PORTS = {"react": 5430, "nextjs": 3430}
CODE = "xx"
"""The code of the test language."""
LABEL = "Test"
LOCALE = "ja"
"""The locale of the test language: its dates and numbers have no Latin letters."""


class TranslationTestError(Exception):
    """A failed check."""


def log(binding: str, message: str) -> None:
    print(f"translation-test: {binding}: {message}", flush=True)


def run(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, quiet: bool = False
) -> None:
    output = subprocess.DEVNULL if quiet else None
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})}, stdout=output)


def test_definition(definition: AppDefinition, binding: str, folder: Path) -> Path:
    """Write the project tracker with the default language and the test language."""
    text = DEFINITION.read_text()
    start = text.find("\ntranslations:")
    if start < 0 or definition.translations is None:
        raise TranslationTestError(f"{DEFINITION} has no translations.")
    if any(line[:1].isalpha() for line in text[start + 1 :].splitlines()[1:]):
        raise TranslationTestError(
            f"The section translations is not the last section of {DEFINITION}."
        )
    texts = app_texts(definition, BINDINGS[binding])
    default = definition.translations.default
    section = {
        "translations": {
            "default": default,
            "languages": {
                default: {"label": definition.translations.languages[default].label},
                CODE: {
                    "label": LABEL,
                    "locale": LOCALE,
                    "text": {text: f"⟦{text}⟧" for text in texts},
                },
            },
        }
    }
    # The other files of the definition, for example the OpenAPI documents of `apis`.
    for item in DEFINITION.parent.iterdir():
        if item.name == DEFINITION.name:
            continue
        if item.is_dir():
            shutil.copytree(item, folder / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, folder / item.name)
    path = folder / "app.yaml"
    dump = yaml.safe_dump(section, allow_unicode=True, sort_keys=False, width=1000)
    path.write_text(text[: start + 1] + dump)
    return path


def ignored_texts(definition: AppDefinition) -> list[str]:
    """Return the texts that are not UI text: the values of the records and the language names."""
    texts = {LABEL}
    if definition.translations is not None:
        texts |= {language.label for language in definition.translations.languages.values()}
    for records in mock_data(definition).values():
        for record in records:
            for value in record.values():
                values: list[Any] = value if isinstance(value, list) else [value]
                texts |= {item.strip() for item in values if isinstance(item, str)}
    return sorted(texts)


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
    raise TranslationTestError(f"{binding}: {url} did not answer in {timeout:.0f} s ({last}).")


@contextmanager
def started(binding: str, app: Path) -> Generator[None]:
    """Start the built app, and stop it at the end."""
    port = str(PORTS[binding])
    env = {**os.environ, "PORT": port}
    if binding == "react":
        command = ["pnpm", "exec", "vite", "preview", "--port", port, "--strictPort"]
    else:
        run("pnpm", "--silent", "db:generate", cwd=app)
        env |= {
            "DATABASE_URL": f"pglite:{app / '.pglite'}",
            "DATABASE_MIGRATE": "true",
            "DATABASE_SEED": "true",
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


def check_ui(binding: str, definition: AppDefinition) -> None:
    """Run the UI test of the test language on the app that runs."""
    name = f"{binding}-language"
    expected_file = (UI_TESTS / "expected" / f"{name}.json").resolve()
    expected_file.parent.mkdir(exist_ok=True)
    expected = {
        **expected_ui(binding, definition),
        "testLanguage": {
            "code": CODE,
            "locale": LOCALE,
            "storageKey": f"{definition.app.name}-language",
            "ignore": ignored_texts(definition),
        },
    }
    expected_file.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
    env = {
        "APPGEN_BASE_URL": f"http://localhost:{PORTS[binding]}",
        "APPGEN_UI_EXPECTED": str(expected_file),
        "APPGEN_UI_OUTPUT": str((UI_TESTS / "test-results" / name).resolve()),
    }
    with (UI_TESTS / ".install.lock").open("w") as lock:
        # Only one check at a time installs the packages of the UI tests.
        fcntl.flock(lock, fcntl.LOCK_EX)
        run("pnpm", "install", "--silent", "--frozen-lockfile", cwd=UI_TESTS)
    command = ["pnpm", "exec", "playwright", "test", "tests/test-language.spec.ts"]
    run(*command, "--project", "light", cwd=UI_TESTS, env=env)


def check_parallel_requests(definition: AppDefinition) -> None:
    """Request the pages of Next.js in two languages at the same time: each page has one language.

    The server renders each request in the language of its cookie (ADR
    0010). Half of the requests have the cookie of the test language.
    """
    pages: list[dict[str, Any]] = expected_ui("nextjs", definition)["pages"]
    paths = [page["path"] for page in pages if not page["params"]]
    cookie = f"{definition.app.name}-language={CODE}"
    translations = definition.translations
    default = translations.default if translations else ""
    default_locale = translations.languages[default].locale_tag(default) if translations else ""

    def fetch(index: int) -> str | None:
        path, test = paths[index % len(paths)], index % 2 == 0
        url = f"http://localhost:{PORTS['nextjs']}{path}"
        request = urllib.request.Request(url, headers={"Cookie": cookie} if test else {})
        with urllib.request.urlopen(request, timeout=120) as response:
            html = response.read().decode()
        lang = f'<html lang="{LOCALE if test else default_locale}"'
        if lang in html and ("⟦" in html) == test:
            return None
        return f"{path} ({CODE if test else default})"

    with ThreadPoolExecutor(max_workers=20) as pool:
        wrong = [item for item in pool.map(fetch, range(4 * 20)) if item]
    if wrong:
        raise TranslationTestError(f"Pages in the wrong language: {', '.join(wrong)}.")


def translation_test(binding: str, out: Path) -> None:
    definition = load_definition(DEFINITION)
    out.mkdir(parents=True, exist_ok=True)
    path = test_definition(definition, binding, out)
    app = out / binding
    log(binding, f"generate {path} in {app}")
    run(
        "uv",
        "run",
        "--locked",
        "appgen",
        "generate",
        str(path),
        "-b",
        binding,
        "-o",
        str(app),
        quiet=True,
    )
    log(binding, "find the UI text that does not call t")
    run("node", "scripts/untranslated_text.mjs", str(app))
    log(binding, "pnpm install and pnpm build")
    run("pnpm", "install", "--silent", cwd=app)
    run("pnpm", "--silent", "build", cwd=app)
    test = load_definition(path)
    with started(binding, app):
        wait_for(binding, f"http://localhost:{PORTS[binding]}/")
        log(binding, "UI test of the test language (Playwright)")
        check_ui(binding, test)
        if binding == "nextjs":
            log(binding, "80 requests in two languages at the same time")
            check_parallel_requests(test)
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
    folder = None if args.out else tempfile.TemporaryDirectory(prefix="appgen-translation.")
    out = args.out.resolve() if args.out else Path(folder.name)  # pyright: ignore[reportOptionalMemberAccess]
    try:
        for binding in bindings:
            translation_test(binding, out / binding)
    except (TranslationTestError, subprocess.CalledProcessError) as error:
        print(f"translation-test: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
