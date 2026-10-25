---
name: appgen
description: "Use the appgen CLI to generate apps from a YAML app definition. Five tasks: (1) use the CLI loop: appgen validate, appgen generate with a binding (nextjs, react, or fastapi), and appgen check of the traces; (2) write a new app definition from a description of an app; (3) change the app definition of an app that exists, and keep its hand-written code and its traces valid; (4) fill the generation gaps of a generated app: the extension files with TODO(appgen) stubs and @trace:gap comments; (5) add seed records to a definition: the data that the apps start with, from a table, a CSV file, or a JSON export. Use this skill when a task names appgen, an app definition (a YAML file with version: 0, app, and entities), a folder with .appgen/manifest.json, @trace comments, or TODO(appgen) stubs."
---

# appgen

appgen generates the code of an app from one YAML file, the **app
definition**. The definition describes the entities, the operations, the
pages, and the UI of the app. `appgen generate` writes the code for a
**binding** (a target stack). Comments in the code, the **traces**, refer
to the elements of the definition, for example
`// @trace entities.Task.fields.title`. `appgen check` reads the traces,
and reports the invalid traces, the uncovered elements, and the open
**generation gaps**: the places where a person or an agent must write
code by hand.

## Tasks

| Task                                         | Read                                                               |
| -------------------------------------------- | ------------------------------------------------------------------ |
| Validate a definition, generate, and check.  | This file.                                                         |
| Write a new app definition.                  | [references/new-definition.md](references/new-definition.md)       |
| Change the definition of an app that exists. | [references/change-definition.md](references/change-definition.md) |
| Fill the generation gaps of an app.          | [references/fill-gaps.md](references/fill-gaps.md)                 |
| Add seed records (data) to a definition.     | [references/seed-data.md](references/seed-data.md)                 |

Each task uses the CLI loop of this file. Read the file of your task
before you start it. Two more files help in all tasks:

- [references/dsl.md](references/dsl.md): the reference of the DSL, with
  an example for each section. Read the section that you need, not the
  whole file.
- [references/diagnostics.md](references/diagnostics.md): the cause and
  the fix of each diagnostic code of `appgen validate` and `appgen check`.

## Run appgen

- An installed appgen: `appgen <command>`.
- In a clone of the appgen repository: `uv run appgen <command>`.
- `appgen --version` gives the version. `appgen --help` lists the
  commands, and `appgen <command> --help` gives the options of a
  command.

## Commands

| Command                                         | Use                                                    | Exit code |
| ----------------------------------------------- | ------------------------------------------------------ | --------- |
| `appgen validate <file> --format json`          | Check a definition. Writes no file.                    | 0 valid, 1 not valid |
| `appgen generate <file> -b <binding> -o <dir>`  | Validate, then write the app into a folder.            | 0 written, 1 not written |
| `appgen check <file> <dir> --format json`       | Check the traces of an app against the definition.     | 0 passed, 1 failed, 2 definition or manifest not valid |
| `appgen orphans <file> <dir> --format json`     | List the extension files whose element is gone.        | 0, or 2 as for `check` |
| `appgen schema`                                 | Write the JSON Schema of the DSL to stdout.            | 0 |

Use `--format json` (or `-f json`) with `validate`, `check`, and
`orphans`, and read the JSON. The text output is for people.

More options:

- `appgen validate <file> --binding <name>` checks the extension keys
  (`x-...`) of one binding only. Repeat `--binding` for more bindings.
  Without it, the command checks the keys of all bindings.
- `appgen generate <file> -b <binding> -o <dir> --force` overwrites
  generated files with manual edits. Do not use `--force` before you
  read [Generated files and extension files](#generated-files-and-extension-files).
- `appgen check <file> <dir> --min-coverage <percent>` fails if the
  coverage is lower. `--exclude-kind <kind>` leaves the elements of a
  kind out of the coverage. `--ignore <pattern>` skips more paths
  (gitignore syntax), and `--no-gitignore` also scans the paths in
  `.gitignore` files. Repeat `--exclude-kind` and `--ignore` for more
  values.
- `appgen schema --out <file>` writes the JSON Schema to a file.

## Install the skill

`appgen skills` copies this skill into the folders that agents read, at
the version of the installed appgen:

| Command                            | Use                                                              |
| ---------------------------------- | ---------------------------------------------------------------- |
| `appgen skills install`            | Write the skill to `./.agents/skills/` and `./.claude/skills/`.  |
| `appgen skills list --format json` | Show each target and scope with the installed version and the status (`up to date`, `out of date`, `changed`, or `not installed`). |
| `appgen skills uninstall`          | Remove the files that appgen installed.                          |

The options of `install` and `uninstall`:

- `--target claude` (Claude Code, `.claude/skills/`) or `--target agents`
  (Codex and other agents, `.agents/skills/`). Repeat it for both.
  Default: both.
- `--scope project` (the folder of `--project-dir <folder>`, or the
  current folder), `--scope user` (the home folder), or `--scope system`
  (a system folder, which needs root). Default: `project`.
- `--path <folder>`: another skills folder, instead of `--target` and
  `--scope`. `appgen skills list --path <folder>` shows it too.
- `--dry-run`: show the changes, and write no file.
- `--force`: also overwrite or remove the files that a person changed.
  Without it, the command names these files and stops.

After an update of appgen, run `appgen skills install` again. A second
install of the same version changes no file.

## Bindings

| Binding   | App                                                         | Tools          |
| --------- | ----------------------------------------------------------- | -------------- |
| `nextjs`  | A full-stack Next.js 16 app (TypeScript, shadcn/ui, Drizzle, Postgres). | pnpm, Docker |
| `react`   | A React 19 front end (TypeScript, shadcn/ui) with mock data. | pnpm, Docker  |
| `fastapi` | A FastAPI REST API (Python 3.14, SQLAlchemy, Alembic).      | uv, Docker     |
| `minimal` | The test binding of appgen. Do not use it for an app.       |                |

The back end (`fastapi`) ignores the `pages` and `ui` sections. Each
generated app has a README with its commands, and a Dockerfile.

## The CLI loop

Do these steps for each change to a definition:

1. Validate: `appgen validate app.yaml --format json`.
2. If `valid` is `false`, fix each entry of `diagnostics` at its
   `file`, `line`, and `column`. Use its `hint` if it has one. Then
   validate again. Fix all diagnostics before you generate.
3. Generate: `appgen generate app.yaml -b <binding> -o <dir>`. Use the
   same folder for each run of the same app. A new run keeps the
   hand-written code.
4. Check: `appgen check app.yaml <dir> --format json`.
5. If `passed` is `false`, fix each entry of `invalid`. Then check
   again.
6. Read `gaps`: each entry is an element that needs hand-written code,
   and `traces` gives its files. Use this list, not the summary of
   `appgen generate`: its line `Gaps created` lists only the gaps of the
   extension files that the run created, and not the open gaps of
   earlier runs.
7. Build and test the app with the commands of its README.

### The JSON of `appgen validate`

<!-- appgen validate -->
```json
{
  "file": "app.yaml",
  "valid": false,
  "diagnostics": [
    {
      "code": "unknown-reference",
      "message": "The entity 'Project' does not exist.",
      "file": "app.yaml",
      "line": 8,
      "column": 45,
      "element_id": "entities.Task.relations.project",
      "hint": null
    }
  ]
}
```

`code` is a stable name of the kind of error. `element_id` is the
element with the error, if it is known.

### The JSON of `appgen check`

A shortened report:

<!-- appgen check -->
```json
{
  "version": 1,
  "passed": true,
  "files": 124,
  "traces": 375,
  "invalid": [],
  "warnings": [],
  "uncovered": [],
  "gaps": [
    {
      "id": "operations.cancel_booking",
      "kind": "operation",
      "traces": [{ "file": "app/features/bookings/cancel_booking_ext.py", "line": 2 }]
    }
  ],
  "gaps_to_close": [],
  "coverage": {
    "percent": 98.31,
    "total": 59,
    "covered": 58,
    "gaps": 1,
    "uncovered": 0,
    "min_percent": null,
    "excluded_kinds": ["page", "ui"],
    "by_kind": [
      { "kind": "operation", "percent": 85.71, "total": 7, "covered": 6, "gaps": 1, "uncovered": 0 }
    ]
  }
}
```

- `invalid`: the traces that fail the check. Each entry has `file`,
  `line`, `column`, `code`, `message`, `text` (the trace), `element_id`,
  and `hint`. The code `unknown-element` is a trace to an element that
  the definition does not have, for example after a rename. Its `hint`
  gives the most likely new element.
- `warnings`: `@trace` text that the scan does not read, because it is
  not in a comment. A warning does not fail the check.
- `uncovered`: the elements without a trace (`id` and `kind`). An
  uncovered element does not fail the check.
- `gaps`: the open generation gaps.
- `gaps_to_close`: the gap files without stub markers. Change their
  `@trace:gap` trace to `@trace:manual`.
- `coverage`: the counts, and the percentage of covered elements.
  `by_kind` gives them for each kind of element. `excluded_kinds` are
  the kinds that the coverage leaves out: the kinds of
  `--exclude-kind`, and the kinds that the binding does not generate.
  `min_percent` is the value of `--min-coverage`, or `null`.

## Element IDs

Each element of a definition has an ID: the mapping keys from the root
to the element, with dots, for example `entities.Task`,
`entities.Task.fields.title`, `operations.complete_task`, or
`pages.task_board`. The traces use these IDs. A rename of an element
changes its ID and the IDs of the elements under it, so choose stable
names, and rename only when the task asks for it.

## Generated files and extension files

appgen writes two kinds of files:

- A **generated file** starts with
  `Generated by appgen. Do not edit: change the app definition instead.`
  Each run writes it again. Do not edit it: change the definition, and
  generate again.
- An **extension file** starts with
  `Created by appgen once. appgen never changes or deletes this file.`
  It holds hand-written code. The extension file of a gap has a stub
  with a `TODO(appgen):` comment, and a `@trace:gap` trace in its
  header.

`.appgen/manifest.json` in the app folder lists the generated files with
their hashes. If a generated file has manual edits, `appgen generate`
stops, names the file, and writes nothing. Then move the edit to an
extension file or to the definition, and generate again. Use `--force`
only to drop the edits.

## When to use `appgen orphans`

After a rename or a removal of an element, `appgen generate` keeps the
extension files of the old element. `appgen orphans app.yaml <dir>
--format json` lists them. For each file, `suggestion` is the element
that most likely replaces the old element, or `null`. Move the
hand-written code to the extension file of the new element, change its
traces to the new ID, and delete the old file. The command changes no
file. It needs the manifest of a run of `appgen generate`.

## When to use `appgen schema`

`appgen schema` gives the JSON Schema of the DSL: all sections, keys,
and values. Use it to look up the exact keys and values of a section.
Put this line at the top of a definition, so that an editor with a YAML
language server completes and checks it:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json
```

## Rules

- Validate before you generate. `appgen generate` writes no file for a
  definition that is not valid.
- Write hand-written code only in extension files. Change the
  definition, not a generated file.
- Keep each trace in a comment on its own line, for example
  `// @trace:manual operations.complete_task` or
  `# @trace:manual operations.complete_task`.
- End each task with `appgen check app.yaml <dir> --format json`, and
  make sure that `invalid` is empty.
