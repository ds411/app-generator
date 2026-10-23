#!/bin/sh
# Prepare a Claude Code cloud session for the check scripts. The hook
# starts the Docker daemon, pulls the Postgres image (POSTGRES_IMAGE),
# and builds the Node image of the front-end checks (NODE_IMAGE) if it
# does not exist. The FastAPI tests cannot pull an image from a mirror
# by themselves, so the hook pulls it first. The image trusts the CA of
# the session proxy, so pnpm in `docker build` can reach the registry.
# The daemon of the environment setup script does not continue into the
# session, so each session must start it again.
#
# The hook also loads the defaults of scripts/sandbox.env (the mirror
# images of the checks) into the session: it adds the file to
# CLAUDE_ENV_FILE, so that each command of the session reads it.
#
# The hook does nothing outside cloud sessions (CLAUDE_CODE_REMOTE is
# not "true"). Without Docker, it only loads the defaults. A failed step
# prints a message and does not stop the session.
#
# Environment variables (scripts/sandbox.env gives the defaults):
#   POSTGRES_IMAGE  The Postgres image to pull.
#   NODE_IMAGE      The image to build (only if its name starts with localhost/).
#   APPGEN_CA_FILE  The CA bundle of the proxy (default /root/.ccr/ca-bundle.crt).

set -u

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

root=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
# shellcheck source=scripts/sandbox.env
. "$root/scripts/sandbox.env"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    printf '. "%s"\n' "$root/scripts/sandbox.env" >>"$CLAUDE_ENV_FILE"
fi

command -v docker >/dev/null 2>&1 || exit 0

image=$NODE_IMAGE
ca_file=${APPGEN_CA_FILE:-/root/.ccr/ca-bundle.crt}

say() {
    echo "session-start: $*" >&2
}

if ! docker info >/dev/null 2>&1; then
    say "start dockerd"
    # Start the daemon in a new session, so that it continues after the
    # hook ends.
    if command -v dockerd >/dev/null 2>&1; then
        setsid dockerd >"${TMPDIR:-/tmp}/dockerd.log" 2>&1 </dev/null &
    fi
    for _ in $(seq 1 30); do
        docker info >/dev/null 2>&1 && break
        sleep 1
    done
    if ! docker info >/dev/null 2>&1; then
        say "the Docker daemon did not start; see ${TMPDIR:-/tmp}/dockerd.log"
        exit 0
    fi
fi

postgres=$POSTGRES_IMAGE
if ! docker image inspect "$postgres" >/dev/null 2>&1; then
    say "pull $postgres"
    docker pull --quiet "$postgres" >/dev/null || say "the pull of $postgres failed"
fi

# Build only a local image. Another NODE_IMAGE comes from a registry.
case "$image" in localhost/*) ;; *) exit 0 ;; esac
docker image inspect "$image" >/dev/null 2>&1 && exit 0
if [ ! -f "$ca_file" ]; then
    say "no CA bundle at $ca_file; skip the build of $image"
    exit 0
fi

dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cp "$ca_file" "$dir/proxy-ca.crt"
cat >"$dir/Dockerfile" <<'DOCKERFILE'
FROM mirror.gcr.io/library/node:24-alpine
COPY proxy-ca.crt /usr/local/share/ca-certificates/proxy-ca.crt
RUN cat /usr/local/share/ca-certificates/proxy-ca.crt >> /etc/ssl/certs/ca-certificates.crt
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/proxy-ca.crt
DOCKERFILE

say "build $image"
if ! docker build --quiet --network host --build-arg HTTPS_PROXY -t "$image" "$dir" >/dev/null; then
    say "the build of $image failed"
fi
exit 0
