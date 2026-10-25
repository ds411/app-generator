#!/bin/sh
# Generate the project tracker with the FastAPI binding, and check the
# output: install, lint, format, type check, tests, Docker image,
# traces, the calls of the clients of the third-party APIs
# (scripts/api_calls.py), and the smoke test (scripts/smoke_test.py:
# start the app and request it), in Docker and with SQLite (--local, with the mock server of
# the third-party APIs, scripts/mock_api.py), the schema change on a
# database with data (scripts/check_schema_change.py), the rate limit
# that two processes share in Redis (scripts/check_shared_rate_limit.py),
# and the deployment files of each target against their schemas
# (scripts/check_deploy_files.py). Then generate the room booking
# example, which has the sign-in, the sign-up, the roles, and a
# provider, and check its code and run its tests. Last, generate
# tests/fixtures/provider-sign-in.yaml (only the sign-in with
# providers), and check it. For both apps, a browser signs in through
# the mock OpenID Connect provider (scripts/check_provider_sign_in.py).
# Last, generate tests/fixtures/account-security.yaml (the verification
# of the email address, the delivery hook of the messages, and the
# second factor), and check its code and run its tests.
# The pre-push hook runs this script when a push changes the generator
# or the FastAPI binding. Run it by hand from the repository root:
#
#   scripts/check-fastapi.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The other apps go to the folders
# "<output folder>-room-booking", "<output folder>-provider-sign-in",
# "<output folder>-account-security", and "<output folder>-rate-limit"
# (the app of the rate limit check). The
# generated tests run on Postgres (Docker, or a database in
# TEST_DATABASE_URL), then on SQLite.
#
# Environment variables:
#   POSTGRES_IMAGE            The Postgres image of the tests and the smoke test.
#   REDIS_IMAGE               The Redis image of the shared rate limit check.
#   KUBERNETES_VERSION        The version of the Kubernetes schemas of the deployment files.
#   APPGEN_SCHEMA_CACHE       The folder of the downloaded schemas (default ~/.cache/appgen/schemas).
#   UV_IMAGE, PYTHON_IMAGE    Build arguments of the Docker image.
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.

set -eu

definition=examples/project-tracker/app.yaml
auth_definition=examples/room-booking/app.yaml
provider_definition=tests/fixtures/provider-sign-in.yaml
security_definition=tests/fixtures/account-security.yaml
root=$(pwd)

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-fastapi.XXXXXX")
    trap 'rm -rf "$out" "$out-room-booking" "$out-provider-sign-in" "$out-account-security" "$out-rate-limit"' EXIT
fi
auth_out="$out-room-booking"
provider_out="$out-provider-sign-in"
security_out="$out-account-security"

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

step "shared rate limit"
rm -rf "$out-rate-limit"
uv run --locked scripts/check_shared_rate_limit.py fastapi "$out-rate-limit"

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

step "passed"
