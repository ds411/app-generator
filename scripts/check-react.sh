#!/bin/sh
# Generate the project tracker with the React binding, and check the
# output: install, lint, type check, build, Docker image, traces, and
# the smoke test with the UI tests (scripts/smoke_test.py --ui: start the
# app, request it, and run the Playwright tests in ui-tests/). Then it
# generates tests/fixtures/seed-data.yaml, and runs lint, type check, and
# appgen check on it.
# The pre-push hook runs this script when a push changes the generator
# or the React binding. Run it by hand from the repository root:
#
#   scripts/check-react.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The script needs pnpm, Docker, and the Chromium
# of Playwright (see scripts/smoke_test.py).
#
# Environment variables:
#   NODE_IMAGE, NGINX_IMAGE   Build arguments of the Docker image.
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.
#   PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the UI tests.

set -eu

definition=examples/project-tracker/app.yaml
root=$(pwd)

# The app of the seed data fixture (ADR 0021), in a temporary folder.
seed_definition=tests/fixtures/seed-data.yaml
seed_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react-seed.XXXXXX")

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
    trap 'rm -rf "$seed_out"' EXIT
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react.XXXXXX")
    trap 'rm -rf "$out" "$seed_out"' EXIT
fi

step() {
    echo "check-react: $*"
}

# In a cloud session, use the mirror images, start Docker, and build the
# Node image (NODE_IMAGE). Outside cloud sessions, this does nothing.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
    scripts/sandbox-setup.sh
fi

step "generate $definition in $out"
# The hand-written code of the example: appgen keeps an extension file
# that exists.
cp -R examples/project-tracker/extensions/react/. "$out"/
uv run --locked appgen generate "$definition" -b react -o "$out" >/dev/null

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
[ -n "${NGINX_IMAGE:-}" ] && set -- "$@" --build-arg "NGINX_IMAGE=$NGINX_IMAGE"
# shellcheck disable=SC2086
docker build --quiet "$@" ${APPGEN_DOCKER_BUILD_ARGS:-} -t appgen-check-react . >/dev/null

cd "$root"
step "appgen check"
uv run --locked appgen check "$definition" "$out"

step "smoke test"
uv run --locked scripts/smoke_test.py react --app "$out" --image appgen-check-react --ui

step "generate $seed_definition in $seed_out"
uv run --locked appgen generate "$seed_definition" -b react -o "$seed_out" >/dev/null
(
    cd "$seed_out"
    step "pnpm install (seed data)"
    pnpm install --silent
    step "pnpm lint (seed data)"
    pnpm --silent lint
    step "pnpm typecheck (seed data)"
    pnpm --silent typecheck
)
step "appgen check (seed data)"
uv run --locked appgen check "$seed_definition" "$seed_out"

step "passed"
