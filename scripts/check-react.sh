#!/bin/sh
# Generate the project tracker with the React binding, and check the
# output: install, lint, type check, build, Docker image, and traces.
# The pre-push hook runs this script when a push changes the generator
# or the React binding. Run it by hand from the repository root:
#
#   scripts/check-react.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The script needs pnpm and Docker.
#
# Environment variables:
#   NODE_IMAGE, NGINX_IMAGE   Build arguments of the Docker image.
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.

set -eu

definition=examples/project-tracker/app.yaml
root=$(pwd)

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react.XXXXXX")
    trap 'rm -rf "$out"' EXIT
fi

step() {
    echo "check-react: $*"
}

step "generate $definition in $out"
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

step "passed"
