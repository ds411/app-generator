#!/bin/sh
# Check the translations of the front ends: generate the project tracker
# with a test language for React and Next.js, and find the text of the
# default language in the code and on the pages
# (scripts/translation_test.py).
# The pre-push hook runs only the sections of this script that a push
# changes (scripts/check_plan.py). Run it by hand from the repository
# root, to run all sections:
#
#   scripts/check-translations.sh [binding ...]
#
# The script needs uv, pnpm, and the Chromium of Playwright (see
# scripts/translation_test.py). It does not need Docker.

set -eu

# Run a section only if the pre-push hook selected it: APPGEN_CHECK_SECTIONS
# lists the selected sections (scripts/check_plan.py). Without the
# variable, run all sections.
section() {
    case " ${APPGEN_CHECK_SECTIONS-$1} " in
    *" $1 "*) return 0 ;;
    esac
    echo "check-translations: skip $1 (no change)"
    return 1
}

# In a cloud session, use the settings of the sandbox (uv and the proxy).
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
fi

# Without bindings, test the bindings of the selected sections.
if [ $# -eq 0 ]; then
    for binding in react nextjs; do
        if section "translations:$binding"; then
            set -- "$@" "$binding"
        fi
    done
    [ $# -gt 0 ] || exit 0
fi

uv run --locked scripts/translation_test.py "$@"
