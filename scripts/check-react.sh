#!/bin/sh
# Generate the project tracker with the React binding, and check the
# output: install, lint, type check, build, Docker image, traces, the
# calls of the client of a third-party API (scripts/api_calls.py), and
# the smoke test with the UI tests (scripts/smoke_test.py --ui: start the
# app, request it, and run the Playwright tests in ui-tests/). Then it
# generates tests/fixtures/seed-data.yaml, and runs lint, type check, and
# appgen check on it. Then it generates tests/fixtures/invoices.yaml (the
# small DSL additions of M33), and runs lint, type check, appgen check,
# the sequence test of the mock store (scripts/sequence_test.py), and the
# UI test of the manual order (scripts/order_ui_test.py) on it.
# Then it does lint, type check, and appgen check for
# tests/fixtures/totals.yaml (the totals of the relations, ADR 0034, and
# the lines editors, ADR 0035). Last, it does the same for
# tests/fixtures/listings.yaml with the hand-written queries of
# tests/fixtures/listings/extensions/react/ (ADR 0045).
# The pre-push hook runs only the sections of this script that a push
# changes (scripts/check_plan.py). Run it by hand from the repository
# root, to run all sections:
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
# The app of the invoices fixture (M33), in a temporary folder.
invoices_definition=tests/fixtures/invoices.yaml
invoices_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react-invoices.XXXXXX")
# The app of the totals fixture, in a temporary folder.
totals_definition=tests/fixtures/totals.yaml
totals_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react-totals.XXXXXX")
# The app of the listings fixture (ADR 0045), in a temporary folder.
listings_definition=tests/fixtures/listings.yaml
listings_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react-listings.XXXXXX")

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
    trap 'rm -rf "$seed_out" "$invoices_out" "$totals_out" "$listings_out"' EXIT
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-react.XXXXXX")
    trap 'rm -rf "$out" "$seed_out" "$invoices_out" "$totals_out" "$listings_out"' EXIT
fi

step() {
    echo "check-react: $*"
}

# Run a section only if the pre-push hook selected it: APPGEN_CHECK_SECTIONS
# lists the selected sections (scripts/check_plan.py). Without the
# variable, run all sections. A section passed when the next one starts:
# then the function adds it to the file APPGEN_CHECK_PASSED of the hook.
current=""
section() {
    if [ -n "$current" ] && [ -n "${APPGEN_CHECK_PASSED:-}" ]; then
        echo "$current" >>"$APPGEN_CHECK_PASSED"
    fi
    current=""
    case " ${APPGEN_CHECK_SECTIONS-$1} " in
    *" $1 "*)
        current=$1
        return 0
        ;;
    esac
    step "skip $1 (no change)"
    return 1
}

# In a cloud session, use the mirror images, start Docker, and build the
# Node image (NODE_IMAGE). Outside cloud sessions, this does nothing.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
    scripts/sandbox-setup.sh
fi

if section react:project-tracker; then
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

    step "calls of the third-party APIs"
    uv run --locked scripts/api_calls.py react "$out"

    step "smoke test"
    uv run --locked scripts/smoke_test.py react --app "$out" --image appgen-check-react --ui
fi

if section react:seed-data; then
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
fi

if section react:invoices; then
    step "generate $invoices_definition in $invoices_out"
    uv run --locked appgen generate "$invoices_definition" -b react -o "$invoices_out" >/dev/null
    (
        cd "$invoices_out"
        step "pnpm install (invoices)"
        pnpm install --silent
        step "pnpm lint (invoices)"
        pnpm --silent lint
        step "pnpm typecheck (invoices)"
        pnpm --silent typecheck
    )
    step "appgen check (invoices)"
    uv run --locked appgen check "$invoices_definition" "$invoices_out"

    step "sequence test"
    uv run --locked scripts/sequence_test.py --app "$invoices_out" --binding react

    step "manual order UI test"
    uv run --locked scripts/order_ui_test.py --app "$invoices_out" --binding react
fi

if section react:totals; then
    step "generate $totals_definition in $totals_out"
    uv run --locked appgen generate "$totals_definition" -b react -o "$totals_out" >/dev/null
    (
        cd "$totals_out"
        step "pnpm install (totals)"
        pnpm install --silent
        step "pnpm lint (totals)"
        pnpm --silent lint
        step "pnpm typecheck (totals)"
        pnpm --silent typecheck
    )
    step "appgen check (totals)"
    uv run --locked appgen check "$totals_definition" "$totals_out"
fi

if section react:listings; then
    step "generate $listings_definition in $listings_out"
    # The hand-written queries of the fixture: appgen keeps an extension file
    # that exists.
    cp -R tests/fixtures/listings/extensions/react/. "$listings_out"/
    uv run --locked appgen generate "$listings_definition" -b react -o "$listings_out" >/dev/null
    (
        cd "$listings_out"
        step "pnpm install (listings)"
        pnpm install --silent
        step "pnpm lint (listings)"
        pnpm --silent lint
        step "pnpm typecheck (listings)"
        pnpm --silent typecheck
    )
    step "appgen check (listings)"
    uv run --locked appgen check "$listings_definition" "$listings_out"
fi

step "passed"
