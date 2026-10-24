#!/bin/sh
# Prepare a Claude Code cloud session for the check scripts.
#
# The hook loads the defaults of scripts/sandbox.env (the mirror images
# of the checks) into the session: it adds the file to CLAUDE_ENV_FILE,
# so that each command of the session reads it. Then it runs
# scripts/sandbox-setup.sh, which starts Docker and prepares the images.
#
# The hook does nothing outside cloud sessions (CLAUDE_CODE_REMOTE is
# not "true"). A failed step prints a message and does not stop the
# session.

set -u

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

root=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    printf '. "%s"\n' "$root/scripts/sandbox.env" >>"$CLAUDE_ENV_FILE"
fi

"$root/scripts/sandbox-setup.sh" || true
exit 0
