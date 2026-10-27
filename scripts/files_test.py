"""Run the server code of the files of a generated Next.js app, and check the results (ADR 0027).

The app of tests/fixtures/files.yaml has file and image fields, seed
files, an S3 storage, and record rules. This test runs its server code
with tsx and PGlite (in memory), without Next.js: small stubs replace
`next/headers` (a cookie jar), `next/cache`, `next/navigation`, and
`server-only`. The files go to a temporary folder. The test
(scripts/files_test.ts) gets the IDs and the seed files of the
definition in the variable APPGEN_FILES_PLAN. It:

1. Applies the migrations (`pnpm db:generate` makes them), and runs the
   seed. The folder must have the seed files.
2. Signs in as the admin, reads a document, and gets its files through
   the route `/files/document/<id>/<field>`: the content and the headers.
3. Uploads a new file, which replaces the old file in the folder. A file
   that is too large, a type that the field does not allow, a request
   without a file, and a name that is not a file field give errors. The
   delete of a file removes it from the folder.
4. Signs in as a member: the member reads the files of a document of
   another user, but cannot change them, and uploads the files of an own
   document and of a note. Without a session, the route gives 404, and
   an upload gives an error.
5. Deletes a document: its files leave the folder. A second seed adds
   the deleted seed record and its files again.
6. Checks the bucket storage against the S3 API of a moto server
   (`moto_server`, which `uv` installs for the test), and the helpers of
   the storage: the media types, the rules, the names, and the sizes.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/files_test.py <definition> --app <folder>

scripts/check-nextjs.sh runs it for tests/fixtures/files.yaml. It needs
pnpm and uv, but not Docker.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from appgen.bindings.nextjs.db import build_tables, seed_tables
from appgen.dsl import AppDefinition, check_file
from appgen.dsl.seed import record_id

FOLDER = ".appgen-files-test"
MOTO = "moto[server]>=5.2"
TEST = Path(__file__).with_suffix(".ts")
"""The test, which the script copies into the app: it imports the modules of the app."""

HOOKS = """\
import { register } from "node:module";

// Replace the modules of Next.js that need a request with stubs.
const stubs = {
  "next/headers": new URL("./next-headers.mjs", import.meta.url).href,
  "next/cache": new URL("./next-cache.mjs", import.meta.url).href,
  "next/navigation": new URL("./next-navigation.mjs", import.meta.url).href,
  "server-only": new URL("./empty.mjs", import.meta.url).href,
};
const source = `
const stubs = ${JSON.stringify(stubs)};
export async function resolve(specifier, context, next) {
  if (Object.hasOwn(stubs, specifier)) {
    return { url: stubs[specifier], format: "module", shortCircuit: true };
  }
  return next(specifier, context);
}
`;
register("data:text/javascript," + encodeURIComponent(source));
"""

STUBS = {
    "next-headers.mjs": """\
const jar = (globalThis.appgenCookies ??= new Map());
export async function cookies() {
  return {
    get: (name) => (jar.has(name) ? { name, value: jar.get(name) } : undefined),
    set: (name, value) => void jar.set(name, value),
    delete: (name) => void jar.delete(name),
  };
}
export async function headers() {
  return new Headers();
}
""",
    "next-cache.mjs": "export function revalidatePath() {}\n",
    "next-navigation.mjs": """\
export function notFound() {
  throw new Error("NEXT_NOT_FOUND");
}
export function redirect(url) {
  throw new Error(`NEXT_REDIRECT ${url}`);
}
""",
    "empty.mjs": "export {};\n",
}


def plan(definition: AppDefinition, endpoint: str) -> dict[str, Any]:
    """Return the IDs, the seed files, and the bucket settings of the test."""
    storage = definition.storage
    if storage is None or storage.kind != "s3":
        sys.exit("files-test: the definition needs a storage of the kind s3.")
    app = definition.app.name
    files: dict[str, str] = {}
    keys: dict[str, str] = {}
    for table in seed_tables(definition, build_tables(definition)):
        for file in table.files:
            files[file.key] = file.content
            keys[file.key.split("/")[2]] = file.key
    return {
        "folderEnv": storage.folder_env,
        "bucketEnv": storage.bucket_env,
        "ids": {
            "ada": record_id(app, "Person", "ada"),
            "ben": record_id(app, "Person", "ben"),
            "guide": record_id(app, "Document", "guide"),
        },
        "files": files,
        "keys": keys,
        "bucket": {
            storage.bucket_env: "test-files",
            storage.region_env: "us-east-1",
            storage.endpoint_env: endpoint,
            storage.access_key_env: "test",
            storage.secret_key_env: "test",
        },
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def moto_server() -> Generator[str]:
    """Start a moto server with the S3 API, and return its URL."""
    port = free_port()
    print("files-test: start the moto server", flush=True)
    process = subprocess.Popen(
        ["uv", "run", "--quiet", "--no-project", "--with", MOTO, "moto_server", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    sys.exit("files-test: the moto server did not start.")
                time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait()


def run(definition_path: Path, app: Path) -> None:
    definition, diagnostics = check_file(definition_path)
    if definition is None or diagnostics:
        sys.exit(f"files-test: the definition is not valid: {diagnostics}")
    assert definition.storage is not None
    print("files-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    folder = app / FOLDER
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    (folder / "hooks.mjs").write_text(HOOKS, encoding="utf-8")
    for name, text in STUBS.items():
        (folder / name).write_text(text, encoding="utf-8")
    try:
        with moto_server() as endpoint, tempfile.TemporaryDirectory() as files:
            shutil.copyfile(TEST, folder / "test.ts")
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("STORAGE_") and k != definition.storage.bucket_env
            }
            env |= {
                "APPGEN_FILES_PLAN": json.dumps(plan(definition, endpoint)),
                "DATABASE_URL": "pglite:",
                "AUTH_SECRET": "files-test-secret",
                definition.storage.folder_env: files,
            }
            print("files-test: run the server code with PGlite", flush=True)
            hooks, test = f"./{FOLDER}/hooks.mjs", f"{FOLDER}/test.ts"
            result = subprocess.run(
                ["pnpm", "--silent", "exec", "tsx", "--import", hooks, test],
                cwd=app,
                env=env,
                capture_output=True,
                text=True,
            )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit("files-test: failed")
    print("files-test: passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("definition", type=Path)
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    args = parser.parse_args()
    run(args.definition, args.app)


if __name__ == "__main__":
    main()
