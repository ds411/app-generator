#!/bin/sh
# Check the translations of the front ends: generate the project tracker
# with a test language for React and Next.js, and find the text of the
# default language in the code and on the pages
# (scripts/translation_test.py).
# The pre-push hook runs this script when a push changes the generator
# or a front-end binding. Run it by hand from the repository root:
#
#   scripts/check-translations.sh [binding ...]
#
# The script needs uv, pnpm, and the Chromium of Playwright (see
# scripts/translation_test.py). It does not need Docker.

set -eu

# In a cloud session, use the settings of the sandbox (uv and the proxy).
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
fi

uv run --locked scripts/translation_test.py "$@"
