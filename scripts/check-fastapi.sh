#!/bin/sh
# Generate the project tracker with the FastAPI binding, and check the
# output: install, lint, format, type check, tests, Docker image,
# traces, the calls of the clients of the third-party APIs
# (scripts/api_calls.py), and the smoke test (scripts/smoke_test.py:
# start the app and request it), in Docker and with SQLite (--local, with the mock server of
# the third-party APIs, scripts/mock_api.py), the schema change on a
# database with data (scripts/check_schema_change.py), the full-text
# search and its migration on Postgres (scripts/check_full_text_search.py),
# the rate limit that two processes share in Redis
# (scripts/check_shared_rate_limit.py), the live events that two
# processes send through Redis, and the users on a record that two
# brokers know through Redis (scripts/check_live_events.py),
# and the deployment files of each target against their schemas
# (scripts/check_deploy_files.py). Then generate the room booking
# example, which has the sign-in, the sign-up, the roles, and a
# provider, and check its code and run its tests. Last, generate
# tests/fixtures/provider-sign-in.yaml (only the sign-in with
# providers), and check it. For both apps, a browser signs in through
# the mock OpenID Connect provider (scripts/check_provider_sign_in.py).
# Then generate tests/fixtures/account-security.yaml (the verification
# of the email address, the delivery hook of the messages, and the
# second factor), and check its code and run its tests. Then generate
# tests/fixtures/seed-data.yaml (seed records with a CSV data file),
# check its code, and run its tests on SQLite and the test of its seed
# on Postgres. The smoke test also runs the seed on Postgres: the app
# starts with DATABASE_SEED=true. Last, generate
# tests/fixtures/record-rules.yaml (the record rules with conditions and
# owner paths), and check it and run its tests. Then generate
# tests/fixtures/webhooks.yaml (the webhooks with each signature scheme),
# and check it and run its tests on Postgres and SQLite. Then generate
# tests/fixtures/jobs.yaml (the kinds of jobs), check its code, run its
# tests on SQLite and the tests of the jobs on Postgres, and run one pass
# of its worker at a fixed time. Then generate tests/fixtures/files.yaml
# (file and image fields in an S3 bucket, and seed files), and check it
# and run its tests; the test of the bucket uses the S3 mock of moto.
# Then generate tests/fixtures/inbound-email.yaml with its hand-written
# logic (the inbound emails of each mail service), check it, run its
# tests on Postgres and SQLite, and send it emails
# (scripts/inbound_email_test.py). Then generate
# tests/fixtures/api-connections.yaml with its hand-written logic (an API
# with the authorization code flow), check it, run its tests on Postgres
# and SQLite, and connect a user at the mock OAuth server
# (scripts/api_connection_test.py). Then generate tests/fixtures/totals.yaml
# (the totals of the relations in computed fields, and the compare rules
# over totals), and check it and run its tests on Postgres and SQLite.
# Then generate
# tests/fixtures/invoices.yaml (the small DSL additions of M33: the
# sequences of the numbers on Postgres, and the largest number plus one
# on SQLite), and check it and run its tests on Postgres and SQLite.
# Then generate tests/fixtures/listings.yaml with the hand-written
# queries of tests/fixtures/listings/extensions/fastapi/ (ADR 0045), and
# check it and run its tests on Postgres and SQLite. Then generate
# tests/fixtures/courses.yaml (the users and the sessions of M36: the
# totals and the widgets of the signed-in user, `$me`), and check it and
# run its tests on Postgres and SQLite. Last, generate
# tests/fixtures/places.yaml (the point fields and the filters `near` and
# `area`, ADR 0046), and check it and run its tests on Postgres and
# SQLite.
# The pre-push hook runs this script when a push changes the generator
# or the FastAPI binding. Run it by hand from the repository root:
#
#   scripts/check-fastapi.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The other apps go to the folders
# "<output folder>-room-booking", "<output folder>-provider-sign-in",
# "<output folder>-account-security", "<output folder>-seed-data",
# "<output folder>-record-rules", "<output folder>-webhooks",
# "<output folder>-jobs", "<output folder>-files",
# "<output folder>-inbound-email", "<output folder>-api-connections",
# "<output folder>-totals", "<output folder>-invoices",
# "<output folder>-listings", "<output folder>-courses",
# "<output folder>-places", "<output folder>-rate-limit" (the app of
# the rate limit check), and "<output folder>-live-events" (the app of
# the live events check). The
# generated tests run on Postgres (Docker, or a database in
# TEST_DATABASE_URL), then on SQLite.
#
# Environment variables:
#   POSTGRES_IMAGE            The Postgres image of the tests and the smoke test.
#   REDIS_IMAGE               The Redis image of the shared rate limit and live events checks.
#   KUBERNETES_VERSION        The version of the Kubernetes schemas of the deployment files.
#   APPGEN_SCHEMA_CACHE       The folder of the downloaded schemas (default ~/.cache/appgen/schemas).
#   UV_IMAGE, PYTHON_IMAGE    Build arguments of the Docker image.
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.

set -eu

definition=examples/project-tracker/app.yaml
auth_definition=examples/room-booking/app.yaml
provider_definition=tests/fixtures/provider-sign-in.yaml
security_definition=tests/fixtures/account-security.yaml
seed_definition=tests/fixtures/seed-data.yaml
rules_definition=tests/fixtures/record-rules.yaml
webhooks_definition=tests/fixtures/webhooks.yaml
jobs_definition=tests/fixtures/jobs.yaml
files_definition=tests/fixtures/files.yaml
email_definition=tests/fixtures/inbound-email.yaml
connections_definition=tests/fixtures/api-connections.yaml
totals_definition=tests/fixtures/totals.yaml
invoices_definition=tests/fixtures/invoices.yaml
listings_definition=tests/fixtures/listings.yaml
courses_definition=tests/fixtures/courses.yaml
places_definition=tests/fixtures/places.yaml
root=$(pwd)

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-fastapi.XXXXXX")
    trap 'rm -rf "$out" "$out-room-booking" "$out-provider-sign-in" "$out-account-security" "$out-seed-data" "$out-record-rules" "$out-webhooks" "$out-jobs" "$out-files" "$out-inbound-email" "$out-api-connections" "$out-totals" "$out-invoices" "$out-listings" "$out-courses" "$out-places" "$out-rate-limit" "$out-live-events"' EXIT
fi
auth_out="$out-room-booking"
provider_out="$out-provider-sign-in"
security_out="$out-account-security"
seed_out="$out-seed-data"
rules_out="$out-record-rules"
webhooks_out="$out-webhooks"
jobs_out="$out-jobs"
files_out="$out-files"
email_out="$out-inbound-email"
connections_out="$out-api-connections"
totals_out="$out-totals"
invoices_out="$out-invoices"
listings_out="$out-listings"
courses_out="$out-courses"
places_out="$out-places"

step() {
    echo "check-fastapi: $*"
}

# In a cloud session, use the mirror images, and start Docker and pull
# the Postgres image. Outside cloud sessions, this does nothing.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
    scripts/sandbox-setup.sh
fi

step "generate $definition in $out"
# The hand-written code of the example: appgen keeps an extension file
# that exists.
cp -R examples/project-tracker/extensions/fastapi/. "$out"/
uv run --locked appgen generate "$definition" -b fastapi -o "$out" >/dev/null

cd "$out"
# The generated app has its own virtual environment.
unset VIRTUAL_ENV

step "uv sync"
uv sync --quiet
step "ruff check"
uv run ruff check
step "ruff format --check"
uv run ruff format --check
step "pyright"
uv run pyright
step "pytest"
uv run pytest -q
step "pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db

step "docker build"
set --
[ -n "${UV_IMAGE:-}" ] && set -- "$@" --build-arg "UV_IMAGE=$UV_IMAGE"
[ -n "${PYTHON_IMAGE:-}" ] && set -- "$@" --build-arg "PYTHON_IMAGE=$PYTHON_IMAGE"
# shellcheck disable=SC2086
docker build --quiet "$@" ${APPGEN_DOCKER_BUILD_ARGS:-} -t appgen-check-fastapi . >/dev/null

cd "$root"
step "appgen check"
uv run --locked appgen check "$definition" "$out"

step "calls of the third-party APIs"
uv run --locked scripts/api_calls.py fastapi "$out"

step "smoke test"
uv run --locked scripts/smoke_test.py fastapi --app "$out" --image appgen-check-fastapi

step "smoke test with the local database"
uv run --locked scripts/smoke_test.py fastapi --app "$out" --local

step "schema change"
uv run --locked scripts/check_schema_change.py "$out"

step "full-text search on Postgres"
uv run --locked scripts/check_full_text_search.py "$out"

step "shared rate limit"
rm -rf "$out-rate-limit"
uv run --locked scripts/check_shared_rate_limit.py fastapi "$out-rate-limit"

step "live events"
rm -rf "$out-live-events"
uv run --locked scripts/check_live_events.py "$out-live-events"

step "deployment files"
uv run --locked scripts/check_deploy_files.py fastapi

step "generate $auth_definition in $auth_out"
rm -rf "$auth_out"
uv run --locked appgen generate "$auth_definition" -b fastapi -o "$auth_out" >/dev/null
uv run --locked appgen check "$auth_definition" "$auth_out"
cd "$auth_out"
step "room booking: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "room booking: pytest"
uv run pytest -q
step "room booking: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"
step "room booking: the sign-in with the mock provider"
uv run --locked scripts/check_provider_sign_in.py "$auth_definition" "$auth_out"

step "generate $provider_definition in $provider_out"
rm -rf "$provider_out"
uv run --locked appgen generate "$provider_definition" -b fastapi -o "$provider_out" >/dev/null
uv run --locked appgen check "$provider_definition" "$provider_out"
cd "$provider_out"
step "provider sign-in: uv sync, ruff, pyright, pytest on SQLite"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"
step "provider sign-in: the sign-in with the mock provider"
uv run --locked scripts/check_provider_sign_in.py "$provider_definition" "$provider_out"
step "generate $security_definition in $security_out"
rm -rf "$security_out"
uv run --locked appgen generate "$security_definition" -b fastapi -o "$security_out" >/dev/null
uv run --locked appgen check "$security_definition" "$security_out"
cd "$security_out"
step "account security: uv sync, ruff, pyright, pytest on SQLite"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $seed_definition in $seed_out"
rm -rf "$seed_out"
uv run --locked appgen generate "$seed_definition" -b fastapi -o "$seed_out" >/dev/null
uv run --locked appgen check "$seed_definition" "$seed_out"
cd "$seed_out"
step "seed data: uv sync, ruff, pyright, pytest on SQLite, the seed test on Postgres"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
uv run pytest -q tests/test_seed.py
cd "$root"

step "generate $rules_definition in $rules_out"
rm -rf "$rules_out"
uv run --locked appgen generate "$rules_definition" -b fastapi -o "$rules_out" >/dev/null
uv run --locked appgen check "$rules_definition" "$rules_out"
cd "$rules_out"
step "record rules: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "record rules: pytest"
uv run pytest -q
step "record rules: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $webhooks_definition in $webhooks_out"
rm -rf "$webhooks_out"
uv run --locked appgen generate "$webhooks_definition" -b fastapi -o "$webhooks_out" >/dev/null
uv run --locked appgen check "$webhooks_definition" "$webhooks_out"
cd "$webhooks_out"
step "webhooks: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "webhooks: pytest"
uv run pytest -q
step "webhooks: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $jobs_definition in $jobs_out"
rm -rf "$jobs_out"
uv run --locked appgen generate "$jobs_definition" -b fastapi -o "$jobs_out" >/dev/null
uv run --locked appgen check "$jobs_definition" "$jobs_out"
cd "$jobs_out"
step "jobs: uv sync, ruff, pyright, pytest on SQLite, the tests of the jobs on Postgres"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
uv run pytest -q tests/jobs
step "jobs: one pass of the worker at a fixed time"
DATABASE_URL=sqlite+aiosqlite:///./worker.db uv run alembic upgrade head >/dev/null 2>&1
DATABASE_URL=sqlite+aiosqlite:///./worker.db uv run python -m app.worker --once --now 2026-06-15T12:00:00Z
rm -f worker.db
cd "$root"

step "generate $files_definition in $files_out"
rm -rf "$files_out"
uv run --locked appgen generate "$files_definition" -b fastapi -o "$files_out" >/dev/null
uv run --locked appgen check "$files_definition" "$files_out"
cd "$files_out"
step "files: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "files: pytest"
uv run pytest -q
step "files: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $email_definition in $email_out"
rm -rf "$email_out"
mkdir -p "$email_out"
# The hand-written logic of the fixture: appgen keeps an extension file
# that exists.
cp -R tests/fixtures/inbound-email/extensions/fastapi/. "$email_out"/
uv run --locked appgen generate "$email_definition" -b fastapi -o "$email_out" >/dev/null
uv run --locked appgen check "$email_definition" "$email_out"
cd "$email_out"
step "inbound email: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "inbound email: pytest"
uv run pytest -q
step "inbound email: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"
step "inbound email test"
uv run --locked scripts/inbound_email_test.py fastapi "$email_definition" --app "$email_out"

step "api connections: generate $connections_definition in $connections_out"
rm -rf "$connections_out"
mkdir -p "$connections_out"
# The hand-written logic of the fixture: appgen keeps an extension file
# that exists.
cp -R tests/fixtures/api-connections/extensions/fastapi/. "$connections_out"/
uv run --locked appgen generate "$connections_definition" -b fastapi -o "$connections_out" >/dev/null
uv run --locked appgen check "$connections_definition" "$connections_out"
cd "$connections_out"
step "api connections: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "api connections: pytest"
uv run pytest -q
step "api connections: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"
step "api connection test"
uv run --locked scripts/api_connection_test.py "$connections_definition" --app "$connections_out"

step "generate $totals_definition in $totals_out"
rm -rf "$totals_out"
uv run --locked appgen generate "$totals_definition" -b fastapi -o "$totals_out" >/dev/null
uv run --locked appgen check "$totals_definition" "$totals_out"
cd "$totals_out"
step "totals: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "totals: pytest"
uv run pytest -q
step "totals: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $invoices_definition in $invoices_out"
rm -rf "$invoices_out"
uv run --locked appgen generate "$invoices_definition" -b fastapi -o "$invoices_out" >/dev/null
uv run --locked appgen check "$invoices_definition" "$invoices_out"
cd "$invoices_out"
step "invoices: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "invoices: pytest"
uv run pytest -q
step "invoices: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $listings_definition in $listings_out"
rm -rf "$listings_out"
mkdir -p "$listings_out"
# The hand-written queries of the fixture: appgen keeps an extension file
# that exists.
cp -R tests/fixtures/listings/extensions/fastapi/. "$listings_out"/
uv run --locked appgen generate "$listings_definition" -b fastapi -o "$listings_out" >/dev/null
uv run --locked appgen check "$listings_definition" "$listings_out"
cd "$listings_out"
step "listings: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "listings: pytest"
uv run pytest -q
step "listings: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $courses_definition in $courses_out"
rm -rf "$courses_out"
uv run --locked appgen generate "$courses_definition" -b fastapi -o "$courses_out" >/dev/null
uv run --locked appgen check "$courses_definition" "$courses_out"
cd "$courses_out"
step "courses: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "courses: pytest"
uv run pytest -q
step "courses: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "generate $places_definition in $places_out"
rm -rf "$places_out"
uv run --locked appgen generate "$places_definition" -b fastapi -o "$places_out" >/dev/null
uv run --locked appgen check "$places_definition" "$places_out"
cd "$places_out"
step "places: uv sync, ruff, pyright"
uv sync --quiet
uv run ruff check
uv run ruff format --check
uv run pyright
step "places: pytest"
uv run pytest -q
step "places: pytest on SQLite"
TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest -q
rm -f test.db
cd "$root"

step "passed"
