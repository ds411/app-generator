#!/bin/sh
# Generate the project tracker with the FastAPI binding, and check the
# output: install, lint, format, type check, tests, Docker image,
# traces, and the smoke test (scripts/smoke_test.py: start the app and
# request it). The pre-push hook runs this script when a push changes the
# generator or the FastAPI binding. Run it by hand from the repository
# root:
#
#   scripts/check-fastapi.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The generated tests need Docker, or a database
# in TEST_DATABASE_URL.
#
# Environment variables:
#   POSTGRES_IMAGE            The Postgres image of the tests and the smoke test.
#   UV_IMAGE, PYTHON_IMAGE    Build arguments of the Docker image.
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.

set -eu

definition=examples/project-tracker/app.yaml
root=$(pwd)

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-fastapi.XXXXXX")
    trap 'rm -rf "$out"' EXIT
fi

step() {
    echo "check-fastapi: $*"
}

step "generate $definition in $out"
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

step "docker build"
set --
[ -n "${UV_IMAGE:-}" ] && set -- "$@" --build-arg "UV_IMAGE=$UV_IMAGE"
[ -n "${PYTHON_IMAGE:-}" ] && set -- "$@" --build-arg "PYTHON_IMAGE=$PYTHON_IMAGE"
# shellcheck disable=SC2086
docker build --quiet "$@" ${APPGEN_DOCKER_BUILD_ARGS:-} -t appgen-check-fastapi . >/dev/null

cd "$root"
step "appgen check"
uv run --locked appgen check "$definition" "$out"

step "smoke test"
uv run --locked scripts/smoke_test.py fastapi --app "$out" --image appgen-check-fastapi

step "passed"
