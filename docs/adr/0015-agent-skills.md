# 0015. Agent skills

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

App authors and app developers work more and more with AI agents, for
example Claude Code and Codex. An agent that does not know appgen tries
the commands, reads the help, and guesses the DSL. It makes avoidable
errors: it edits generated files, forgets to change a `gap` trace to
`manual`, or renames an element and loses the hand-written code of the
element.

Claude Code, Codex, and other agents read skills in the Agent Skills
format: a folder with a `SKILL.md` file (YAML front matter with `name`
and `description`, then the instructions) and optional reference files.
An agent loads the `description` of each skill at the start of a
session, and the rest of the skill only when a task needs it.

An agent needs four abilities with appgen: use the CLI, write a new app
definition, change an app definition, and fill the generation gaps. We
looked at these options:

- **One skill for each task.** Each skill is small, but the skills
  repeat the CLI and the DSL, and the installed skills can come from
  different versions of appgen.
- **One skill with one reference file for each task.** `SKILL.md` gives
  the CLI loop, and the agent reads only the reference file of its task.
- **An MCP server.** Agents without a shell can use it, but it is one
  more interface to keep in agreement with the CLI, and its tool
  definitions are in the context of each session. The backlog keeps
  this option (M14).

A skill that does not agree with the CLI or the DSL is worse than no
skill: the agent trusts it and runs commands that fail.

## Decision

We ship one skill, `appgen`, in the package: `src/appgen/skills/appgen/`.

- `SKILL.md` describes the commands, the CLI loop (validate, fix the
  diagnostics, generate, check), the JSON reports, the element IDs, and
  the rules for generated files and extension files. It names the
  reference file of each task.
- `references/` has one file for each task (a new definition, a change
  to a definition, and generation gaps), and the reference of the DSL
  and of the diagnostic codes. The skill uses `--format json` wherever
  the CLI has it. `references/dsl.md` is a copy of `docs/dsl.md` that a
  script makes: it changes the links to other files of the repository
  into links to GitHub, because the installed skill has only its own
  files.
- The skill files are package data. `appgen.skills` reads them with
  `importlib.resources`, so that they are available after
  `uv tool install`.
- `appgen skills install` copies the skill into the folders that the
  agents read: `.claude/skills/` (Claude Code) and `.agents/skills/`
  (Codex and other agents), in a project, in the home folder, or in a
  system folder. A file in each installed copy (`.appgen-skill.json`)
  records the appgen version and the hash of each file, as the output manifest of the
  generator does (ADR 0005).
- Tests keep the skill in agreement with the code. A test fails if the
  skill names a command or an option that the CLI does not have, or if
  `SKILL.md` leaves out a command or an option of the CLI. Other tests
  check the front matter, the links, the DSL reference, the diagnostic
  codes, and the kinds of extension files.
- Tests also check the statements of the skill against the CLI. They run
  the command of each JSON example on a fixture, and compare the keys
  and the types of the values. A comment before the block, for example
  `<!-- appgen check -->`, names the command. They run each case of the
  table of commands, and compare the exit codes. They compare each
  default of an option (`Default: <value>.`) with the default of the
  CLI. A wrong statement fails with the file and the line of the text.

## Consequences

- An agent gets the workflow of appgen from one place, at the version of
  the installed appgen.
- A change to the CLI or the DSL must also change the skill. The
  definition of done and the pull request template say so, and the tests
  fail until the skill agrees.
- The skill is text for agents, not a contract. The tests find a missing
  or an unknown name, a wrong JSON example, a wrong exit code, and a
  wrong default, but not a wrong description in the prose. An evaluation
  with agent tasks shows if the text is enough.
- Agents without a shell cannot use the skill. An MCP server can cover
  them later, with the reference files as its resources.
