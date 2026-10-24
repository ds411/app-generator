# Run the example apps

This guide shows how to generate the three example apps from
`examples/project-tracker/app.yaml`, check their traces, and run them.
You can run each app on your machine or in Docker. On your machine,
the Next.js app and the FastAPI app can use a local database instead of
a Postgres server.

| Binding   | App                           | Data in Docker      | Local database       | Local URL               | Docker URL              |
| --------- | ----------------------------- | ------------------- | -------------------- | ----------------------- | ----------------------- |
| `nextjs`  | A full-stack app (Next.js 16) | Postgres            | PGlite or Postgres   | <http://localhost:3000> | <http://localhost:3000> |
| `fastapi` | A REST API (FastAPI 0.161)    | Postgres            | SQLite or Postgres   | <http://localhost:8000> | <http://localhost:8000> |
| `react`   | A front end (React 19)        | Mock data in memory | Mock data in memory  | <http://localhost:5173> | <http://localhost:8080> |

## Contents

- [Requirements](#requirements)
- [Generate and check the apps](#generate-and-check-the-apps)
- [Choose the database for the local runs](#choose-the-database-for-the-local-runs)
- [Next.js app](#nextjs-app)
- [FastAPI app](#fastapi-app)
- [React app](#react-app)
- [Use a registry mirror](#use-a-registry-mirror)
- [Smoke test all apps](#smoke-test-all-apps)
- [Clean up](#clean-up)

## Requirements

- [uv](https://docs.astral.sh/uv/). uv installs Python 3.14 for the
  FastAPI app.
- Node.js 24 and [pnpm](https://pnpm.io/) for the Next.js and React
  apps.
- Docker with Docker Compose, for the Docker runs. The local runs need
  Docker only if you use Postgres.

Install appgen from the repository root:

```sh
uv sync
```

## Generate and check the apps

Run these commands from the repository root. Each app goes to its own
folder, here in `/tmp`:

```sh
for binding in nextjs fastapi react; do
  uv run appgen generate examples/project-tracker/app.yaml -b $binding -o /tmp/tracker-$binding
  uv run appgen check examples/project-tracker/app.yaml /tmp/tracker-$binding
done
```

`appgen generate` prints the files that it wrote and the generation
gaps. `appgen check` prints the trace coverage of the definition and
the invalid traces. For each app, the result is `Result: passed.` with
no uncovered elements and no invalid traces. The stubs of the custom
elements are open gaps until you write them: 8 for Next.js and React,
3 for FastAPI. The FastAPI app has no pages, so
its report shows the kinds `page` and `ui` as excluded. See
[traces.md](traces.md) for the report format.

The second example, `examples/room-booking/app.yaml`, works the same
way. Replace `project-tracker` with `room-booking` in the commands. It
uses the CRUD shorthand with the default views and forms, so its
definition is short.

Run `appgen generate` again to update an app after you change the
definition. appgen does not change the extension files.

## Choose the database for the local runs

The Next.js app and the FastAPI app use Postgres in Docker. The Docker
runs start their own Postgres. For the local runs, you can use a local
database or a Postgres server:

- **Local database (no server).** The Next.js app uses PGlite, a
  Postgres that runs in the Node.js process. The FastAPI app uses
  SQLite, a database in a file. You need no Docker and no setup. The
  steps below use this option.
- **Postgres server.** Use it to test with the database of production.
  Start the container below, and use the Postgres steps of each app.

[ADR 0007](adr/0007-local-database.md) explains the choice of PGlite
and SQLite.

### Start Postgres

Start one Postgres container for the two apps:

```sh
docker run -d --name tracker-db -p 5432:5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=project_tracker postgres:18
```

Make a second database for the FastAPI app, because the two apps make
tables with the same names:

```sh
docker exec tracker-db createdb -U postgres project_tracker_api
```

## Next.js app

### Run on your machine

1. Go to the app folder, and install the dependencies:

   ```sh
   cd /tmp/tracker-nextjs
   pnpm install
   ```

2. Write the settings file `.env.local` for PGlite:

   ```sh
   printf 'DATABASE_URL=pglite:./.pglite\nDATABASE_MIGRATE=true\nDATABASE_SEED=true\n' > .env.local
   ```

   With `DATABASE_MIGRATE=true`, the server applies the migrations when
   it starts. With `DATABASE_SEED=true`, it then adds the seed records
   to the empty tables. PGlite keeps the data in the folder `.pglite/`.

3. Write the first migration from the schema. The command writes the
   SQL files into `drizzle/`:

   ```sh
   pnpm db:generate
   ```

4. Start the dev server:

   ```sh
   pnpm dev
   ```

5. Open <http://localhost:3000>.

To apply the migrations without the server, stop the server and run
`pnpm db:migrate`. To add the seed records without the server, run
`DATABASE_URL=pglite:./.pglite pnpm db:seed`. The seed adds records
only if all tables are empty. Only one process can open the PGlite
folder. To delete all data, stop the server and delete `.pglite/`.

To use the Postgres container instead, copy the settings file in step 2
(`cp .env.example .env.local`), and set `DATABASE_MIGRATE=true` in it.
The `DATABASE_URL` in the file agrees with the Postgres container.

### Run in Docker

```sh
cd /tmp/tracker-nextjs
docker compose up --build
```

Compose starts Postgres and the app on <http://localhost:3000>. The
build writes the first migration if `drizzle/` does not exist. The app
applies the migrations when it starts.

## FastAPI app

### Run on your machine

1. Go to the app folder, and install the dependencies:

   ```sh
   cd /tmp/tracker-fastapi
   uv sync
   ```

2. Write the settings file `.env` for SQLite:

   ```sh
   printf 'DATABASE_URL=sqlite+aiosqlite:///./local.db\n' > .env
   ```

   The API and Alembic read `DATABASE_URL` from `.env`. Do not only set
   `DATABASE_URL` in the shell: a shell variable that you do not export
   has no effect. SQLite keeps the data in the file `local.db`.

   To use the Postgres container instead, write the URL of its FastAPI
   database:

   ```sh
   printf 'DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/project_tracker_api\n' > .env
   ```

3. Apply the migrations:

   ```sh
   uv run alembic upgrade head
   ```

   The output shows `Context impl SQLiteImpl.` for SQLite and
   with `Context impl PostgresqlImpl.` for Postgres.

4. Start the API:

   ```sh
   uv run fastapi dev app/main.py
   ```

5. Open <http://localhost:8000/docs> for the API documentation.
   `GET /health` gives `{"status":"ok"}`.

To run the tests of the app, run `uv run pytest`. The tests start their
own Postgres with Testcontainers, so Docker must run. To run the tests
on SQLite without Docker, set `TEST_DATABASE_URL`:

```sh
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest
```

To delete all data of the local database, delete `local.db`.

### Run in Docker

```sh
cd /tmp/tracker-fastapi
docker compose up --build
```

Compose builds the image, starts Postgres, applies the migrations, and
starts the API on <http://localhost:8000>.

## React app

The React app has no back end. It keeps mock data in memory, so it
does not need Postgres.

### Run on your machine

```sh
cd /tmp/tracker-react
pnpm install
pnpm dev
```

Open <http://localhost:5173>.

### Run in Docker

The React app has a Dockerfile, but no Compose file. Build the image
and run it:

```sh
cd /tmp/tracker-react
docker build -t tracker-react .
docker run --rm -p 8080:8080 tracker-react
```

nginx serves the app on <http://localhost:8080>.

## Use a registry mirror

The Dockerfiles use images from Docker Hub. To use other images, for
example from a mirror, set these build arguments:

| App       | Build arguments              | Default images                                       |
| --------- | ---------------------------- | ---------------------------------------------------- |
| `nextjs`  | `NODE_IMAGE`                 | `node:24-alpine`                                     |
| `fastapi` | `UV_IMAGE`, `PYTHON_IMAGE`   | `ghcr.io/astral-sh/uv:0.11`, `python:3.14-slim`         |
| `react`   | `NODE_IMAGE`, `NGINX_IMAGE`  | `node:24-alpine`, `nginxinc/nginx-unprivileged:1.29-alpine` |

The Compose files read the Postgres image from the environment
variable `POSTGRES_IMAGE`. For example, for the FastAPI app:

```sh
export POSTGRES_IMAGE=mirror.gcr.io/library/postgres:18
docker compose build \
  --build-arg UV_IMAGE=mirror.gcr.io/astral/uv:0.11 \
  --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.14-slim
docker compose up
```

For the React app, give the arguments to `docker build`:

```sh
docker build -t tracker-react \
  --build-arg NODE_IMAGE=mirror.gcr.io/library/node:24-alpine \
  --build-arg NGINX_IMAGE=mirror.gcr.io/nginxinc/nginx-unprivileged:1.29-alpine .
```

If your network uses a proxy with its own CA certificate, the Node.js
image must trust that certificate. Build a local Node.js image that
adds the certificate and sets `NODE_EXTRA_CA_CERTS`, and give it as
`NODE_IMAGE`. Give the proxy to the build with
`--build-arg HTTPS_PROXY=$HTTPS_PROXY`.

## Smoke test all apps

`scripts/smoke_test.py` does the Docker steps of this guide for all
three apps, one at a time. It generates each app, builds its image,
starts it, and checks its pages or endpoints:

```sh
uv run scripts/smoke_test.py
```

To test one app, give its binding, for example
`uv run scripts/smoke_test.py fastapi`. The script reads the build
arguments of the section above from the environment. It also reads
`APPGEN_DOCKER_BUILD_ARGS`, with more arguments for `docker build`, for
example `--network host`. The script header lists all the environment
variables.

To test the local run of an app that you generated and installed, give
its folder and `--local`. The script starts the app on your machine
with PGlite or SQLite, without Docker. Build the Next.js app first with
`pnpm build`:

```sh
uv run scripts/smoke_test.py nextjs --app /tmp/tracker-nextjs --local
uv run scripts/smoke_test.py fastapi --app /tmp/tracker-fastapi --local
```

## Clean up

Stop a Compose run with `docker compose down -v` in the app folder.
The `-v` option also deletes the database volume. The local databases
are in the app folders: `.pglite/` (Next.js) and `local.db` (FastAPI).
If you started the Postgres container for the local runs, remove it:

```sh
docker rm -f tracker-db
```
