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
# card list, and a calendar (scripts/listings_ui_test.py, ADR 0045). Last,
# sign in to the course hub of tests/fixtures/courses.yaml as each user
# with records, and check the values of the signed-in user (`$me`) in the
# widgets, the lists, the totals, and the forms
# (scripts/sessions_ui_test.py, M36).
# The pre-push hook runs this script when a push changes the generator
# or a front-end binding. Run it by hand from the repository root:
#
#   scripts/check-auth-ui.sh [binding ...]
#
# The script needs uv, pnpm, and the Chromium of Playwright (see
# scripts/auth_ui_test.py). It does not need Docker.

set -eu

# In a cloud session, use the settings of the sandbox (uv and the proxy).
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
fi

uv run --locked scripts/auth_ui_test.py "$@"
uv run --locked scripts/connection_ui_test.py "$@"
uv run --locked scripts/listings_ui_test.py "$@"
uv run --locked scripts/sessions_ui_test.py "$@"
