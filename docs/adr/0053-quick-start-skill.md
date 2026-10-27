# 0053. A quick-start skill that picks the defaults of an app

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

The `appgen` skill (ADR 0015) tells an agent how to use the CLI, and how
to write, change, and fill an app definition. It does not choose the
options of an app: the binding, the sign-in, the roles, the languages,
the seed records, or the APIs. An agent that gets a short prompt, for
example "Make an app for a neighborhood tool library", must ask the
user or guess. The questions slow down a first app, and the guesses can
differ between two runs of the same prompt.

We looked at these options:

- **A table of defaults in the `appgen` skill.** The agent loads the
  table in each task, also when it fills a gap or changes a field. The
  `description` of the skill must then trigger on a request for a whole
  app too, and the skill gets longer for all tasks.
- **A second skill with only the defaults and the order of the work.**
  It uses the `appgen` skill for the CLI, the DSL, and the gaps. Each
  skill stays short, and the text of the CLI and the DSL is in one place.
- **A second skill that repeats the CLI and the DSL.** It works without
  the `appgen` skill, but the two skills can disagree.
- **A dialog that asks the user about each option.** It gives the right
  options, but it needs many answers before the first app.

## Decision

We ship a second skill, `appgen-quickstart`, in the package:
`src/appgen/skills/appgen-quickstart/`.

- `SKILL.md` has the table of defaults: for each default, the signal in
  the prompts, and the bindings or the keys of the definition that it
  gives. It also gives the order of the work, the record of the chosen
  defaults, the summary at the end, and the rules for a later prompt.
- The skill does not describe the CLI, the DSL, or the gaps. It tells
  the agent to load the `appgen` skill (`/appgen` in Claude Code, or
  `../appgen/SKILL.md`), and links to its reference files. So the
  link works only when both skills are in the same skills folder.
  `appgen skills install` installs all skills of the package together,
  and a test keeps each link of the skill in the skill or in
  `../appgen/`.
- The agent asks no question about a default. It asks only when the
  prompts conflict. When the app needs a file that the agent cannot
  make, for example the OpenAPI document of an API, the agent makes the
  app without that part, and names the part in its summary.
- The agent writes the chosen defaults as comments at the top of
  `app.yaml`, each with the words of the prompt that caused it. Thus a
  person sees why the app has a part, and a later prompt or a later
  session changes the right default.
- The folder of each binding is `./<binding>/`, for example
  `./nextjs/`. A later prompt that changes the bindings generates the
  new binding into a new folder, and keeps the folder of the old one.
- Tests keep the table in agreement with the code: each key and each
  value of the table exists in the JSON Schema of the DSL or in the
  extension keys of a binding, and each binding of the table is in the
  registry of the bindings. Each section of the DSL has a row, or is on
  a short list of sections without a default, with the reason. Each
  YAML example of the skill validates.
- `appgen skills install`, `list`, and `uninstall` handle each skill of
  the package, so they need no change.

## Consequences

- A short prompt gives the same kind of app in each run, and the agent
  asks no questions. The defaults are visible in `app.yaml`, and a
  later prompt changes them.
- A change of the DSL that removes or renames a key of the table fails
  the tests until the skill agrees. A new section of the DSL fails them
  too, until a person gives it a row or puts it on the list of sections
  without a default.
- The defaults are a choice of this project, for example `nextjs` for a
  web app. Some users want other defaults. They name the stack or the
  option in the prompt, and the prompt wins.
- The tests check the names, not the choice. An evaluation with agent
  tasks shows if the agents pick the defaults of the table
  (`scripts/evaluate_skill.py`, `docs/evaluation-skills.md`).
