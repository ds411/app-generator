#!/bin/sh
# Check the sign-in and the permissions of the front ends: generate the
# room booking example for React and Next.js, sign in as a user of each
# role, and compare the menus, the pages, and the actions with what the
# role allows. Then sign up a new user, reset a password (Next.js),
# check that a user of an owner rule sees only the records of the user,
# and sign in with a provider through the mock provider: in Next.js, and
# in React with the FastAPI app (scripts/auth_ui_test.py).
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
