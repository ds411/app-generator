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
- [AI-assisted work](#ai-assisted-work)

## Workflow

1. Pick an open story from the current milestone.
2. Assign the story to yourself.
3. Make a branch from `main`.
4. Make commits that follow the commit format.
5. Open a pull request that closes the story.
6. Merge the pull request with "Squash and merge" when the checks pass
   and the review is complete.

## Planning

We plan with GitHub milestones and issues.

- A **milestone** is a deliverable increment with a goal, a scope, and
  exit criteria. Use [the milestone template](.github/MILESTONE_TEMPLATE.md).
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
- Link each story that the pull request completes with `Closes #<n>`.
- Keep one story in one pull request where possible.
- Open the pull request as a draft until it is ready for review.
- Merge with "Squash and merge" only after the checks pass and the
  review is complete.

## Definition of done

A story is done when all these conditions are true:

- All acceptance criteria are true.
- Tests for the change exist and pass in CI.
- Lint and type checks pass.
- For changes to the generator or a binding:
  - A second generation run gives the same output (no diff).
  - The generated example apps build.
  - The trace check reports no invalid traces.
- The docs agree with the change.
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

## AI-assisted work

- Mark AI-assisted commits with a `Co-Authored-By:` trailer.
- AI-assisted pull requests say so in the description.
- Do not put links to claude.ai anywhere in GitHub: commits, pull
  requests, issues, comments, or files.
- A person reviews and merges each pull request.
