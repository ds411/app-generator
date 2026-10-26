"""Check the full-text search of the FastAPI app (`x-fastapi-search: fulltext`) on Postgres.

The script copies a generated FastAPI app of the project tracker, which
has the full-text search, into a temporary folder, and then:

1. generates the app without the full-text search (`like`), applies its
   first migration to Postgres, and adds a project,
2. generates the app again with the full-text search, and makes the next
   migration with `alembic revision --autogenerate` on Postgres: it must
   create the GIN index of each entity under a test of the dialect,
3. applies the migration, and checks that the models and the migrations
   agree (`alembic check`), and that the search of a project uses its
   index,
4. applies all migrations to a new SQLite database, where the test of
   the dialect skips the GIN indexes, and runs `alembic check` there.

`scripts/check-fastapi.sh` runs it after its other checks. Run it by hand
from the repository root, with a generated app:

    uv run scripts/check_full_text_search.py <app folder>

The script needs uv and Docker (the image in POSTGRES_IMAGE, default
postgres:18).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

DEFINITION = Path("examples/project-tracker/app.yaml")
FIRST = Path("migrations/versions/0001_schema.py")
KEY = "  x-fastapi-search: fulltext\n"
INDEXES = ("ix_people_search", "ix_projects_search", "ix_tasks_search")
GUARD = 'if op.get_bind().dialect.name == "postgresql":'
# The query of the list endpoint of the projects, with the helpers of the app.
EXPLAIN = """
import asyncio
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.search import matches, search_vector, web_query
from app.models import Project


async def main() -> None:
    engine = create_async_engine(sys.argv[1])
    statement = select(Project.id).where(
        matches(search_vector(Project.name, Project.key), web_query("report"))
    )
    sql = statement.compile(engine, compile_kwargs={"literal_binds": True})
    async with engine.connect() as connection:
        await connection.execute(text("SET enable_seqscan = off"))
        for row in await connection.execute(text(f"EXPLAIN {sql}")):
            print(row[0])
    await engine.dispose()


asyncio.run(main())
"""


class FullTextSearchError(Exception):
    """A check of the full-text search failed."""


def log(message: str) -> None:
    print(f"full-text-search: {message}", flush=True)


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def start_postgres(name: str) -> str:
    """Start Postgres in Docker, and return the URL of its database."""
    image = os.environ.get("POSTGRES_IMAGE", "postgres:18")
    password = uuid.uuid4().hex
    options = ["--name", name, "-e", f"POSTGRES_PASSWORD={password}", "-p", "127.0.0.1::5432"]
    subprocess.run(
        ["docker", "run", "-d", "--rm", *options, image], check=True, capture_output=True
    )
    port = run(["docker", "port", name, "5432/tcp"], Path.cwd()).split(":")[-1].strip()
    for _ in range(60):
        ready = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"],
            capture_output=True,
        )
        if ready.returncode == 0:
            return f"postgresql+asyncpg://postgres:{password}@127.0.0.1:{port}/postgres"
        time.sleep(1)
    raise FullTextSearchError("Postgres did not start.")


def psql(name: str, sql: str) -> str:
    return run(["docker", "exec", name, "psql", "-U", "postgres", "-tAc", sql], Path.cwd())


def check(app: Path) -> None:
    root = Path.cwd()
    text = DEFINITION.read_text()
    if KEY not in text:
        raise FullTextSearchError(f"{DEFINITION} has no {KEY.strip()!r}.")
    container = f"appgen-full-text-{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory(prefix="appgen-full-text.") as temp:
        # The other files of the example, for example the OpenAPI documents of its APIs.
        shutil.copytree(DEFINITION.parent, Path(temp) / "definition")
        before = Path(temp) / "definition" / "app.yaml"
        before.write_text(text.replace(KEY, ""))
        work = Path(temp) / "app"
        shutil.copytree(app, work, ignore=shutil.ignore_patterns(".venv", "*.db", "__pycache__"))
        (work / FIRST).unlink()
        args = ["uv", "run", "--locked", "appgen", "generate"]
        log("generate the app without the full-text search")
        run([*args, str(before), "-b", "fastapi", "-o", str(work)], root)
        if "to_tsvector" in (work / FIRST).read_text():
            raise FullTextSearchError(f"{FIRST} has a GIN index without the full-text search.")

        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        log("start Postgres")
        env["DATABASE_URL"] = start_postgres(container)
        try:
            run(["uv", "sync", "--quiet"], work, env)
            log("apply the first migration, and add a project")
            run(["uv", "run", "alembic", "upgrade", "head"], work, env)
            person = uuid.uuid4()
            psql(
                container,
                "INSERT INTO people (id, name, email, role, active) VALUES "
                f"('{person}', 'Ada Lovelace', 'ada@example.com', 'lead', true)",
            )
            psql(
                container,
                "INSERT INTO projects (id, name, key, status, owner_id) VALUES "
                f"('{uuid.uuid4()}', 'Quarterly report', 'QR', 'active', '{person}')",
            )

            log("generate the app again with the full-text search")
            run([*args, str(DEFINITION.resolve()), "-b", "fastapi", "-o", str(work)], root)
            log("alembic revision --autogenerate on Postgres")
            message = "add the indexes of the full-text search"
            run(["uv", "run", "alembic", "revision", "--autogenerate", "-m", message], work, env)
            new = [p for p in (work / FIRST.parent).glob("*.py") if p.name != FIRST.name]
            code = new[0].read_text() if len(new) == 1 else ""
            missing = [name for name in INDEXES if name not in code]
            if missing or GUARD not in code:
                raise FullTextSearchError(
                    f"The new migration does not create {missing} under a test of the dialect:"
                    f"\n{code}"
                )
            log(f"alembic upgrade head ({new[0].name}), and alembic check")
            run(["uv", "run", "alembic", "upgrade", "head"], work, env)
            run(["uv", "run", "alembic", "check"], work, env)
            names = psql(
                container, "SELECT indexname FROM pg_indexes WHERE indexname LIKE '%search'"
            )
            if sorted(names.split()) != list(INDEXES):
                raise FullTextSearchError(f"The database has the indexes {names.split()}.")
            found = psql(
                container,
                "SELECT name FROM projects WHERE to_tsvector('english', name || ' ' || key) "
                "@@ websearch_to_tsquery('english', 'reports')",
            )
            if found.strip() != "Quarterly report":
                raise FullTextSearchError(f"The search found {found!r}.")
            plan = run(["uv", "run", "python", "-c", EXPLAIN, env["DATABASE_URL"]], work, env)
            if "ix_projects_search" not in plan:
                raise FullTextSearchError(
                    f"The search of the projects does not use its index:\n{plan}"
                )
        finally:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)

        log("apply all migrations to SQLite")
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(temp) / 'data.db'}"
        run(["uv", "run", "alembic", "upgrade", "head"], work, env)
        run(["uv", "run", "alembic", "check"], work, env)
        run(["uv", "run", "--locked", "appgen", "check", str(DEFINITION), str(work)], root)
    log("passed")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        check(Path(sys.argv[1]).resolve())
    except (FullTextSearchError, subprocess.CalledProcessError) as error:
        output = getattr(error, "stderr", None) or ""
        print(f"full-text-search: failed: {error}\n{output}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
