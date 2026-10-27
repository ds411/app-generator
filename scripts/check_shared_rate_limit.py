"""Run two processes of an app with one Redis, and check their shared rate limit.

With `x-fastapi-rate-limit-store: redis` (the FastAPI app) or
`x-nextjs-rate-limit-store: redis` (the Next.js app) in the `app`
section, the rate limit counts in Redis (`RATE_LIMIT_STORE_URL`), so all
replicas share one limit (ADR 0013). This check proves it:

1. Generate the project tracker with the key, and check the code of the
   app. FastAPI: ruff, pyright, and the tests on SQLite. Next.js: pnpm
   install and build (`scripts/check-nextjs.sh` lints and type checks
   the app without the key).
2. Start one process without Redis, with a limit of 10 requests in each
   minute: it counts in its memory, so 10 of 11 requests must pass.
3. Start Redis in Docker, and two processes of the app with the same
   limit. The FastAPI processes use one SQLite database, and each
   Next.js process has a PGlite database in memory.
4. Send 6 requests to each process: 10 of the 12 requests must pass,
   and 2 must get 429 with `Retry-After`. One more request in German
   must get the German message. `/health` must have no limit.
5. Stop Redis: a request must pass, and the log must have a warning. A
   process with `RATE_LIMIT_FAIL_CLOSED=true` must give 503.

Run it from the repository root:

    uv run scripts/check_shared_rate_limit.py {fastapi,nextjs} [output folder]

The script needs Docker, and uv (FastAPI) or pnpm (Next.js). It uses the
ports 8431 to 8434 and 6391 (Redis) for FastAPI, and 3451 to 3454 and
6392 for Next.js, so that the check scripts of both apps can run at the
same time.

Environment variables:
    REDIS_IMAGE                   The Redis image (default redis:8-alpine).
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for a process to start (default 180).
"""

import argparse
import contextlib
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from appgen.bindings.fastapi.model import RATE_LIMIT_STORE_KEY as FASTAPI_KEY
from appgen.bindings.nextjs.model import RATE_LIMIT_STORE_KEY as NEXTJS_KEY

DEFINITION = Path("examples/project-tracker/app.yaml")
LIMIT = 10
REQUESTS = 6
"""The requests to each of the two processes: more than the limit together."""
GERMAN = f"Senden Sie nicht mehr als {LIMIT} Anfragen pro Minute."
"""The message of a 429 in German (the `translations` of the project tracker)."""


@dataclass(frozen=True, slots=True)
class Target:
    """The settings of the check for one binding."""

    key: str
    """The extension key of the store of the rate limit."""
    ports: tuple[int, int]
    """The ports of the two processes that share Redis."""
    memory_port: int
    fail_closed_port: int
    redis_port: int
    path: str
    """A path with a limit: the list of the people."""


TARGETS = {
    "fastapi": Target(FASTAPI_KEY, (8431, 8432), 8434, 8433, 6391, "/people"),
    "nextjs": Target(NEXTJS_KEY, (3451, 3452), 3454, 3453, 6392, "/people"),
}


class CheckError(Exception):
    """A failed check."""


def log(message: str) -> None:
    print(f"shared-rate-limit: {message}", flush=True)


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], str]:
    """Return the status, the headers, and the body of a GET request."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def status(url: str) -> int:
    """Return the status of a GET request."""
    return get(url)[0]


def wait_for(url: str) -> None:
    """Wait until a URL answers with 200."""
    timeout = float(os.environ.get("APPGEN_SMOKE_TIMEOUT", "180"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if status(url) == 200:
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise CheckError(f"{url} did not answer in {timeout:.0f} s.")


def wait_for_redis(port: int) -> None:
    """Wait until Redis answers PING."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                connection.sendall(b"PING\r\n")
                if connection.recv(16).startswith(b"+PONG"):
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise CheckError("Redis did not start in 60 s.")


@contextmanager
def redis(name: str, port: int) -> Generator[None]:
    """Start Redis in Docker, and remove it at the end."""
    image = os.environ.get("REDIS_IMAGE", "redis:8-alpine")
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    run("docker", "run", "-d", "--name", name, "-p", f"{port}:6379", image)
    try:
        wait_for_redis(port)
        yield
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, env=env, stdout=subprocess.DEVNULL)


@contextmanager
def started(
    command: list[str], app: Path, port: int, env: dict[str, str], log_file: Path
) -> Generator[subprocess.Popen[bytes]]:
    """Start a process of the app, and stop it at the end, if it did not stop."""
    with log_file.open("w") as output:
        # A new session, so that the stop also ends the child processes of pnpm and uv.
        process = subprocess.Popen(
            [*command, "--port", str(port)],
            cwd=app,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            wait_for(f"http://127.0.0.1:{port}/health")
            yield process
        except BaseException:
            print(log_file.read_text()[-4000:], file=sys.stderr)
            raise
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)


def wait_for_a_new_window() -> None:
    """Wait for the next minute if this one ends soon, so that all requests are in one window."""
    second = time.time() % 60
    if second > 40:
        time.sleep(61 - second)


def prepare_fastapi(app: Path, env: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """Check the FastAPI app, and return its command and the settings of its database."""
    log("uv sync, ruff, pyright, and pytest on SQLite")
    for args in (
        ["uv", "sync", "--quiet"],
        ["uv", "run", "ruff", "check"],
        ["uv", "run", "ruff", "format", "--check"],
        ["uv", "run", "pyright"],
    ):
        subprocess.run(args, cwd=app, check=True, env=env)
    test_database = {"TEST_DATABASE_URL": f"sqlite+aiosqlite:///{app / 'test.db'}"}
    subprocess.run(["uv", "run", "pytest", "-q"], cwd=app, check=True, env={**env, **test_database})
    database = {"DATABASE_URL": f"sqlite+aiosqlite:///{app / 'local.db'}"}
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=app, check=True, env={**env, **database}
    )
    return ["uv", "run", "uvicorn", "app.main:app"], database


def prepare_nextjs(app: Path, env: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """Build the Next.js app, and return its command and the settings of its database."""
    log("pnpm install, db:generate, and build")
    for args in (
        ["pnpm", "install", "--silent"],
        ["pnpm", "--silent", "db:generate"],
        ["pnpm", "--silent", "build"],
    ):
        run(*args, cwd=app, env=env)
    # Each process has its own database in memory: the limit needs only Redis.
    return ["pnpm", "--silent", "start"], {"DATABASE_URL": "pglite:", "DATABASE_MIGRATE": "true"}


def check(binding: str, out: Path) -> None:
    target = TARGETS[binding]
    text = DEFINITION.read_text()
    text, count = re.subn(r"(?m)^app:\n", f"app:\n  {target.key}: redis\n", text, count=1)
    if count != 1:
        raise CheckError(f"{DEFINITION} has no 'app:' line.")
    # The other files of the definition, for example the OpenAPI documents of `apis`.
    shutil.copytree(DEFINITION.parent, out, dirs_exist_ok=True)
    definition = out / "app.yaml"
    definition.write_text(text)
    app = out / binding
    # The hand-written code of the example: appgen keeps an extension file that exists.
    shutil.copytree(DEFINITION.parent / "extensions" / binding, app, dirs_exist_ok=True)
    log(f"generate {definition} with {binding} in {app}")
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
    )

    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    prepare = prepare_fastapi if binding == "fastapi" else prepare_nextjs
    command, database = prepare(app, env)
    base = {**env, **database, "RATE_LIMIT_PER_MINUTE": str(LIMIT)}
    people = target.path

    log("one process without Redis: it counts in its memory")
    port = target.memory_port
    with started(command, app, port, base, out / f"app-{port}.log"):
        # The windows of the FastAPI app in memory start at the times of its own
        # clock, so a window can end during the requests. Then the second client
        # (another X-Forwarded-For) starts in the new window.
        expected, statuses = [200] * LIMIT + [429], list[int]()
        for client in ("10.0.0.1", "10.0.0.2"):
            url = f"http://127.0.0.1:{port}{people}"
            statuses = [get(url, {"X-Forwarded-For": client})[0] for _ in range(LIMIT + 1)]
            if statuses == expected:
                break
        else:
            raise CheckError(f"In memory, the statuses of {LIMIT + 1} requests are {statuses}.")

    settings = {**base, "RATE_LIMIT_STORE_URL": f"redis://127.0.0.1:{target.redis_port}/0"}
    redis_name = f"appgen-check-redis-{binding}"
    with redis(redis_name, target.redis_port), ExitStack() as stack:
        for port in target.ports:
            stack.enter_context(started(command, app, port, settings, out / f"app-{port}.log"))
        wait_for_a_new_window()
        first, second = target.ports
        log(f"send {REQUESTS} requests to each of the ports {first} and {second}")
        statuses = [
            status(f"http://127.0.0.1:{port}{people}")
            for _ in range(REQUESTS)
            for port in target.ports
        ]
        allowed, limited = statuses.count(200), statuses.count(429)
        if (allowed, limited) != (LIMIT, 2 * REQUESTS - LIMIT):
            raise CheckError(
                f"The two processes allowed {allowed} requests and limited {limited}: {statuses}."
            )
        code, headers, body = get(
            f"http://127.0.0.1:{first}{people}", headers={"Accept-Language": "de"}
        )
        retry_after = {name.lower(): value for name, value in headers.items()}.get("retry-after")
        if code != 429 or not retry_after or GERMAN not in body:
            raise CheckError(
                f"Over the limit in German: status {code}, Retry-After {retry_after}, {body!r}."
            )
        if (code := status(f"http://127.0.0.1:{second}/health")) != 200:
            raise CheckError(f"Over the limit, /health gave {code}, not 200.")

        log("stop Redis: the requests pass with a warning, or get 503 when fail closed")
        subprocess.run(["docker", "stop", redis_name], capture_output=True, check=True)
        if (code := status(f"http://127.0.0.1:{first}{people}")) != 200:
            raise CheckError(f"Without Redis, a request got {code}, not 200.")
        if "rate limit store is not available" not in (out / f"app-{first}.log").read_text():
            raise CheckError("Without Redis, the log has no warning.")
        closed = {**settings, "RATE_LIMIT_FAIL_CLOSED": "true"}
        port = target.fail_closed_port
        with started(command, app, port, closed, out / f"app-{port}.log"):
            if (code := status(f"http://127.0.0.1:{port}{people}")) != 503:
                raise CheckError(f"Fail closed without Redis, a request got {code}, not 503.")
    log("passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("binding", choices=sorted(TARGETS))
    parser.add_argument("out", nargs="?", type=Path, help="The output folder (default: temporary).")
    args = parser.parse_args()
    folder = None
    if args.out is not None:
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        folder = tempfile.TemporaryDirectory(prefix="appgen-rate-limit.")
        out = Path(folder.name)
    try:
        check(args.binding, out)
    except (CheckError, subprocess.CalledProcessError) as error:
        print(f"shared-rate-limit: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
