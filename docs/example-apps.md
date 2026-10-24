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
elements are open gaps until you write them: 10 for Next.js, 13 for
React, and 4 for FastAPI. The React app also marks the API with a secret
as a gap, because a browser app cannot keep a secret. The FastAPI app has no pages, so
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

### Show data of a third-party API

The dashboard of the project tracker has the custom widget `holidays`,
which shows the next public holidays. Its hand-written code is in
`examples/project-tracker/extensions/nextjs/`: the widget calls a server
action, and the server action calls the server-only client of the
holidays API. The example also has the code of the custom operation
`schedule_task`.

1. Copy the hand-written code into the app, and generate it again.
   appgen keeps an extension file that exists:

   ```sh
   cp -R examples/project-tracker/extensions/nextjs/. /tmp/tracker-nextjs/
   uv run appgen generate examples/project-tracker/app.yaml -b nextjs -o /tmp/tracker-nextjs
   ```

2. Start the mock server from the repository root (see
   [Call a third-party API](#call-a-third-party-api)), and add the base
   URL to the settings of the app:

   ```sh
   uv run scripts/mock_api.py
   printf 'HOLIDAYS_API_URL=http://localhost:8430/holidays\n' >> /tmp/tracker-nextjs/.env.local
   ```

3. Start the dev server, and open <http://localhost:3000>. The widget
   shows the holidays of the example of the OpenAPI document.

The React app has the same widget, in
`examples/project-tracker/extensions/react/`. Its code calls the client
of the holidays API in the browser. With mock data, the client gives the
example answers of the OpenAPI document, so the app needs no mock
server:

```sh
cp -R examples/project-tracker/extensions/react/. /tmp/tracker-react/
uv run appgen generate examples/project-tracker/app.yaml -b react -o /tmp/tracker-react
cd /tmp/tracker-react && pnpm install && pnpm dev
```

`appgen generate` gives a warning for the API `exchange_rates`: it has a
secret, so the React app has no client for it.

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

### Call a third-party API

The project tracker calls a public holidays API. The custom operation
`schedule_task` sets the due date of a task to a number of working
days from today, without weekends and public holidays. The example has
its hand-written code in `examples/project-tracker/extensions/fastapi/`.
A mock server answers with the examples of the OpenAPI documents, so
the demo does not call the real API.

1. Copy the hand-written code into the app, and generate it again.
   appgen keeps an extension file that exists:

   ```sh
   cp -R examples/project-tracker/extensions/fastapi/. /tmp/tracker-fastapi/
   uv run appgen generate examples/project-tracker/app.yaml -b fastapi -o /tmp/tracker-fastapi
   ```

2. Start the mock server from the repository root. It prints the base
   URL of each API:

   ```sh
   uv run scripts/mock_api.py
   ```

3. In a second terminal, add the base URL to the settings of the app,
   and start the API as in the steps above:

   ```sh
   cd /tmp/tracker-fastapi
   printf 'HOLIDAYS_API_URL=http://localhost:8430/holidays\n' >> .env
   uv run fastapi dev app/main.py
   ```

4. Add a person, a project, and a task, and run the operation. Use the
   IDs of the answers:

   ```sh
   curl -s -X POST localhost:8000/people -H 'Content-Type: application/json' \
     -d '{"name": "Ada", "email": "ada@example.com"}'
   curl -s -X POST localhost:8000/projects -H 'Content-Type: application/json' \
     -d '{"name": "Demo", "key": "DEMO", "owner_id": "<person ID>"}'
   curl -s -X POST localhost:8000/tasks -H 'Content-Type: application/json' \
     -d '{"title": "Demo task", "project_id": "<project ID>"}'
   curl -s -X POST localhost:8000/tasks/<task ID>/schedule-task \
     -H 'Content-Type: application/json' -d '{"working_days": 5, "country_code": "DE"}'
   ```

   The answer has the new `due_date`. The mock server records the
   request of the operation: open <http://localhost:8430/_requests>.

The smoke test with `--local` does these steps (see below).

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

The third-party APIs of the apps point to the mock server of
`scripts/mock_api.py`. In Docker, the apps reach it through the host
gateway (`host.docker.internal`). With `--local`, the FastAPI check also
runs the custom operation `schedule_task` through it. With `--ui`, the
dashboard of the Next.js app calls the holidays API through it. These
checks need the hand-written code of the example (see
[Call a third-party API](#call-a-third-party-api)).
`scripts/check-react-api.sh` builds the React app with
`x-react-data: api` and the base URL of the mock server, and its
dashboard calls the holidays API from the browser.

## Clean up

Stop a Compose run with `docker compose down -v` in the app folder.
The `-v` option also deletes the database volume. The local databases
are in the app folders: `.pglite/` (Next.js) and `local.db` (FastAPI).
If you started the Postgres container for the local runs, remove it:

```sh
docker rm -f tracker-db
```
