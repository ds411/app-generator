# Contributing

This file describes how we plan, write, and review work in this
repository. The project is a proof of concept for an application code
generator. A YAML DSL defines an application. The generator uses Jinja2
templates to write the code for a binding (a target stack). Traces in
the generated code refer back to the app definition.

## Contents

- [Workflow](#workflow)
- [Planning](#planning)
- [Stories](#stories)
- [Labels](#labels)
- [Branches](#branches)
- [Commits](#commits)
- [Pull requests](#pull-requests)
- [Definition of done](#definition-of-done)
- [Generated code](#generated-code)
- [Tooling](#tooling)
- [Pre-push hook](#pre-push-hook)
- [Cloud sessions](#cloud-sessions)
- [AI-assisted work](#ai-assisted-work)

## Workflow

1. Pick an open story from the current milestone.
2. Assign the story to yourself.
3. Make a branch from `main`.
4. Make commits that follow the commit format.
5. Open a pull request that closes the story.
6. Merge the pull request with "Squash and merge" when the pre-push
   hook passes and the review is complete. Use the squash commit
   message from the pull request description.

## Planning

We plan with GitHub milestones and issues.

- A **milestone** is a deliverable increment with a goal, a scope, and
  exit criteria. Use [the milestone template](.github/MILESTONE_TEMPLATE.md).
  Define each milestone in `.github/planning/milestones.yml`. The
  "Planning sync" workflow creates or updates the milestones on each
  push to `main`.
- A **story** is an issue that one pull request can deliver. Each story
  belongs to one milestone. Use the "Story" issue form.
- Work on the milestones in their number order. A story can start
  before its milestone starts only if its dependencies are done.
- Record each important design decision as an ADR (architecture
  decision record) in `docs/adr/`. Give each ADR a number and a short
  title, for example `0001-trace-format.md`.

## Stories

- Write the user story from the view of one role:
  - **App author**: writes the YAML app definition.
  - **App developer**: works in the generated code.
  - **Maintainer**: works on the generator, the bindings, or the CLI.
- Write acceptance criteria that a test or a command can check.
- List the app definition elements that the story adds or covers. This
  links the plan to the trace coverage.
- Keep stories small. If a story is size L, split it.
- Write dependencies as `Blocked by #<n>`.

## Labels

| Label              | Use                                                   |
| ------------------ | ----------------------------------------------------- |
| `story`            | A story. The story form adds this label.              |
| `area: dsl`        | The YAML DSL, its schema, and validation.             |
| `area: generator`  | The generator core, templates, and generation gaps.   |
| `area: traces`     | The trace format, the trace scanner, and the checker. |
| `area: cli`        | The command line interface.                           |
| `area: tooling`    | The repository setup, CI, and Docker.                 |
| `binding: nextjs`  | The Next.js binding.                                  |
| `binding: react`   | The React binding.                                    |
| `binding: fastapi` | The FastAPI binding.                                  |
| `bug`              | Something that does not work as specified.            |
| `blocked`          | Work cannot continue until a dependency is done.      |
| `deferred`         | Planned, but deferred. Do not start this work yet.    |

`.github/planning/labels.yml` defines these labels. The "Planning sync"
workflow creates or updates them on each push to `main`. To add or
change a label, change that file.

## Branches

- Make each branch from `main`.
- Name the branch `<type>/<issue>-<short-name>`, for example
  `feat/12-dsl-loader`. The types are the same as the commit types.
- Branches that tools make, for example `claude/<name>`, are also
  permitted.
- Do not push directly to `main`.

## Commits

We use [Conventional Commits](https://www.conventionalcommits.org/).
Enable the commit template once per clone:

```sh
git config commit.template .gitmessage
```

Format:

```text
<type>(<scope>): <summary>

<body>

<trailers>
```

Rules:

- Write the summary in the imperative mood: "add", not "added".
- Keep the subject line at 72 characters or fewer. Do not end it with a
  period.
- In the body, say what changes and why. Wrap lines at 72 characters.
- Add `Refs #<n>` to link the story. Add `Closes #<n>` only if the
  commit completes the story.
- For a breaking change, put `!` before the colon and add a
  `BREAKING CHANGE:` trailer.

| Type       | Use                                                  |
| ---------- | ---------------------------------------------------- |
| `feat`     | A new feature.                                       |
| `fix`      | A bug fix.                                           |
| `docs`     | Documentation only.                                  |
| `test`     | Tests only.                                          |
| `refactor` | A code change that does not change behavior.         |
| `perf`     | A performance improvement.                           |
| `build`    | The build system, packaging, or Docker.              |
| `ci`       | The CI configuration.                                |
| `chore`    | Maintenance that does not fit another type.          |
| `revert`   | A revert of an earlier commit.                       |

| Scope      | Area                                                 |
| ---------- | ---------------------------------------------------- |
| `dsl`      | The YAML DSL, its schema, and validation.            |
| `gen`      | The generator core and generation gaps.              |
| `trace`    | The trace format, the scanner, and the checker.      |
| `cli`      | The command line interface.                          |
| `nextjs`   | The Next.js binding.                                 |
| `react`    | The React binding.                                   |
| `fastapi`  | The FastAPI binding.                                 |
| `examples` | The example app definitions and their output.        |
| `repo`     | The repository setup, templates, and CI.             |
| `deps`     | Dependency updates.                                  |

Example:

```text
feat(dsl): add relations between entities

Entities can now refer to other entities with one-to-many and
many-to-one relations. The validator rejects a relation to an entity
that does not exist.

Refs #14
```

## Pull requests

- Use the pull request template. Fill in each section, or write "Not
  applicable".
- Give the pull request a title in the commit subject format. The title
  becomes the subject of the squash commit.
- Write the recommended squash commit message in the "Squash commit
  message" section. Use this message when you merge the pull request.
- Link each story that the pull request completes with `Closes #<n>`.
- Keep one story in one pull request where possible.
- Open the pull request as a draft until it is ready for review.
- Merge with "Squash and merge" only after the pre-push hook passes
  and the review is complete.

## Definition of done

A story is done when all these conditions are true:

- All acceptance criteria are true.
- Tests for the change exist and pass in the pre-push hook.
- Lint and type checks pass in the pre-push hook.
- For changes to the generator or a binding:
  - A second generation run gives the same output (no diff).
  - The generated example apps build.
  - The trace check reports no invalid traces.
- The docs agree with the change.
- The skill agrees with the change: the agent skill in
  `src/appgen/skills/appgen/` describes each changed command, option, DSL
  section, and diagnostic code (ADR 0015). Its JSON examples, exit codes,
  and defaults agree with the CLI (`tests/test_skill_statements.py`).
  After a change to `docs/dsl.md`, run
  `uv run scripts/update_skill_references.py`.
- The pull request that closes the story is merged.

## Generated code

- Do not edit generated files by hand. Change the app definition, a
  template, or a generation gap file.
- The same app definition and the same generator version must give the
  same output, byte for byte.
- Each generated part of the code carries a trace to the app definition
  element that it comes from.
- Where a binding cannot generate an element, the generator makes a
  generation gap. Hand-written code fills the gap and carries a trace
  to the same element.
- The ADRs in `docs/adr/` define the trace format and the generation gap
  mechanism.

## Tooling

- Python: use [uv](https://docs.astral.sh/uv/) for environments,
  dependencies, and commands. Do not use `pip` directly.
- TypeScript: use [pnpm](https://pnpm.io/). Do not use `npm` or `yarn`.
- The generated apps use the same tools: uv for Python apps and pnpm for
  TypeScript apps. Each generated app has a Dockerfile.
- The README gives the setup, lint, and test commands for this
  repository. The first code changes add them.

## Pre-push hook

We run no CI on pull requests, because GitHub Actions minutes cost
money. A git pre-push hook runs the checks instead. Enable it once per
clone:

```sh
git config core.hooksPath .githooks
```

- `.githooks/pre-push` runs the checks of each part that the push
  changes, and stops the push if a check fails. For the Python part,
  the checks are `ruff check`, `ruff format --check`, `pyright`,
  `pytest`, and `appgen check` on the golden output of the bindings
  (`tests/golden/`). The trace check fails on an invalid trace. A
  change to a Markdown file also runs these checks, because
  `tests/test_docs.py` checks the docs.
- The hook runs the app checks below (`scripts/check-<app>.sh`) at the
  same time, after the Python checks. Each output line of an app check
  starts with the name of the app, for example `[nextjs]`. At the end,
  the hook tells which app checks passed and which failed. To run them
  one after the other, push with `APPGEN_CHECK_SERIAL=1 git push`.
- When a push changes the generator core, the FastAPI binding, or the
  shared binding code, the hook also runs `scripts/check-fastapi.sh`. The script generates the
  project tracker with the FastAPI binding, and runs `uv sync`, Ruff,
  pyright, the generated tests, `docker build`, and `appgen check` on
  the output. It also starts two processes of the app with Redis, and
  checks that they share the rate limit, and it validates the
  deployment files of each target against their schemas (it downloads
  the schemas once). Then it generates the room booking example
  (sign-in, sign-up, roles, and a provider) and
  `tests/fixtures/provider-sign-in.yaml` (only providers), and runs
  Ruff, pyright, the generated tests, and `appgen check` on them. A
  browser signs in to both apps through the mock OpenID Connect provider
  `scripts/mock_oidc.py` (`scripts/check_provider_sign_in.py`). Then it
  generates `tests/fixtures/account-security.yaml` (the verification of
  the email address, and the second factor), and runs Ruff, pyright,
  the generated tests, and `appgen check` on it. Then it generates
  `tests/fixtures/seed-data.yaml` (seed records, ADR 0021), checks it in
  the same way, and runs its seed test on Postgres. Then it generates
  `tests/fixtures/record-rules.yaml` (the record rules with conditions
  and owner paths) and the other fixtures of the script header, for
  example `tests/fixtures/totals.yaml` (the totals of the relations)
  and `tests/fixtures/invoices.yaml` (sequence numbers, ADR 0037), and
  runs the same checks on them. It needs Docker.
  Run it by hand with
  `scripts/check-fastapi.sh [output folder]`. The script header lists
  the environment variables for other images (for example a mirror).
- When a push changes the generator core, the Next.js binding, or the
  shared binding code, the hook also runs `scripts/check-nextjs.sh`.
  The script generates the project tracker with the Next.js binding,
  and runs `pnpm install`, lint, type check, build, `docker build`, and
  `appgen check` on the output. Like the FastAPI check, it starts two
  processes of the app with Redis, and checks that they share the rate
  limit, and it validates the deployment files of each target against
  their schemas. Then it generates `tests/fixtures/seed-data.yaml` (seed
  records, ADR 0021), checks it in the same way without the build, and
  runs the seed two times with PGlite (`scripts/seed_test.py`). The
  script header lists the other fixtures that it checks, for example
  `tests/fixtures/invoices.yaml` with the sequence test
  (`scripts/sequence_test.py`), and `tests/fixtures/totals.yaml`, whose
  test reads the totals of the relations and checks the compare rules
  over totals with PGlite (`scripts/totals_test.py`). It needs pnpm and Docker. Run it by hand
  with `scripts/check-nextjs.sh [output folder]`.
- When a push changes the generator core, the React binding, or the
  shared binding code, the hook also runs `scripts/check-react.sh`. The
  script generates the project tracker with the React binding, and runs
  `pnpm install`, lint, type check, build, `docker build`, and
  `appgen check` on the output. Then it generates
  `tests/fixtures/seed-data.yaml`, and runs lint, type check, and
  `appgen check` on it. Then it does the same for
  `tests/fixtures/invoices.yaml`, and runs the sequence test of the mock
  store (`scripts/sequence_test.py --binding react`). Last, it does the
  same for `tests/fixtures/totals.yaml` (the totals and the lines
  editors). It needs pnpm and Docker. Run it by hand with
  `scripts/check-react.sh [output folder]`.
- When a push changes the generator core, a front-end binding, or the
  shared binding code, the hook also runs
  `scripts/check-translations.sh`. The script generates the project
  tracker with a test language that changes each text, and checks that
  the React and the Next.js apps show no text of the default language
  (`scripts/translation_test.py`). It needs pnpm, but not Docker. A
  fixed text in a template must use a text helper of
  `src/appgen/bindings/shared/i18n.py`, for example `jsx_text("Close")`,
  else the check fails. The test language is from right to left: the
  check fails when a page is wider than the window, and it compares one
  page of each kind with its approved screenshot in
  `ui-tests/approved/<binding>/rtl/<page>.png`, in the light mode. A
  template that uses a class of a side (for example `ml-2` in place of
  `ms-2`) fails a test of `tests/test_bindings_shared_sides.py`.
- When a push changes the generator core, a front-end binding, the
  FastAPI binding, the shared binding code, or the room booking example,
  the hook also runs `scripts/check-auth-ui.sh`. The script builds the room booking example
  with React and Next.js, signs in as a user of each role, and checks
  the menus, the pages, and the actions of the role. It also signs up
  a new user, resets a password (Next.js), checks that a user of a
  record rule sees only the records of the rule, and signs in with a
  provider through the mock provider of `scripts/mock_oidc.py`
  (`scripts/auth_ui_test.py`). The Next.js app sends the links of the
  sign-up and of the reset as emails to the mock SMTP server
  `scripts/mock_smtp.py`, and the test opens the links of the emails.
  It also builds `tests/fixtures/record-rules.yaml`, and checks its
  rules with conditions and owner paths. The binding `react-api` is the React app
  with the FastAPI app of the example: the script starts both, and signs
  in through the flow of the FastAPI app. Then it builds
  `tests/fixtures/api-connections.yaml` with React, Next.js, and
  react-api, connects an account of the calendar API at the mock OAuth
  server of `scripts/mock_api.py`, syncs a calendar, and disconnects
  the account on the page `/connections` (`scripts/connection_ui_test.py`).
  It needs uv and pnpm, but not Docker. Update its approved screenshots with
  `APPGEN_UPDATE_SCREENSHOTS=1 scripts/check-auth-ui.sh`.
- Each check script ends with the smoke test of its app
  (`scripts/smoke_test.py`): it starts the Docker image that the script
  built, and requests one page for each entity (Next.js and React) or
  the list endpoint of each entity (FastAPI). Run it for all apps with
  `uv run scripts/smoke_test.py`.
- The check scripts of the front ends also run the Playwright UI tests
  (`ui-tests/`, `scripts/smoke_test.py --ui`) in the light and the dark
  mode. They need the Chromium of Playwright (`pnpm --dir ui-tests exec
  playwright install chromium`). Without it, they use the Chromium of
  the environment at `/opt/pw-browsers/chromium` (cloud sessions have
  one). `PLAYWRIGHT_CHROMIUM_EXECUTABLE` selects another Chromium.
- The UI tests compare each page in each color mode with its approved
  screenshot in `ui-tests/approved/<binding>/<mode>/<page>.png`. A page
  fails when more than 0.1 % of its pixels differ. The tests turn off
  the animations and fix the date, the locale, and the time zone of the
  browser. The pages show the mock data (React) or the seed data
  (Next.js). On a failure, Playwright writes the expected, the actual,
  and the diff image to `ui-tests/test-results/<binding>/`.
- When a change to the UI is intended, update the approved screenshots
  and review the changed images in the pull request:

  ```sh
  APPGEN_UPDATE_SCREENSHOTS=1 scripts/check-nextjs.sh
  APPGEN_UPDATE_SCREENSHOTS=1 scripts/check-react.sh
  APPGEN_UPDATE_SCREENSHOTS=1 scripts/check-auth-ui.sh
  APPGEN_UPDATE_SCREENSHOTS=1 scripts/check-translations.sh
  git add ui-tests/approved
  ```

  Make the approved screenshots in a Claude Code cloud session (the
  Chromium at `/opt/pw-browsers/chromium`). Another Chromium or other
  fonts can give small differences.
- The hook checks the working tree. Push from a clean working tree, so
  that the hook checks the pushed code.
- To run all checks, push with `APPGEN_CHECK_ALL=1 git push`.
- Do not skip the hook with `git push --no-verify` for a pull request
  that is ready for review.
- When you add a part (for example a binding), add its checks and its
  path patterns to the hook.
- Claude Code sessions enable the hook with a SessionStart hook in
  `.claude/settings.json`. See [Cloud sessions](#cloud-sessions).

## Cloud sessions

Claude Code cloud sessions (the sandbox) need some setup for the
checks. The repository does this setup, so a new session needs no
manual steps.

- `scripts/sandbox-setup.sh` starts the Docker daemon, pulls
  `POSTGRES_IMAGE`, and builds the Node image
  `localhost/appgen-node:24-alpine` (`NODE_IMAGE`) if they do not
  exist. The Node image trusts the CA of the session proxy, so that
  `pnpm install` in `docker build` works. Its name must start with
  `localhost/`, else BuildKit pulls the image of the same name from
  Docker Hub. The script also sets `core.hooksPath`, so that the
  pre-push hook runs. The SessionStart hook
  `.claude/hooks/session-start.sh` runs the script, and each check
  script runs it again in cloud sessions. A session can start without
  a running daemon, or with stale PID files of an earlier daemon. The
  script removes the stale files and starts the daemon again. On a
  machine without `dockerd`, the script skips the Docker steps.
- Docker Hub gives status 429 and ghcr.io is blocked in the sandbox,
  so the checks use mirror images. `scripts/sandbox.env` gives these
  variables. The SessionStart hook loads the file into the session, and
  the pre-push hook loads it in cloud sessions. A variable that the
  environment settings already set keeps its value.

| Variable          | Value in the sandbox                                    |
| ----------------- | ------------------------------------------------------- |
| `POSTGRES_IMAGE`  | `mirror.gcr.io/library/postgres:18-alpine`              |
| `UV_IMAGE`        | `mirror.gcr.io/astral/uv:0.11`                          |
| `PYTHON_IMAGE`    | `mirror.gcr.io/library/python:3.14-slim`                |
| `NGINX_IMAGE`     | `mirror.gcr.io/nginxinc/nginx-unprivileged:1.29-alpine` |
| `NODE_IMAGE`      | `localhost/appgen-node:24-alpine`                       |
| `REDIS_IMAGE`     | `mirror.gcr.io/library/redis:8-alpine`                  |
| `UV_SYSTEM_CERTS` | `true`                                                  |

`UV_SYSTEM_CERTS` makes uv trust the system certificates, which hold
the CA of the session proxy. The file also removes `UV_NATIVE_TLS`,
because uv warns that it is deprecated. Do not set `UV_NATIVE_TLS` in
the environment settings.

To use the values in a shell that the hook did not prepare, run
`. scripts/sandbox.env`.

## AI-assisted work

- Mark AI-assisted commits with a `Co-Authored-By:` trailer.
- AI-assisted pull requests say so in the description.
- Do not put links to claude.ai anywhere in GitHub: commits, pull
  requests, issues, comments, or files.
- A person reviews and merges each pull request.

### GitHub calls in Claude Code sessions

The GitHub tools of a Claude Code session cannot create or close a
milestone, and the session blocks the GitHub GraphQL API, so `gh pr`
and `gh issue` do not work. Use `gh api` with the REST API instead.

The session adds a footer with a link to claude.ai to each pull request
body that `gh api` or the pull request tool of the session writes, and
to each issue body that `gh api` writes. The project does not permit
these links. The GitHub MCP tools `update_pull_request` and
`issue_write` keep the body as it is. So, write the body last with one
of these tools.

1. Write the body to a file, for example `pr.md`. End it with the plain
   footer `_Generated by Claude Code_`, without a link.
2. Open the pull request:

   ```sh
   gh api repos/ds411/app-generator/pulls -X POST \
     -f title="<type>(<scope>): <summary>" \
     -f head="<branch>" -f base=main -F body=@pr.md -q .number
   ```

3. Write the body again with the MCP tool `update_pull_request`
   (`owner`, `repo`, `pullNumber`, and `body` with the text of
   `pr.md`). Use the same steps to edit the body later. For an issue,
   use the MCP tool `issue_write` (method `update`).
4. Make sure that the body has no link to claude.ai:

   ```sh
   gh api repos/ds411/app-generator/pulls/<n> -q .body | grep -c 'https://claude\.ai'
   ```

   The command must give `0`.

Other REST calls:

```sh
# Read an issue or a pull request.
gh api repos/ds411/app-generator/issues/<n>
# List the open milestones with their numbers.
gh api repos/ds411/app-generator/milestones -q '.[] | "\(.number) \(.title)"'
# Close a milestone.
gh api repos/ds411/app-generator/milestones/<number> -X PATCH -f state=closed
```

To merge a pull request, use the MCP tool `merge_pull_request` with
`merge_method` `squash`. Give the squash commit message of the pull
request description: the first line in `commit_title`, and the rest in
`commit_message`. The tool adds no footer to the commit message.
