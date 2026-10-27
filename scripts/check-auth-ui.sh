#!/bin/sh
# Check the sign-in and the permissions of the front ends: generate the
# room booking example for React and Next.js, sign in as a user of each
# role, and compare the menus, the pages, and the actions with what the
# role allows. Then sign up a new user, reset a password (Next.js),
# check that a user of a record rule sees only the records of the rule
# (also with conditions and owner paths, in tests/fixtures/record-rules.yaml),
# turn on a second factor and sign in with a code, and sign in with a
# provider through the mock provider: in Next.js, and in React with the
# FastAPI app (scripts/auth_ui_test.py). Then connect a new user to an API
# on the page /connections, through the authorization page of the mock
# server of the API (scripts/connection_ui_test.py, ADR 0033). Then show
# the rows of the queries of tests/fixtures/listings.yaml in a table, a
# card list, and a calendar (scripts/listings_ui_test.py, ADR 0045). Then
# sign in to the course hub of tests/fixtures/courses.yaml as each user
# with records, and check the values of the signed-in user (`$me`) in the
# widgets, the lists, the totals, and the forms
# (scripts/sessions_ui_test.py, M36). Then open the map of the places of
# tests/fixtures/places.yaml with a local tile server, and move it
# (scripts/places_ui_test.py, ADR 0046). Last, fill a cart of the shop
# of tests/fixtures/shop.yaml as a guest, sign up or sign in, and find
# the cart (scripts/guests_ui_test.py, ADR 0050).
# The pre-push hook runs only the sections of this script that a push
# changes (scripts/check_plan.py). Run it by hand from the repository
# root, to run all sections:
#
#   scripts/check-auth-ui.sh [binding ...]
#
# The script needs uv, pnpm, and the Chromium of Playwright (see
# scripts/auth_ui_test.py). It does not need Docker.

set -eu

# Run a section only if the pre-push hook selected it: APPGEN_CHECK_SECTIONS
# lists the selected sections (scripts/check_plan.py). Without the
# variable, run all sections.
section() {
    case " ${APPGEN_CHECK_SECTIONS-$1} " in
    *" $1 "*) return 0 ;;
    esac
    echo "check-auth-ui: skip $1 (no change)"
    return 1
}

# Run a test script for a part of the check. Without bindings in the
# arguments of the check, test the bindings of the selected sections
# "auth-ui:<part>:<binding>".
run_test() {
    part=$1
    script=$2
    shift 2
    if [ $# -eq 0 ]; then
        for binding in react nextjs react-api; do
            if section "auth-ui:$part:$binding"; then
                set -- "$@" "$binding"
            fi
        done
        [ $# -gt 0 ] || return 0
    fi
    uv run --locked "scripts/$script" "$@"
}

# In a cloud session, use the settings of the sandbox (uv and the proxy).
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
fi

run_test room-booking auth_ui_test.py "$@"
run_test connections connection_ui_test.py "$@"
run_test listings listings_ui_test.py "$@"
run_test courses sessions_ui_test.py "$@"
run_test places places_ui_test.py "$@"
run_test shop guests_ui_test.py "$@"
