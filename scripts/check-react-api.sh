#!/bin/sh
# Check the API client of the React app: generate the project tracker
# with `x-react-data: api` for FastAPI and React, start both apps, and
# load a page with data from the API (scripts/api_client_test.py).
# The pre-push hook runs this script when a push changes the React or
# the FastAPI binding. Run it by hand from the repository root:
#
#   scripts/check-react-api.sh [output folder]
#
# The script needs uv, pnpm, and the Chromium of Playwright (see
# scripts/api_client_test.py). It does not need Docker.

set -eu

# In a cloud session, use the settings of the sandbox (uv and the proxy).
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
fi

echo "check-react-api: install the Playwright package of ui-tests/"
pnpm --dir ui-tests install --silent

uv run --locked scripts/api_client_test.py "$@"
