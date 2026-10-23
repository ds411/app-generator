#!/bin/sh
# Generate the project tracker with the Next.js binding, and check the
# output: install, lint, type check, build, Docker image, traces, and
# the smoke test (scripts/smoke_test.py: start the app and request it).
# The pre-push hook runs this script when a push changes the generator
# or the Next.js binding. Run it by hand from the repository root:
#
#   scripts/check-nextjs.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The script needs pnpm and Docker.
#
# Environment variables:
#   NODE_IMAGE                Build argument of the Docker image.
#   POSTGRES_IMAGE            The Postgres image of the smoke test.
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.

set -eu

definition=examples/project-tracker/app.yaml
root=$(pwd)

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs.XXXXXX")
    trap 'rm -rf "$out"' EXIT
fi

step() {
    echo "check-nextjs: $*"
}

step "generate $definition in $out"
uv run --locked appgen generate "$definition" -b nextjs -o "$out" >/dev/null

cd "$out"

step "pnpm install"
pnpm install --silent
step "pnpm lint"
pnpm --silent lint
step "pnpm typecheck"
pnpm --silent typecheck
step "pnpm build"
pnpm --silent build >/dev/null

step "docker build"
set --
[ -n "${NODE_IMAGE:-}" ] && set -- "$@" --build-arg "NODE_IMAGE=$NODE_IMAGE"
# shellcheck disable=SC2086
docker build --quiet "$@" ${APPGEN_DOCKER_BUILD_ARGS:-} -t appgen-check-nextjs . >/dev/null

cd "$root"
step "appgen check"
uv run --locked appgen check "$definition" "$out"

step "smoke test"
uv run --locked scripts/smoke_test.py nextjs --app "$out" --image appgen-check-nextjs

step "passed"
