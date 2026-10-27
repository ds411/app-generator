"""Run the server code of the live updates of a Next.js app, and check the events (ADR 0051).

The app of tests/fixtures/record-rules.yaml has a live entity (Task) with
record rules for the reads (ADR 0025). This test runs its server code
with tsx and PGlite (in memory), without Next.js: the stubs of
scripts/files_test.py replace `next/headers` (a cookie jar) and the
other modules of Next.js. The test (scripts/live_test.ts):

1. Applies the migrations, and adds an admin, a member of each of two
   teams, a reviewer, and a project of each team.
2. Calls the route `/api/live` without a session (401) and with an
   entity that is not live (400), and opens a stream for each user.
3. Creates, changes, and deletes tasks with the repository of the app, as
   the server actions do. Each stream must get only the events of the
   tasks that the user may read before or after the change: the admin
   all tasks, a member the open tasks of the projects of the teams of
   the member, and the reviewer the done tasks. A client that leaves
   gets no more events.
4. Starts Redis in Docker, and checks two brokers with one Redis, as two
   replicas: each change of one broker goes to the subscriptions of both
   in less than 2 s. A broker without Redis at its URL logs one warning,
   and gives its changes to its own subscriptions.
5. Ends the streams, as the server does at SIGTERM: the open streams end,
   and a new stream ends after its `open` event.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/live_test.py --app <folder> [--no-redis]

scripts/check-nextjs.sh runs it. It needs pnpm, and Docker for Redis
(not with --no-redis). It uses the port 6394 for Redis.

Environment variables:
    REDIS_IMAGE                   The Redis image (default redis:8-alpine).
"""

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_shared_rate_limit import redis
from files_test import HOOKS, STUBS

FOLDER = ".appgen-live-test"
TEST = Path(__file__).with_suffix(".ts")
"""The test, which the script copies into the app: it imports the modules of the app."""
REDIS_PORT = 6394
REDIS_NAME = "appgen-check-redis-live-nextjs"


def run(app: Path, with_redis: bool) -> None:
    print("live-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    folder = app / FOLDER
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    (folder / "hooks.mjs").write_text(HOOKS, encoding="utf-8")
    for name, text in STUBS.items():
        (folder / name).write_text(text, encoding="utf-8")
    shutil.copyfile(TEST, folder / "test.ts")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("DATABASE_") and k != "LIVE_EVENTS_URL"
    }
    env |= {"DATABASE_URL": "pglite:", "AUTH_SECRET": "live-test-secret"}
    try:
        with redis(REDIS_NAME, REDIS_PORT) if with_redis else contextlib.nullcontext():
            if with_redis:
                env["APPGEN_LIVE_REDIS_URL"] = f"redis://127.0.0.1:{REDIS_PORT}"
            print("live-test: run the server code with PGlite", flush=True)
            hooks, test = f"./{FOLDER}/hooks.mjs", f"{FOLDER}/test.ts"
            result = subprocess.run(
                ["pnpm", "--silent", "exec", "tsx", "--import", hooks, test],
                cwd=app,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit("live-test: failed")
    print("live-test: passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    parser.add_argument("--no-redis", action="store_true", help="Do not start Redis in Docker.")
    args = parser.parse_args()
    run(args.app, not args.no_redis)


if __name__ == "__main__":
    main()
