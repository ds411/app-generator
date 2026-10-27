"""Select the sections of the app checks that a push must run.

The app checks (`scripts/check-<check>.sh`) generate, build, test, and
start the generated apps. Each check has sections: a section generates
one fixture with one binding or a few, and checks the output. The
pre-push hook runs a section only if it can give another result than on
the base commit, where all checks passed before the merge:

- A generated app of the section is not the same as in the base commit.
  The script generates each app of the section in memory, in the
  working tree and in the base commit, and compares the hashes of the
  files. It skips the generation if the generator (`src/appgen/`), the
  examples, and the fixtures are the same in both.
- A file that the section runs is not the same: the part of its check
  script without the other sections and the comments, its test scripts
  and the scripts that they import, and for a UI test, `ui-tests/` with
  the approved screenshots of its binding.
- A file of all sections is not the same: `uv.lock`, `pyproject.toml`,
  `.python-version`, `scripts/sandbox.env`, and `scripts/sandbox-setup.sh`.

The hook also skips a section that passed on this machine with the same
files and the same generated apps (the file `passed` in APPGEN_CHECK_CACHE).

Run it from the repository root:

    uv run scripts/check_plan.py select [--base <commit>]... [--all] [--state <file>]
    uv run scripts/check_plan.py record --state <file> [--sections <file>] <check>...

`select` prints the sections to run, one in each line, for example
`nextjs:listings`, and tells why on stderr. Without `--base`, it compares
with `origin/main`. `--all` selects all sections, also the passed ones.
`--state` writes the hashes of the selected sections to a file. `record`
adds the sections of the checks that passed, and the sections in the
file of `--sections`, from that file to the passed sections. A check
script runs only the sections in APPGEN_CHECK_SECTIONS (see the function
`section` in each script). Without the variable, it runs all sections.

When you add a section to a check script, add it to SECTIONS.

Environment variables:
    APPGEN_CHECK_CACHE    The folder of the passed sections (default ~/.cache/appgen/checks).
"""

import argparse
import concurrent.futures
import dataclasses
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSED_LINES = 5000
"""The number of passed sections that the cache keeps."""


@dataclass(frozen=True)
class App:
    """One generated app of a section: a definition with a binding."""

    definition: str
    binding: str
    extensions: str | None = None
    """The folder of the hand-written code that the check copies into the app first."""
    keys: tuple[tuple[str, str], ...] = ()
    """The keys that the test adds to the `app` section of the definition."""
    variant: str | None = None
    """A test script that writes another definition (VARIANTS)."""


@dataclass(frozen=True)
class Section:
    """One part of a check script."""

    name: str
    """`<check>:<part>`, for example `nextjs:listings`. The check is scripts/check-<check>.sh."""
    apps: tuple[App, ...]
    scripts: tuple[str, ...] = ()
    """The test scripts in scripts/ that the section runs."""
    ui: tuple[str, ...] = ()
    """The files and the folders in ui-tests/ that the section runs: the UI tests (specs) and the
    approved screenshots."""

    @property
    def check(self) -> str:
        return self.name.split(":", 1)[0]


TRACKER = "examples/project-tracker/app.yaml"
ROOMS = "examples/room-booking/app.yaml"
FIXTURES = "tests/fixtures"
GENERATION = ("src/appgen", "examples", "tests/fixtures")
"""The files that the generation of an app reads: the generator, the definitions, their
documents, and the hand-written code."""
COMMON = ("uv.lock", "pyproject.toml", ".python-version", "scripts/sandbox.env")
COMMON_SCRIPTS = ("sandbox-setup.sh",)
UI_FILES = (
    "ui-tests/package.json",
    "ui-tests/pnpm-lock.yaml",
    "ui-tests/playwright.config.ts",
    "ui-tests/tsconfig.json",
)
"""The files of the Playwright package, for the sections with a script that uses it."""
API = {"x-react-data": "api"}
"""The key of the React app with the API client of the FastAPI app."""
SKIPPED = {"node_modules", "__pycache__", ".venv", "test-results", ".DS_Store"}
VARIANTS = {"translation": "translation_test.py", "api-client": "api_client_test.py"}
"""The test scripts that write another definition of their apps."""


def tracker(binding: str, **keys: str) -> App:
    return App(
        TRACKER, binding, f"examples/project-tracker/extensions/{binding}", tuple(keys.items())
    )


def fixture(name: str, binding: str, extensions: bool = False, **keys: str) -> App:
    """An app of a fixture. With `extensions`, the check copies tests/fixtures/<name>/extensions/
    <binding> into it."""
    folder = f"{FIXTURES}/{name}/extensions/{binding}" if extensions else None
    return App(f"{FIXTURES}/{name}.yaml", binding, folder, tuple(keys.items()))


def pages(binding: str) -> tuple[str, ...]:
    """The UI files of `scripts/smoke_test.py --ui`: all UI tests, and the screenshots of the
    pages in the light and the dark mode."""
    return ("tests", f"approved/{binding}/light", f"approved/{binding}/dark")


def deploy(binding: str) -> tuple[App, ...]:
    """The apps of scripts/check_deploy_files.py."""
    targets = {f"x-{binding}-deploy": "[kubernetes, knative]"}
    store = {f"x-{binding}-rate-limit-store": "redis"}
    return (
        App(TRACKER, binding, keys=tuple(targets.items())),
        App(ROOMS, binding, keys=tuple({**targets, **store}.items())),
        fixture("files", binding, **targets),
    )


def fastapi_sections() -> Iterator[Section]:
    """The sections of scripts/check-fastapi.sh."""
    yield Section(
        "fastapi:project-tracker",
        (
            tracker("fastapi"),
            tracker("fastapi", **{"x-fastapi-rate-limit-store": "redis"}),
            *deploy("fastapi"),
            # scripts/check_live_events.py runs two brokers of this app with one Redis.
            fixture("record-rules", "fastapi"),
        ),
        (
            "api_calls.py",
            "smoke_test.py",
            "check_schema_change.py",
            "check_full_text_search.py",
            "check_shared_rate_limit.py",
            "check_live_events.py",
            "check_deploy_files.py",
        ),
    )
    yield Section("fastapi:room-booking", (App(ROOMS, "fastapi"),), ("check_provider_sign_in.py",))
    yield Section(
        "fastapi:provider-sign-in",
        (fixture("provider-sign-in", "fastapi"),),
        ("check_provider_sign_in.py",),
    )
    yield Section(
        "fastapi:cognito-sign-in",
        (fixture("cognito-sign-in", "fastapi"),),
        ("check_provider_sign_in.py",),
    )
    for name in ("account-security", "seed-data", "record-rules", "webhooks", "jobs", "files"):
        yield Section(f"fastapi:{name}", (fixture(name, "fastapi"),))
    yield Section(
        "fastapi:inbound-email",
        (fixture("inbound-email", "fastapi", extensions=True),),
        ("inbound_email_test.py",),
    )
    yield Section(
        "fastapi:api-connections",
        (fixture("api-connections", "fastapi", extensions=True),),
        ("api_connection_test.py",),
    )
    yield Section("fastapi:jira", (fixture("jira", "fastapi"),), ("api_calls.py",))
    for name in ("totals", "invoices"):
        yield Section(f"fastapi:{name}", (fixture(name, "fastapi"),))
    yield Section("fastapi:listings", (fixture("listings", "fastapi", extensions=True),))
    for name in ("courses", "places"):
        yield Section(f"fastapi:{name}", (fixture(name, "fastapi"),))


def nextjs_sections() -> Iterator[Section]:
    """The sections of scripts/check-nextjs.sh."""
    yield Section(
        "nextjs:project-tracker",
        (
            tracker("nextjs"),
            tracker("nextjs", **{"x-nextjs-rate-limit-store": "redis"}),
            *deploy("nextjs"),
        ),
        ("api_calls.py", "smoke_test.py", "check_shared_rate_limit.py", "check_deploy_files.py"),
        ui=pages("nextjs"),
    )
    yield Section("nextjs:seed-data", (fixture("seed-data", "nextjs"),), ("seed_test.py",))
    yield Section("nextjs:webhooks", (fixture("webhooks", "nextjs"),), ("webhook_test.py",))
    yield Section(
        "nextjs:inbound-email",
        (fixture("inbound-email", "nextjs", extensions=True),),
        ("inbound_email_test.py",),
    )
    yield Section(
        "nextjs:jobs",
        (App(f"{FIXTURES}/jobs.yaml", "nextjs", f"{FIXTURES}/jobs-extensions/nextjs"),),
        ("jobs_test.py",),
    )
    yield Section("nextjs:files", (fixture("files", "nextjs"),), ("files_test.py",))
    yield Section(
        "nextjs:events",
        (App(f"{FIXTURES}/events.yaml", "nextjs", f"{FIXTURES}/events-extensions/nextjs"),),
        ("events_test.py",),
    )
    yield Section("nextjs:record-rules", (fixture("record-rules", "nextjs"),), ("live_test.py",))
    yield Section(
        "nextjs:invoices",
        (fixture("invoices", "nextjs"),),
        ("sequence_test.py", "page_meta_test.py", "order_ui_test.py"),
        ui=("tests/order.spec.ts",),
    )
    yield Section("nextjs:totals", (fixture("totals", "nextjs"),), ("totals_test.py",))
    yield Section(
        "nextjs:listings", (fixture("listings", "nextjs", extensions=True),), ("queries_test.py",)
    )
    yield Section("nextjs:jira", (fixture("jira", "nextjs"),), ("api_calls.py",))


def react_sections() -> Iterator[Section]:
    """The sections of scripts/check-react.sh."""
    yield Section(
        "react:project-tracker",
        (tracker("react"),),
        ("api_calls.py", "smoke_test.py"),
        ui=pages("react"),
    )
    yield Section("react:seed-data", (fixture("seed-data", "react"),))
    yield Section(
        "react:invoices",
        (fixture("invoices", "react"),),
        ("sequence_test.py", "order_ui_test.py"),
        ui=("tests/order.spec.ts",),
    )
    yield Section("react:totals", (fixture("totals", "react"),))
    yield Section("react:listings", (fixture("listings", "react", extensions=True),))


def react_api_sections() -> Iterator[Section]:
    """The sections of scripts/check-react-api.sh: the React app with the FastAPI app."""
    yield Section(
        "react-api:project-tracker",
        tuple(
            App(TRACKER, b, f"examples/project-tracker/extensions/{b}", variant="api-client")
            for b in ("react", "fastapi")
        ),
        ("api_client_test.py",),
        ui=("tests/live.spec.ts",),
    )
    yield Section(
        "react-api:invoices",
        (fixture("invoices", "react", **API), fixture("invoices", "fastapi", **API)),
        ("order_ui_test.py",),
        ui=("tests/order.spec.ts",),
    )


def translation_sections() -> Iterator[Section]:
    """The sections of scripts/check-translations.sh: one for each front end."""
    for binding in ("react", "nextjs"):
        yield Section(
            f"translations:{binding}",
            (App(TRACKER, binding, variant="translation"),),
            ("translation_test.py", "untranslated_text.mjs"),
            ui=("tests/test-language.spec.ts", f"approved/{binding}/rtl"),
        )


AUTH_UI_TESTS = {
    "room-booking": "auth_ui_test.py",
    "connections": "connection_ui_test.py",
    "listings": "listings_ui_test.py",
    "courses": "sessions_ui_test.py",
    "places": "places_ui_test.py",
}
"""The parts of scripts/check-auth-ui.sh, with their test scripts."""
AUTH_UI_SPECS = {
    "room-booking": "auth",
    "connections": "connections",
    "listings": "listings",
    "courses": "sessions",
    "places": "places",
}
"""The UI test (ui-tests/tests/<name>.spec.ts) of each part."""
AUTH_UI_BINDINGS = ("react", "nextjs", "react-api")
AUTH_UI_FIXTURES = {
    "connections": ("api-connections", ("fastapi", "nextjs")),
    "listings": ("listings", ("fastapi", "nextjs", "react")),
    "courses": ("courses", ()),
    "places": ("places", ()),
}
"""The fixture of each part after the room booking, with the bindings of its hand-written code."""


def auth_ui_apps(part: str, binding: str) -> tuple[App, ...]:
    if part == "room-booking":
        # Next.js and react-api also sign in through the mock user pool of Cognito.
        cognito = f"{FIXTURES}/cognito-sign-in.yaml"
        if binding == "react-api":
            keys = tuple(API.items())
            bindings = ("react", "fastapi")
            return tuple(App(d, b, keys=keys) for d in (ROOMS, cognito) for b in bindings)
        if binding == "nextjs":
            return (App(ROOMS, binding), fixture("record-rules", binding), App(cognito, binding))
        return (App(ROOMS, binding), fixture("record-rules", binding))
    name, extended = AUTH_UI_FIXTURES[part]
    if binding == "react-api":
        return tuple(
            fixture(name, b, extensions=b in extended, **API) for b in ("react", "fastapi")
        )
    return (fixture(name, binding, extensions=binding in extended),)


def auth_ui_sections() -> Iterator[Section]:
    """The sections of scripts/check-auth-ui.sh: one for each part and each binding."""
    for part, script in AUTH_UI_TESTS.items():
        for binding in AUTH_UI_BINDINGS:
            ui = (f"tests/{AUTH_UI_SPECS[part]}.spec.ts",)
            if part == "room-booking":
                ui += (f"approved/{'react' if binding == 'react-api' else binding}/room-booking",)
            yield Section(f"auth-ui:{part}:{binding}", auth_ui_apps(part, binding), (script,), ui)


SECTIONS: tuple[Section, ...] = (
    *fastapi_sections(),
    *nextjs_sections(),
    *react_sections(),
    *react_api_sections(),
    *translation_sections(),
    *auth_ui_sections(),
)


class Digest:
    """A SHA-256 hash of named parts."""

    def __init__(self) -> None:
        self._hash = hashlib.sha256()

    def add(self, name: str, content: bytes | str) -> None:
        data = content.encode() if isinstance(content, str) else content
        for part in (name.encode(), len(data).to_bytes(8), data):
            self._hash.update(part)

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def tree_files(root: Path, path: str) -> list[Path]:
    """Return the files of a file or a folder, sorted, without the folders of tools."""
    start = root / path
    if start.is_file():
        return [start]
    found: list[Path] = []
    for folder, names, files in os.walk(start):
        names[:] = sorted(n for n in names if n not in SKIPPED)
        found.extend(Path(folder) / n for n in sorted(files) if n not in SKIPPED)
    return found


@functools.cache
def path_hash(root: Path, path: str) -> str:
    """Return the hash of a file, or of the files of a folder."""
    digest = Digest()
    for file in tree_files(root, path):
        digest.add(file.relative_to(root).as_posix(), file.read_bytes())
    return digest.hexdigest()


def add_files(digest: Digest, root: Path, paths: Iterable[str]) -> None:
    for path in paths:
        digest.add(path, path_hash(root, path))


_IMPORT = re.compile(r"^\s*(?:from|import)\s+(\w+)", re.MULTILINE)


@functools.cache
def script_closure(root: Path, names: tuple[str, ...]) -> tuple[str, ...]:
    """Return the paths of the scripts, of the scripts that they import, and of the .ts and .mjs
    files with the same names, sorted."""
    found: set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        path = root / "scripts" / name
        if name in found or not path.is_file():
            continue
        found.add(name)
        if name.endswith(".py"):
            todo.extend(f"{module}.py" for module in _IMPORT.findall(path.read_text()))
            todo.extend(f"{path.stem}{suffix}" for suffix in (".ts", ".mjs"))
    return tuple(sorted(f"scripts/{name}" for name in found))


_SECTION = re.compile(r"^if section ([\w:.-]+); then\n.*?^fi\n", re.MULTILINE | re.DOTALL)


def script_part(text: str, name: str) -> str:
    """Return the lines of a check script that a section runs: the lines outside all sections,
    and the lines of the section, without the comment lines."""
    kept = _SECTION.sub(lambda m: m.group(0) if m.group(1) == name else "", text)
    return "".join(line for line in kept.splitlines(True) if not line.lstrip().startswith("#"))


@functools.cache
def files_hash(root: Path, section: Section) -> str:
    """Return the hash of the files that a section runs, without its generated apps."""
    digest = Digest()
    script = root / "scripts" / f"check-{section.check}.sh"
    text = script.read_text() if script.is_file() else ""
    digest.add(script.name, script_part(text, section.name))
    add_files(digest, root, COMMON)
    scripts = script_closure(root, (*section.scripts, *COMMON_SCRIPTS))
    add_files(digest, root, scripts)
    if section.ui:
        add_files(digest, root, UI_FILES)
        # The modules that the UI tests import.
        helpers = (p for p in (root / "ui-tests" / "tests").glob("*.ts") if ".spec." not in p.name)
        add_files(digest, root, sorted(p.relative_to(root).as_posix() for p in helpers))
        add_files(digest, root, (f"ui-tests/{path}" for path in section.ui))
    elif any("ui-tests" in (root / path).read_text() for path in scripts):
        # A script that starts Chromium with the Playwright package of ui-tests/.
        add_files(digest, root, UI_FILES)
    return digest.hexdigest()


@functools.cache
def generation_hash(root: Path, app: App) -> str:
    """Return the hash of the files that the generation of an app can read."""
    digest = Digest()
    add_files(digest, root, GENERATION)
    if app.variant:
        add_files(digest, root, script_closure(root, (VARIANTS[app.variant],)))
    return digest.hexdigest()


def variant_definition(app: App, folder: Path) -> Path:
    """Write the definition of the test script of a variant, from the scripts of sys.path."""
    if app.variant == "translation":
        import translation_test

        from appgen.dsl import load_definition

        definition = load_definition(Path(app.definition))
        return translation_test.test_definition(definition, app.binding, folder)
    if app.variant == "api-client":
        import api_client_test

        return api_client_test.api_definition(folder)
    raise ValueError(f"Unknown variant: {app.variant}")


def app_hash(app: App) -> str | None:
    """Generate an app in memory with the appgen of sys.path, and return the hash of its files.

    The folder of the tree is the working folder. Return None if the generation fails, for
    example in a commit without the definition.
    """
    from appgen.dsl import load_definition_text
    from appgen.gen import find_binding, generate

    try:
        with tempfile.TemporaryDirectory() as temp:
            path = variant_definition(app, Path(temp)) if app.variant else Path(app.definition)
            text = path.read_text()
            if app.keys:
                lines = "".join(f"  {key}: {value}\n" for key, value in app.keys)
                text, count = re.subn(r"(?m)^app:\n", f"app:\n{lines}", text, count=1)
                if count != 1:
                    return None
            result = generate(load_definition_text(text, str(path)), find_binding(app.binding))
    except Exception:
        return None
    digest = Digest()
    for file in sorted(result.files, key=lambda f: f.path):
        digest.add(f"{file.kind}:{file.path}", file.content)
    for path, value in sorted(result.documents.items()):
        digest.add(f"document:{path}", value)
    if app.extensions:
        add_files(digest, Path.cwd(), (app.extensions,))
    return digest.hexdigest()


def app_hashes(root: Path, apps: Iterable[App]) -> dict[App, str | None]:
    """Generate apps with the appgen and the scripts of a tree, in a process of its own."""
    apps = list(dict.fromkeys(apps))
    if not apps:
        return {}
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root / "scripts")])}
    # -P: do not put the folder of this file first in sys.path, so that the scripts of the tree
    # come first.
    result = subprocess.run(
        [sys.executable, "-P", __file__, "hashes"],
        input=json.dumps([dataclasses.asdict(app) for app in apps]),
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
        check=True,
    )
    hashes: list[str | None] = json.loads(result.stdout)
    return dict(zip(apps, hashes, strict=True))


def hashes_command() -> int:
    """Read apps as JSON from stdin, and print the hashes of their files as JSON."""
    apps = [
        App(**{**item, "keys": tuple(tuple(pair) for pair in item["keys"])})
        for item in json.loads(sys.stdin.read())
    ]
    with concurrent.futures.ProcessPoolExecutor(min(len(apps), os.cpu_count() or 1)) as pool:
        hashes = list(pool.map(app_hash, apps))
    print(json.dumps(hashes))
    return 0


def changed_sections(head: Path, base: Path, hashes: dict[App, str | None]) -> dict[str, str]:
    """Return the sections that differ between two trees, with the reason of each.

    `hashes` keeps the hashes of the apps of the head tree.
    """
    reasons: dict[str, str] = {}
    pending: list[Section] = []
    for section in SECTIONS:
        if files_hash(head, section) != files_hash(base, section):
            reasons[section.name] = "a file that it runs changed"
        elif any(generation_hash(head, a) != generation_hash(base, a) for a in section.apps):
            pending.append(section)
    apps = [app for section in pending for app in section.apps]
    hashes.update(app_hashes(head, (app for app in apps if app not in hashes)))
    base_hashes = app_hashes(base, apps)
    for section in pending:
        for app in section.apps:
            if hashes[app] is None or hashes[app] != base_hashes[app]:
                reasons[section.name] = f"its app of {app.definition} with {app.binding} changed"
                break
    return reasons


def section_hash(head: Path, section: Section, hashes: dict[App, str | None]) -> str:
    """Return the hash of the files and the generated apps of a section."""
    digest = Digest()
    digest.add("files", files_hash(head, section))
    for app in section.apps:
        digest.add("app", hashes[app] or "none")
    return digest.hexdigest()


def log(message: str) -> None:
    print(f"check-plan: {message}", file=sys.stderr, flush=True)


def passed_file() -> Path:
    folder = os.environ.get("APPGEN_CHECK_CACHE") or Path.home() / ".cache" / "appgen" / "checks"
    return Path(folder) / "passed"


def passed_sections() -> set[str]:
    """Return the passed sections, as lines "<section> <hash>"."""
    path = passed_file()
    return set(path.read_text().splitlines()) if path.is_file() else set()


def base_tree(commit: str, folder: Path) -> Path:
    """Write the files of a commit into a folder."""
    archive = subprocess.run(["git", "archive", commit], capture_output=True, check=True, cwd=ROOT)
    subprocess.run(["tar", "-x", "-C", str(folder)], input=archive.stdout, check=True)
    return folder


def select_command(bases: list[str], everything: bool, state: Path | None) -> int:
    hashes: dict[App, str | None] = {}
    reasons: dict[str, str] = {}
    if everything:
        reasons = {s.name: "all sections" for s in SECTIONS}
    else:
        for commit in dict.fromkeys(bases):
            with tempfile.TemporaryDirectory() as temp:
                found = changed_sections(ROOT, base_tree(commit, Path(temp)), hashes)
            for name, reason in found.items():
                reasons.setdefault(name, reason)
    selected = [s for s in SECTIONS if s.name in reasons]
    hashes.update(app_hashes(ROOT, (a for s in selected for a in s.apps if a not in hashes)))
    lines = {s.name: f"{s.name} {section_hash(ROOT, s, hashes)}" for s in selected}
    passed = set() if everything else passed_sections()
    run = [s for s in selected if lines[s.name] not in passed]
    for section in selected:
        if section in run:
            log(f"run {section.name}: {reasons[section.name]}")
        else:
            log(f"skip {section.name}: it passed before with the same files")
    log(f"skip {len(SECTIONS) - len(selected)} sections that are the same as in the base commit")
    if state:
        state.write_text("".join(f"{lines[s.name]}\n" for s in run))
    for section in run:
        print(section.name)
    return 0


def record_command(state: Path, checks: list[str], sections: Path | None = None) -> int:
    passed = set(sections.read_text().split()) if sections and sections.is_file() else set()
    lines = [
        line
        for line in state.read_text().splitlines()
        if line.split(":", 1)[0] in checks or line.split(" ", 1)[0] in passed
    ]
    if lines:
        path = passed_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text().splitlines() if path.is_file() else []
        path.write_text("".join(f"{line}\n" for line in [*old, *lines][-PASSED_LINES:]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select", help="print the sections to run")
    select.add_argument("--base", action="append", default=[], help="a base commit")
    select.add_argument("--all", action="store_true", help="select all sections")
    select.add_argument("--state", type=Path, help="write the hashes of the sections to this file")
    record = commands.add_parser("record", help="record the sections of the passed checks")
    record.add_argument("--state", type=Path, required=True)
    record.add_argument("--sections", type=Path, help="a file with more passed sections")
    record.add_argument("checks", nargs="*")
    commands.add_parser("hashes", help="print the hashes of the apps of stdin (internal)")
    args = parser.parse_args()
    if args.command == "hashes":
        return hashes_command()
    if args.command == "record":
        return record_command(args.state, args.checks, args.sections)
    return select_command(args.base or ["origin/main"], args.all, args.state)


if __name__ == "__main__":
    sys.exit(main())
