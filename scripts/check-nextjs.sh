#!/bin/sh
# Generate the project tracker with the Next.js binding, and check the
# output: install, lint, type check, build, Docker image, traces, the
# calls of the clients of the third-party APIs (scripts/api_calls.py),
# and the smoke test with the UI tests (scripts/smoke_test.py --ui: start the
# app, request it, and run the Playwright tests in ui-tests/). Then the
# smoke test runs the built app with PGlite (--local), without Docker.
# Then check the rate limit that two processes share in Redis
# (scripts/check_shared_rate_limit.py), and the deployment files of each
# target against their schemas (scripts/check_deploy_files.py). Then
# generate tests/fixtures/seed-data.yaml, and run lint, type check,
# appgen check, and the seed test (scripts/seed_test.py) on it. Then
# generate tests/fixtures/webhooks.yaml, and run lint, type check, build,
# appgen check, and the webhook test (scripts/webhook_test.py) on it, and
# the same for tests/fixtures/inbound-email.yaml with its hand-written
# logic and the inbound email test (scripts/inbound_email_test.py).
# Then generate tests/fixtures/jobs.yaml with the hand-written operations
# of tests/fixtures/jobs-extensions/nextjs/, and run lint, type check,
# appgen check, and the test of the routes of the jobs with a fixed clock
# (scripts/jobs_test.py) on it.
# Then generate tests/fixtures/files.yaml (file fields, ADR 0027), and
# run lint, type check, appgen check, and the files test
# (scripts/files_test.py) on it.
# Then generate tests/fixtures/events.yaml with the hand-written
# operations of tests/fixtures/events-extensions/nextjs/, and run lint,
# type check, appgen check, and the test of the events
# (scripts/events_test.py) on it.
# Then generate tests/fixtures/invoices.yaml (the small DSL additions of
# M33), and run lint, type check, appgen check, and the sequence test
# (scripts/sequence_test.py) on it.
# Last, generate tests/fixtures/totals.yaml (totals of relations, ADR
# 0034), and run lint, type check, appgen check, and the totals test
# (scripts/totals_test.py) on it.
# The pre-push hook runs this script when a push changes the generator
# or the Next.js binding. Run it by hand from the repository root:
#
#   scripts/check-nextjs.sh [output folder]
#
# Without an output folder, the script uses a temporary folder and
# deletes it at the end. The app of the rate limit check goes to the
# folder "<output folder>-rate-limit". The script needs pnpm, Docker, and
# the Chromium of Playwright (see scripts/smoke_test.py).
#
# Environment variables:
#   NODE_IMAGE                Build argument of the Docker image.
#   POSTGRES_IMAGE            The Postgres image of the smoke test.
#   REDIS_IMAGE               The Redis image of the shared rate limit check.
#   KUBERNETES_VERSION        The version of the Kubernetes schemas of the deployment files.
#   APPGEN_SCHEMA_CACHE       The folder of the downloaded schemas (default ~/.cache/appgen/schemas).
#   APPGEN_DOCKER_BUILD_ARGS  More arguments for `docker build`.
#   PLAYWRIGHT_CHROMIUM_EXECUTABLE  A Chromium for the UI tests.

set -eu

definition=examples/project-tracker/app.yaml
root=$(pwd)

# The apps of the seed data fixture (ADR 0021) and of the jobs fixture
# (ADR 0029), in temporary folders.
seed_definition=tests/fixtures/seed-data.yaml
seed_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-seed.XXXXXX")
# The app of the webhooks fixture (ADR 0028), in a temporary folder.
webhooks_definition=tests/fixtures/webhooks.yaml
webhooks_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-webhooks.XXXXXX")
# The app of the inbound email fixture (ADR 0030), in a temporary folder.
email_definition=tests/fixtures/inbound-email.yaml
email_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-email.XXXXXX")
jobs_definition=tests/fixtures/jobs.yaml
jobs_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-jobs.XXXXXX")
# The app of the files fixture (ADR 0027), in a temporary folder.
files_definition=tests/fixtures/files.yaml
files_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-files.XXXXXX")
# The app of the events fixture (ADR 0031), in a temporary folder.
events_definition=tests/fixtures/events.yaml
events_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-events.XXXXXX")
# The app of the invoices fixture (M33), in a temporary folder.
invoices_definition=tests/fixtures/invoices.yaml
invoices_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-invoices.XXXXXX")
# The app of the totals fixture (ADR 0034), in a temporary folder.
totals_definition=tests/fixtures/totals.yaml
totals_out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs-totals.XXXXXX")

if [ $# -gt 0 ]; then
    out=$1
    mkdir -p "$out"
    trap 'rm -rf "$seed_out" "$webhooks_out" "$email_out" "$jobs_out" "$files_out" "$events_out" "$invoices_out" "$totals_out"' EXIT
else
    out=$(mktemp -d "${TMPDIR:-/tmp}/appgen-nextjs.XXXXXX")
    trap 'rm -rf "$out" "$out-rate-limit" "$seed_out" "$webhooks_out" "$email_out" "$jobs_out" "$files_out" "$events_out" "$invoices_out" "$totals_out"' EXIT
fi

step() {
    echo "check-nextjs: $*"
}

# In a cloud session, use the mirror images, start Docker, and build the
# Node image (NODE_IMAGE). Outside cloud sessions, this does nothing.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    # shellcheck source=scripts/sandbox.env
    . scripts/sandbox.env
    scripts/sandbox-setup.sh
fi

step "generate $definition in $out"
# The hand-written code of the example: appgen keeps an extension file
# that exists.
cp -R examples/project-tracker/extensions/nextjs/. "$out"/
uv run --locked appgen generate "$definition" -b nextjs -o "$out" >/dev/null

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
# shellcheck disable=SC2086
docker build --quiet "$@" ${APPGEN_DOCKER_BUILD_ARGS:-} -t appgen-check-nextjs . >/dev/null

cd "$root"
step "appgen check"
uv run --locked appgen check "$definition" "$out"

step "calls of the third-party APIs"
uv run --locked scripts/api_calls.py nextjs "$out"

step "smoke test"
uv run --locked scripts/smoke_test.py nextjs --app "$out" --image appgen-check-nextjs --ui

step "smoke test with the local database"
uv run --locked scripts/smoke_test.py nextjs --app "$out" --local

step "shared rate limit"
rm -rf "$out-rate-limit"
uv run --locked scripts/check_shared_rate_limit.py nextjs "$out-rate-limit"

step "deployment files"
uv run --locked scripts/check_deploy_files.py nextjs

step "generate $seed_definition in $seed_out"
uv run --locked appgen generate "$seed_definition" -b nextjs -o "$seed_out" >/dev/null
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

step "seed test"
uv run --locked scripts/seed_test.py "$seed_definition" --app "$seed_out"

step "generate $webhooks_definition in $webhooks_out"
uv run --locked appgen generate "$webhooks_definition" -b nextjs -o "$webhooks_out" >/dev/null
(
    cd "$webhooks_out"
    step "pnpm install (webhooks)"
    pnpm install --silent
    step "pnpm lint (webhooks)"
    pnpm --silent lint
    step "pnpm typecheck (webhooks)"
    pnpm --silent typecheck
    step "pnpm build (webhooks)"
    pnpm --silent build >/dev/null
)
step "appgen check (webhooks)"
uv run --locked appgen check "$webhooks_definition" "$webhooks_out"

step "webhook test"
uv run --locked scripts/webhook_test.py "$webhooks_definition" --app "$webhooks_out"

step "generate $email_definition in $email_out"
# The hand-written logic of the fixture: appgen keeps an extension file
# that exists.
cp -R tests/fixtures/inbound-email/extensions/nextjs/. "$email_out"/
uv run --locked appgen generate "$email_definition" -b nextjs -o "$email_out" >/dev/null
(
    cd "$email_out"
    step "pnpm install (inbound email)"
    pnpm install --silent
    step "pnpm lint (inbound email)"
    pnpm --silent lint
    step "pnpm typecheck (inbound email)"
    pnpm --silent typecheck
    step "pnpm build (inbound email)"
    pnpm --silent build >/dev/null
)
step "appgen check (inbound email)"
uv run --locked appgen check "$email_definition" "$email_out"

step "inbound email test"
uv run --locked scripts/inbound_email_test.py nextjs "$email_definition" --app "$email_out"

step "generate $jobs_definition in $jobs_out"
cp -R tests/fixtures/jobs-extensions/nextjs/. "$jobs_out"/
uv run --locked appgen generate "$jobs_definition" -b nextjs -o "$jobs_out" >/dev/null
(
    cd "$jobs_out"
    step "pnpm install (jobs)"
    pnpm install --silent
    step "pnpm lint (jobs)"
    pnpm --silent lint
    step "pnpm typecheck (jobs)"
    pnpm --silent typecheck
)
step "appgen check (jobs)"
uv run --locked appgen check "$jobs_definition" "$jobs_out"

step "jobs test"
uv run --locked scripts/jobs_test.py --app "$jobs_out"

step "generate $files_definition in $files_out"
uv run --locked appgen generate "$files_definition" -b nextjs -o "$files_out" >/dev/null
(
    cd "$files_out"
    step "pnpm install (files)"
    pnpm install --silent
    step "pnpm lint (files)"
    pnpm --silent lint
    step "pnpm typecheck (files)"
    pnpm --silent typecheck
)
step "appgen check (files)"
uv run --locked appgen check "$files_definition" "$files_out"

step "files test"
uv run --locked scripts/files_test.py "$files_definition" --app "$files_out"

step "generate $events_definition in $events_out"
cp -R tests/fixtures/events-extensions/nextjs/. "$events_out"/
uv run --locked appgen generate "$events_definition" -b nextjs -o "$events_out" >/dev/null
(
    cd "$events_out"
    step "pnpm install (events)"
    pnpm install --silent
    step "pnpm lint (events)"
    pnpm --silent lint
    step "pnpm typecheck (events)"
    pnpm --silent typecheck
)
step "appgen check (events)"
uv run --locked appgen check "$events_definition" "$events_out"

step "events test"
uv run --locked scripts/events_test.py --app "$events_out"

step "generate $invoices_definition in $invoices_out"
uv run --locked appgen generate "$invoices_definition" -b nextjs -o "$invoices_out" >/dev/null
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
uv run --locked scripts/sequence_test.py --app "$invoices_out"

step "generate $totals_definition in $totals_out"
uv run --locked appgen generate "$totals_definition" -b nextjs -o "$totals_out" >/dev/null
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

step "totals test"
uv run --locked scripts/totals_test.py --app "$totals_out"

step "passed"
