#!/bin/sh
# Check the API client of the React app: generate the project tracker
# with `x-react-data: api` for FastAPI and React, start both apps, and
# open the project table: each page of the table must load with one
# request to the API, and a change in a second browser must show on the
# task board of the first (scripts/api_client_test.py). Then do the same with
# tests/fixtures/invoices.yaml, and move a row and a card of the views
# with a manual order (scripts/order_ui_test.py).
# The pre-push hook runs only the sections of this script that a push
# changes (scripts/check_plan.py). Run it by hand from the repository
# root, to run all sections:
#
#   scripts/check-react-api.sh [output folder]
#
# The script needs uv, pnpm, and the Chromium of Playwright (see
# scripts/api_client_test.py). It does not need Docker.

set -eu

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
    echo "check-react-api: skip $1 (no change)"
    return 1
}

# In a cloud session, use the settings of the sandbox (uv and the proxy).
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
fi

echo "check-react-api: install the Playwright package of ui-tests/"
pnpm --dir ui-tests install --silent

if section react-api:project-tracker; then
    uv run --locked scripts/api_client_test.py "$@"
fi

if section react-api:invoices; then
    uv run --locked scripts/order_ui_test.py --binding react-api
fi
