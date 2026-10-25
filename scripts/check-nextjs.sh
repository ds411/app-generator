#!/bin/sh
# Generate the project tracker with the Next.js binding, and check the
# output: install, lint, type check, build, Docker image, traces, and
# the smoke test with the UI tests (scripts/smoke_test.py --ui: start the
# app, request it, and run the Playwright tests in ui-tests/). Then the
# smoke test runs the built app with PGlite (--local), without Docker.
# Last, check the rate limit that two processes share in Redis
# (scripts/check_shared_rate_limit.py), and the deployment files of each
# target against their schemas (scripts/check_deploy_files.py).
# The pre-push hook runs this script when a push changes the generator
# or the Next.js binding. Run it by hand from the repository root:
#
#   scripts/check-nextjs.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The app of the rate limit check goes to the
# folder "<output folder>-rate-limit". The script needs pnpm, Docker, and
# the Chromium of Playwright (see scripts/smoke_test.py).
#
# Environment variables:
#   NODE_IMAGE                Build argument of the Docker image.
#   POSTGRES_IMAGE            The Postgres image of the smoke test.
#   REDIS_IMAGE               The Redis image of the shared rate limit check.
#   KUBERNETES_VERSION        The version of the Kubernetes schemas of the deployment files.
#   APPGEN_SCHEMA_CACHE       The folder of the downloaded schemas (default ~/.cache/appgen/schemas).
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.
#   PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the UI tests.

set -eu

definition=examples/project-tracker/app.yaml
root=$(pwd)

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs.XXXXXX")
    trap 'rm -rf "$out" "$out-rate-limit"' EXIT
fi

step() {
    echo "check-nextjs: $*"
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
cp -R examples/project-tracker/extensions/nextjs/. "$out"/
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
uv run --locked scripts/smoke_test.py nextjs --app "$out" --image appgen-check-nextjs --ui

step "smoke test with the local database"
uv run --locked scripts/smoke_test.py nextjs --app "$out" --local

step "shared rate limit"
rm -rf "$out-rate-limit"
uv run --locked scripts/check_shared_rate_limit.py nextjs "$out-rate-limit"

step "deployment files"
uv run --locked scripts/check_deploy_files.py nextjs

step "passed"
