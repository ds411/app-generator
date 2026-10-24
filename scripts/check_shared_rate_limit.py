"""Run two processes of the FastAPI app with one Redis, and check their shared rate limit.

With `x-fastapi-rate-limit-store: redis` in the `app` section, the rate
limit of the FastAPI app counts in Redis (`RATE_LIMIT_STORE_URL`), so all
replicas share one limit (ADR 0013). This check proves it:

1. Generate the project tracker with the key, and check the code of the
   app: ruff, pyright, and the tests on SQLite.
2. Start Redis in Docker, and two processes of the app on one SQLite
   database, with a limit of 10 requests in each minute.
3. Send 6 requests to each process: 10 of the 12 requests must pass,
   and 2 must get 429.
4. Stop Redis: a request must pass, and the log must have a warning. A
   process with `RATE_LIMIT_FAIL_CLOSED=true` must give 503.

Run it from the repository root:

    uv run scripts/check_shared_rate_limit.py [output folder]

The script needs uv and Docker. It uses the ports 8431 to 8433 (the app)
and 6391 (Redis).

Environment variables:
    REDIS_IMAGE                   The Redis image (default redis:8-alpine).
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for a process to start (default 180).
"""

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from appgen.bindings.fastapi.model import RATE_LIMIT_STORE_KEY

DEFINITION = Path("examples/project-tracker/app.yaml")
LIMIT = 10
REQUESTS = 6
"""The requests to each of the two processes: more than the limit together."""
REDIS_PORT = 6391
REDIS_NAME = "appgen-check-redis"
PORTS = (8431, 8432)
FAIL_CLOSED_PORT = 8433


class CheckError(Exception):
    """A failed check."""


def log(message: str) -> None:
    print(f"shared-rate-limit: {message}", flush=True)


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        args, cwd=cwd, check=True, env={**os.environ, **(env or {})}, stdout=subprocess.DEVNULL
    )


def status(url: str) -> int:
    """Return the status of a GET request."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return error.code


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


def wait_for_redis() -> None:
    """Wait until Redis answers PING."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", REDIS_PORT), timeout=2) as connection:
                connection.sendall(b"PING\r\n")
                if connection.recv(16).startswith(b"+PONG"):
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise CheckError("Redis did not start in 60 s.")


@contextmanager
def redis() -> Generator[None]:
    """Start Redis in Docker, and remove it at the end."""
    image = os.environ.get("REDIS_IMAGE", "redis:8-alpine")
    subprocess.run(["docker", "rm", "-f", REDIS_NAME], capture_output=True, check=False)
    run("docker", "run", "-d", "--name", REDIS_NAME, "-p", f"{REDIS_PORT}:6379", image)
    try:
        wait_for_redis()
        yield
    finally:
        subprocess.run(["docker", "rm", "-f", REDIS_NAME], capture_output=True, check=False)


@contextmanager
def started(app: Path, port: int, env: dict[str, str], log_file: Path) -> Generator[None]:
    """Start a process of the app, and stop it at the end."""
    args = ["uv", "run", "uvicorn", "app.main:app", "--port", str(port)]
    with log_file.open("w") as output:
        process = subprocess.Popen(
            args, cwd=app, env={**os.environ, **env}, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            wait_for(f"http://127.0.0.1:{port}/health")
            yield
        except BaseException:
            print(log_file.read_text()[-4000:], file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


def wait_for_a_new_window() -> None:
    """Wait for the next minute if this one ends soon, so that all requests are in one window."""
    second = time.time() % 60
    if second > 40:
        time.sleep(61 - second)


def check(out: Path) -> None:
    text = DEFINITION.read_text()
    text, count = re.subn(r"(?m)^app:\n", f"app:\n  {RATE_LIMIT_STORE_KEY}: redis\n", text, count=1)
    if count != 1:
        raise CheckError(f"{DEFINITION} has no 'app:' line.")
    # The other files of the definition, for example the OpenAPI documents of `apis`.
    shutil.copytree(DEFINITION.parent, out, dirs_exist_ok=True)
    definition = out / "app.yaml"
    definition.write_text(text)
    app = out / "fastapi"
    log(f"generate {definition} with fastapi in {app}")
    run(
        "uv",
        "run",
        "--locked",
        "appgen",
        "generate",
        str(definition),
        "-b",
        "fastapi",
        "-o",
        str(app),
    )

    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    database = {"DATABASE_URL": f"sqlite+aiosqlite:///{app / 'local.db'}"}
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
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=app, check=True, env={**env, **database}
    )

    settings = {
        **database,
        "RATE_LIMIT_PER_MINUTE": str(LIMIT),
        "RATE_LIMIT_STORE_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
    }
    with redis(), ExitStack() as stack:
        for port in PORTS:
            stack.enter_context(started(app, port, {**env, **settings}, out / f"api-{port}.log"))
        wait_for_a_new_window()
        log(f"send {REQUESTS} requests to each of the ports {PORTS[0]} and {PORTS[1]}")
        statuses = [
            status(f"http://127.0.0.1:{port}/people") for _ in range(REQUESTS) for port in PORTS
        ]
        allowed, limited = statuses.count(200), statuses.count(429)
        if (allowed, limited) != (LIMIT, 2 * REQUESTS - LIMIT):
            raise CheckError(
                f"The two processes allowed {allowed} requests and limited {limited}: {statuses}."
            )

        log("stop Redis: the requests pass with a warning, or get 503 when fail closed")
        subprocess.run(["docker", "stop", REDIS_NAME], capture_output=True, check=True)
        if (code := status(f"http://127.0.0.1:{PORTS[0]}/people")) != 200:
            raise CheckError(f"Without Redis, a request got {code}, not 200.")
        if "rate limit store is not available" not in (out / f"api-{PORTS[0]}.log").read_text():
            raise CheckError("Without Redis, the log has no warning.")
        closed = {**env, **settings, "RATE_LIMIT_FAIL_CLOSED": "true"}
        with started(app, FAIL_CLOSED_PORT, closed, out / f"api-{FAIL_CLOSED_PORT}.log"):
            if (code := status(f"http://127.0.0.1:{FAIL_CLOSED_PORT}/people")) != 503:
                raise CheckError(f"Fail closed without Redis, a request got {code}, not 503.")
    log("passed")


def main() -> int:
    if len(sys.argv) > 1:
        out = Path(sys.argv[1]).resolve()
        out.mkdir(parents=True, exist_ok=True)
        folder = None
    else:
        folder = tempfile.TemporaryDirectory(prefix="appgen-rate-limit.")
        out = Path(folder.name)
    try:
        check(out)
    except (CheckError, subprocess.CalledProcessError) as error:
        print(f"shared-rate-limit: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
