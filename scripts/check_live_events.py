"""Run two processes of an app with one Redis, and check that both send the live events.

With `live: true` on an entity, the FastAPI app sends the changes of its
records to the open views at `GET /live` (server-sent events, ADR 0051).
With `LIVE_EVENTS_URL`, the changes go through Redis, so that each
replica sends the changes of all replicas. This check proves it with the
tasks of the project tracker:

1. Generate the project tracker, and migrate a SQLite database that the
   processes share. (`scripts/check-fastapi.sh` checks the code and the
   tests of the app.)
2. Start Redis in Docker, and two processes of the app with
   `LIVE_EVENTS_URL`. Open a stream to each process.
3. Create a task on the first process: both streams must get the event
   `created` in less than 2 s. Change the task on the second process, and
   delete it on the first process: both streams must get `changed` and
   `deleted`.
4. Stop Redis: a change on the first process must go to its own stream,
   and the log must have a warning. Start Redis again: both streams must
   get `reset`, and the next change must go to both streams again.
5. Send SIGTERM to the first process: its stream must end, and the
   process must stop in less than 10 s. (A server waits for the open
   requests before it stops.)
6. Generate tests/fixtures/record-rules.yaml (a task page that shows the
   other users on the task, ADR 0052), and run two brokers of its app
   with one Redis: a user on a task of one broker must get a new user
   on the task of the other broker in less than 2 s, and its leave.

Run it from the repository root:

    uv run scripts/check_live_events.py [output folder]

The script needs Docker and uv. It uses the ports 8441 and 8442, and
6393 (Redis).

Environment variables:
    REDIS_IMAGE                   The Redis image (default redis:8-alpine).
    APPGEN_SMOKE_TIMEOUT          Seconds to wait for a process to start (default 180).
"""

import argparse
import contextlib
import http.client
import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from check_shared_rate_limit import CheckError, get, redis, started

DEFINITION = Path("examples/project-tracker/app.yaml")
PRESENCE_DEFINITION = Path("tests/fixtures/record-rules.yaml")
PORTS = (8441, 8442)
REDIS_PORT = 6393
REDIS_NAME = "appgen-check-redis-live"
LIMIT = 2.0
"""The seconds from a change to its event in an open view (the exit criteria of M37)."""
STOP = 10
"""The seconds of a process with an open stream to stop after SIGTERM."""
PRESENCE_CHECK = """\
import asyncio
import sys
import time
from uuid import uuid4

from app.core.live import Broker, LiveEvent, PresentUser, Viewer


async def main(url: str, limit: float) -> None:
    first, second = Broker(url), Broker(url)
    task, ada, ben = uuid4(), uuid4(), uuid4()
    first.subscribe(Viewer(frozenset({"Task"}), ada))
    subscription = second.subscribe(Viewer(frozenset({"Task"}), ben))
    try:
        # The brokers connect: Ben calls again until both brokers know him.
        for _ in range(100):
            second.here("Task", task, ben, "Ben", False)
            await asyncio.sleep(0.1)
            if first.users("Task", task) and second.users("Task", task):
                break
        else:
            sys.exit("The brokers did not get the user of the second broker through Redis.")
        start = time.monotonic()
        others = first.here("Task", task, ada, "Ada", True)
        if others != [PresentUser(id=ben, name="Ben", typing=False)]:
            sys.exit(f"The first broker gave {others}, not Ben.")
        event = await asyncio.wait_for(subscription.next(), limit)
        ada_typing = [PresentUser(id=ada, name="Ada", typing=True)]
        if event != LiveEvent(type="presence", entity="Task", id=task, users=ada_typing):
            sys.exit(f"Ben got {event}, not Ada.")
        print(f"{(time.monotonic() - start) * 1000:.0f}")
        first.leave("Task", task, ada)
        event = await asyncio.wait_for(subscription.next(), limit)
        if event != LiveEvent(type="presence", entity="Task", id=task, users=[]):
            sys.exit(f"Ben got {event}, not the leave of Ada.")
    finally:
        await asyncio.gather(first.close(), second.close())


asyncio.run(main(sys.argv[1], float(sys.argv[2])))
"""
"""Two brokers of an app with presence in one process, with one Redis (ADR 0052)."""


def log(message: str) -> None:
    print(f"live-events: {message}", flush=True)


@dataclass(frozen=True, slots=True)
class Event:
    """An event of a stream, and the time when the stream got it."""

    data: dict[str, Any]
    time: float


class Stream:
    """A stream of the live events of a process, read by a thread."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.events: queue.Queue[Event | None] = queue.Queue()
        """The events, and None at the end of the stream."""
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=60)
        self.connection = http.client.HTTPConnection("127.0.0.1", port)
        self.connection.sock = self.socket
        self.connection.request("GET", "/live", headers={"Accept": "text/event-stream"})
        response = self.connection.getresponse()
        if response.status != 200:
            raise CheckError(f"GET /live on port {port} gave {response.status}.")
        self.response = response
        threading.Thread(target=self._read, daemon=True).start()
        self.expect("open")

    def _read(self) -> None:
        try:
            for line in self.response:
                text = line.decode().rstrip("\r\n")
                if text.startswith("data:"):
                    self.events.put(Event(json.loads(text[5:]), time.monotonic()))
        except OSError, ValueError, http.client.HTTPException:
            pass
        self.events.put(None)

    def _next(self, timeout: float) -> Event | None:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            raise CheckError(
                f"The stream of port {self.port} got nothing in {timeout} s."
            ) from None

    def expect(self, kind: str, id: str | None = None, timeout: float = 10) -> Event:
        """Return the next event, and check its type and the ID of its record."""
        event = self._next(timeout)
        if event is None:
            raise CheckError(f"The stream of port {self.port} ended before the event {kind}.")
        if event.data.get("type") != kind or (id is not None and event.data.get("id") != id):
            raise CheckError(f"The stream of port {self.port} got {event.data}, not {kind} {id}.")
        return event

    def expect_end(self, timeout: float) -> None:
        """Check that the stream ends in the time, without more events."""
        if (event := self._next(timeout)) is not None:
            raise CheckError(f"The stream of port {self.port} got {event.data}, not its end.")

    def close(self) -> None:
        # The thread holds the response: only a shutdown of the socket ends the connection.
        with contextlib.suppress(OSError):
            self.socket.shutdown(socket.SHUT_RDWR)
        self.connection.close()


@contextmanager
def opened(port: int) -> Generator[Stream]:
    stream = Stream(port)
    try:
        yield stream
    finally:
        stream.close()


def send(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a request with a JSON body, and return the JSON of the answer."""
    port, path = url.split("/", 1)
    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=30)
    try:
        data = json.dumps(body).encode() if body is not None else None
        connection.request(method, f"/{path}", data, {"Content-Type": "application/json"})
        response = connection.getresponse()
        text = response.read().decode()
        if response.status >= 300:
            raise CheckError(f"{method} /{path} on port {port} gave {response.status}: {text}")
        return json.loads(text) if text else {}
    finally:
        connection.close()


def check_delay(change: float, *events: Event) -> None:
    """Check that the events came in less than LIMIT seconds after the change."""
    for event in events:
        delay = event.time - change
        if delay >= LIMIT:
            raise CheckError(
                f"An event came {delay:.2f} s after the change, not less than {LIMIT} s."
            )
    log(f"the events came {max(e.time - change for e in events) * 1000:.0f} ms after the change")


def check(out: Path) -> None:
    # The other files of the definition, for example the OpenAPI documents of `apis`.
    shutil.copytree(DEFINITION.parent, out, dirs_exist_ok=True)
    app = out / "fastapi"
    # The hand-written code of the example: appgen keeps an extension file that exists.
    shutil.copytree(DEFINITION.parent / "extensions" / "fastapi", app, dirs_exist_ok=True)
    log(f"generate {out / 'app.yaml'} with fastapi in {app}")
    generate = ["uv", "run", "--locked", "appgen", "generate", str(out / "app.yaml")]
    subprocess.run(
        [*generate, "-b", "fastapi", "-o", str(app)], check=True, stdout=subprocess.DEVNULL
    )
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    database = {"DATABASE_URL": f"sqlite+aiosqlite:///{app / 'local.db'}"}
    log("uv sync, and the migrations with the seed records")
    subprocess.run(["uv", "sync", "--quiet"], cwd=app, check=True, env=env)
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=app, check=True, env={**env, **database}
    )
    subprocess.run(
        ["uv", "run", "python", "-m", "app.cli", "seed"],
        cwd=app,
        check=True,
        env={**env, **database},
        stdout=subprocess.DEVNULL,
    )
    settings = {**env, **database, "LIVE_EVENTS_URL": f"redis://127.0.0.1:{REDIS_PORT}/0"}
    command = ["uv", "run", "uvicorn", "app.main:app"]
    first, second = PORTS
    with redis(REDIS_NAME, REDIS_PORT), ExitStack() as stack:
        processes = [
            stack.enter_context(started(command, app, port, settings, out / f"app-{port}.log"))
            for port in PORTS
        ]
        a = stack.enter_context(opened(first))
        b = stack.enter_context(opened(second))
        status, _, body = get(f"http://127.0.0.1:{first}/projects")
        if status != 200 or not json.loads(body)["items"]:
            raise CheckError(f"GET /projects gave {status}, or no project: {body[:200]}")
        project = json.loads(body)["items"][0]["id"]

        log(f"create a task on port {first}, and change it on port {second}")
        change = time.monotonic()
        task = send("POST", f"{first}/tasks", {"title": "Live check", "project_id": project})
        check_delay(change, a.expect("created", task["id"]), b.expect("created", task["id"]))
        change = time.monotonic()
        send("PATCH", f"{second}/tasks/{task['id']}", {"status": "done"})
        check_delay(change, a.expect("changed", task["id"]), b.expect("changed", task["id"]))
        send("DELETE", f"{first}/tasks/{task['id']}")
        a.expect("deleted", task["id"])
        b.expect("deleted", task["id"])

        log("stop Redis: each process sends its own changes, with a warning")
        subprocess.run(["docker", "stop", REDIS_NAME], capture_output=True, check=True)
        task = send("POST", f"{first}/tasks", {"title": "Without Redis", "project_id": project})
        a.expect("created", task["id"])
        if (
            "The Redis of the live events is not available"
            not in (out / f"app-{first}.log").read_text()
        ):
            raise CheckError("Without Redis, the log has no warning.")

        log("start Redis again: the streams get reset, then the events of both processes")
        subprocess.run(["docker", "start", REDIS_NAME], capture_output=True, check=True)
        b.expect("reset", timeout=30)
        a.expect("reset", timeout=30)
        send("DELETE", f"{second}/tasks/{task['id']}")
        a.expect("deleted", task["id"])
        b.expect("deleted", task["id"])

        log(f"stop the process of port {first}: its stream ends, and the process stops")
        start = time.monotonic()
        os.killpg(processes[0].pid, signal.SIGTERM)
        a.expect_end(timeout=STOP)
        try:
            processes[0].wait(timeout=STOP)
        except subprocess.TimeoutExpired:
            raise CheckError(
                f"With an open stream, the process did not stop in {STOP} s."
            ) from None
        log(f"the process stopped in {time.monotonic() - start:.1f} s")
    check_presence(out / "presence")
    log("passed")


def check_presence(app: Path) -> None:
    """Check that two brokers with one Redis know the users on a record of both (ADR 0052)."""
    log(f"generate {PRESENCE_DEFINITION} with fastapi in {app}")
    generate = ["uv", "run", "--locked", "appgen", "generate", str(PRESENCE_DEFINITION)]
    subprocess.run(
        [*generate, "-b", "fastapi", "-o", str(app)], check=True, stdout=subprocess.DEVNULL
    )
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    subprocess.run(["uv", "sync", "--quiet"], cwd=app, check=True, env=env)
    log("two brokers with one Redis: the users on a task of both brokers")
    url = f"redis://127.0.0.1:{REDIS_PORT}/0"
    with redis(REDIS_NAME, REDIS_PORT):
        result = subprocess.run(
            ["uv", "run", "python", "-c", PRESENCE_CHECK, url, str(LIMIT)],
            cwd=app,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    if result.returncode != 0:
        raise CheckError(f"The users on a task through Redis: {result.stderr.strip()}")
    log(f"the users on the task came {result.stdout.strip()} ms after the call")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", type=Path, help="The output folder (default: temporary).")
    args = parser.parse_args()
    folder = None
    if args.out is not None:
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        folder = tempfile.TemporaryDirectory(prefix="appgen-live-events.")
        out = Path(folder.name)
    try:
        check(out)
    except (CheckError, subprocess.CalledProcessError) as error:
        print(f"live-events: failed: {error}", file=sys.stderr)
        return 1
    finally:
        if folder is not None:
            folder.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
