# Evaluation of the agent skill

This report records three tasks that an agent did with only the
installed skill of appgen (#260, milestone M15). It shows if the text of
the skill (`src/appgen/skills/appgen/`) gives an agent enough context to
write, change, and fill an app definition, and it lists the problems
that the runs showed and the fix of each problem.

## Contents

- [Summary](#summary)
- [Method](#method)
- [Run 1: a new app from a short text](#run-1-a-new-app-from-a-short-text)
- [Run 2: add a field and rename an entity](#run-2-add-a-field-and-rename-an-entity)
- [Run 3: fill two gaps](#run-3-fill-two-gaps)
- [Problems and fixes](#problems-and-fixes)
- [Runs after the fixes](#runs-after-the-fixes)
- [Limits](#limits)

## Summary

| Run | Task | Binding | Tries to a valid definition | `appgen check` at the end | App checks |
| --- | ---- | ------- | --------------------------: | ------------------------- | ---------- |
| 1 | Write a new definition from a short text, and generate it | `fastapi` | 1 | Passed: 0 invalid, 0 gaps, coverage 100 % | 86 tests pass |
| 2 | Add a field and rename an entity of the room-booking example | `fastapi` | 3 | Passed: 0 invalid, 0 gaps, 0 orphans | 141 tests pass |
| 3 | Fill two gaps of the project tracker | `nextjs` | 0 (no change) | Passed: 0 invalid, the 2 gaps closed, 6 other gaps open | lint, typecheck, and build pass |

Each of the three runs ended with a valid definition and no invalid
traces. No agent
edited a generated file: a second `appgen generate` into a copy of each
app folder wrote no file. The agents found the right reference file of
the task at the first try, and used `appgen validate`, `appgen check`,
and `appgen orphans` with `--format json` as the skill tells.

The runs showed five problems. Two of them made an agent guess or work
around the skill: the plural name of the CRUD list operation, and the
database for an Alembic migration. The fixes are in the same pull
request (see [Problems and fixes](#problems-and-fixes)). With the fixed
skill, task 2 got a valid definition at the first try, and task 3 did
not search for the list API (see [Runs after the fixes](#runs-after-the-fixes)).
A second run of task 2 also found a bug of the FastAPI binding, which
is not a problem of the skill.

## Method

- appgen 0.1.0 installed as a tool from the branch: `uv tool install .`.
  The first runs used the branch of #259, and the runs after the fixes
  used the branch of this report, with the fixes.
- The skill installed with `appgen skills install --scope user` into an
  empty home folder. The agent sessions had this home folder, so the
  appgen skill was the only skill of the user. `appgen skills list`
  showed the copies of both targets as `up to date`.
- Each run is a new session of Claude Code in print mode
  (`claude -p "<prompt>"`), with the default model and the permission
  mode `bypassPermissions`. The work folder of each run is outside of
  the repository, and the prompts do not name the repository. The logs
  of the sessions show that no agent read or ran a file of the
  repository. The generated apps of the runs are not in the repository.
- Before run 2 and run 3, the work folder got an app definition from
  `examples/` and an app that appgen generated from it. In run 2, the
  app also had hand-written code: the logic of `cancel_booking`, with a
  trace to `entities.Member.fields.email`.
- After each run, the evaluation checked the result again: `appgen validate`,
  `appgen check`, `appgen orphans`, and a second `appgen generate` into
  a copy of the app folder.

## Run 1: a new app from a short text

**Prompt:**

> Use appgen to make a small web app for a neighborhood tool library.
> Members borrow tools. A tool has a name, a category (garden, kitchen,
> or workshop), and a note about its condition. A loan has the member,
> the tool, the date of the loan, the due date, and the date of the
> return. A member can mark a loan as returned. Write the app definition
> in app.yaml, and generate a FastAPI app into ./app.

The agent loaded the skill, and read `references/new-definition.md`
and, for the gap, `references/fill-gaps.md`. It took 8 turns and about
1 minute.

**Commands:**

1. Write `app.yaml` with the entities `Member`, `Tool`, and `Loan`
   (`crud: true`, two `many_to_one` relations with `on_delete: restrict`,
   a `compare` rule for the due date), and the custom operation
   `mark_loan_returned`. Then, in one command:
   `appgen validate app.yaml --format json && appgen generate app.yaml -b fastapi -o app && appgen check app.yaml app --format json`.
2. Read the extension file and the generated file of the gap:
   `cat mark_loan_returned_ext.py mark_loan_returned_gen.py`, and
   `router.py` and `read_loan.py`.
3. Write the logic in `mark_loan_returned_ext.py` (a `ProblemError(409)`
   for a returned loan, else set `returned_on` to today), change the
   trace to `@trace:manual`, and run
   `appgen check app.yaml app --format json`,
   `uv sync`, `uv run ruff check`, `uv run pyright`, and `uv run pytest`.

**Tries to a valid definition:** 1. The first `appgen validate` gave no
diagnostics.

**`appgen check`:** after the generation, passed with one gap
(`operations.mark_loan_returned`). After the fill, passed with 0
invalid traces, 0 gaps, and coverage 100 % (the kinds `page`, `ui`, and
`translations` are out of the scope of `fastapi`). ruff and pyright
reported no errors, and the 86 tests of the app passed.

**Problems:** the summary of `appgen generate` said `Gaps created: 0`,
and listed the stub of the gap under "Extension files created". The
agent used the gaps of `appgen check`, as the skill tells, so the
summary did not mislead it (problem 5).

## Run 2: add a field and rename an entity

**Prompt:**

> The folder ./app is a FastAPI app that appgen generated from
> app.yaml. It has hand-written code. Change the app: add an optional
> phone number to the members, and rename the entity Member to Person.
> Keep the hand-written code working.

The agent loaded the skill and read `references/change-definition.md`.
It took 14 turns and about 1.5 minutes.

**Commands:**

1. Read the folder and the definition, and the report:
   `appgen check app.yaml app --format json`.
2. Find the hand-written code: `grep -rl "Created by appgen once" .`
   and `grep -rn "@trace:manual" .`, and read the extension files.
3. Change the definition with a script: the entity key `Member` to
   `Person`, each `target`, `entity`, and `user_entity`, and the new
   field `phone: { type: string, max_length: 30 }`. Then
   `appgen validate app.yaml -f json`.
4. Change the references that `validate` reported. The hints gave the
   new names, except for `list_members`: its hint was `list_amenities`,
   and the agent wrote `list_people`. Then
   `appgen validate app.yaml -f json`.
5. Change `list_people` to `list_persons`, the name of the hint, and
   validate again. Then `appgen generate app.yaml -b fastapi -o app`:
   19 generated files deleted, 1 extension file created
   (`app/features/persons/validation_ext.py`), and 1 orphan
   (`app/features/members/validation_ext.py`, a stub without code).
6. Delete the folder `app/features/members`, and change the import,
   the model, and the trace of `cancel_booking_ext.py` to `Person` and
   `entities.Person.fields.email`.
7. Read `migrations/versions/0001_schema.py` and the new models. Write
   the migration `0002_rename_member_to_person.py` by hand: rename the
   table and the constraints, add the column `phone`, and the
   downgrade.
8. `appgen check app.yaml app -f json`, `appgen orphans app.yaml app -f json`,
   a search for the old name, and `uv run pytest`.

**Tries to a valid definition:** 3. The first `validate` gave 5
`unknown-reference` diagnostics (`member_table`, `new_member`,
`member_detail`, `list_members`, and `read_member`). Four of them had
the new name as the hint. The second gave 1: the agent wrote
`list_people`, and the CRUD shorthand names the operation
`list_persons`. The third gave no diagnostics.

**`appgen check`:** passed with 0 invalid traces, 0 gaps, and no
orphans. The agent changed the trace of the hand-written code before it
generated the app, so the check never reported the old ID. The 141
tests of the app passed, also `tests/test_migrations.py`, which
compares the migrations with the models and runs them down and up.

**Problems:**

- The agent guessed the plural of `Person` (problem 1).
- The agent did not run `alembic revision --autogenerate`, because it
  needs a database, and the skill did not tell how to get one. It wrote
  the migration by hand (problem 2).
- Step 5 of the reference told the agent to read "the gaps created" in
  the summary, which counts only part of the gaps (problem 5).

## Run 3: fill two gaps

**Prompt:**

> The folder ./app is a Next.js app that appgen generated from
> app.yaml. Fill two gaps of the app: the operation complete_task, and
> the dashboard widget workload, which shows the number of open tasks
> of each person. Then run the tests of the app.

The app was the project tracker with the binding `nextjs`, with 8 open
gaps. The agent loaded the skill and read `references/fill-gaps.md`. It
took 13 turns and about 1.5 minutes.

**Commands:**

1. Read the definition and the report:
   `appgen check app.yaml app --format json`.
2. Read the elements `complete_task` and `workload` in the definition,
   and the two extension files.
3. Read 6 generated files to find the data API of the front end:
   `src/entities/task/server.ts`, `task-api.ts`, the types of the
   entity, `src/shared/lib/use-resource.ts`, the list types in
   `src/shared/api/`, and the generated dashboard
   `overview-dashboard.tsx` (problem 3).
4. Write `complete-task.ext.ts` (with `taskRepository.update` of
   `@/entities/task/server`) and `workload-widget.ext.tsx` (with
   `personApi.list()`, `taskApi.list()`, `subscribe`, and
   `useResource`), and change both traces to `@trace:manual`.
5. `appgen check app.yaml app --format json`, `pnpm install`,
   `pnpm lint`, `pnpm typecheck`, a search for a test script in
   `package.json`, and `pnpm build`.

**Tries to a valid definition:** 0. The task did not change the
definition.

**`appgen check`:** passed with 0 invalid traces and 0 gaps to close.
The two gaps of the task are closed, and the 6 other gaps stay open.
lint, typecheck, and build passed.

**Problems:**

- The agent read 6 generated files to learn how to load data in a
  component (problem 3).
- The prompt asked for the tests, and the app has no test script. The
  skill gave the right commands, but did not say that the app has no
  unit tests (problem 4).

## Problems and fixes

| # | Problem | Run | Fix |
| - | ------- | --- | --- |
| 1 | The skill did not give the plural rule of the CRUD list operation. The agent wrote `list_people` for `Person`, and the shorthand gives `list_persons`. | 2 | `new-definition.md` gives the rule (add `s`, `es`, or `ies`; no irregular plurals) and `plural_label`. The rename section of `change-definition.md` lists the names that the shorthand gives, and tells to use the name of the hint. |
| 2 | `change-definition.md` told to run `alembic revision --autogenerate`, but not how to get the database that it compares the models with. The agent wrote the migration by hand. | 2 | The database section tells to make a SQLite database with the migrations before the change, and then to run autogenerate. On the app of run 2, these commands gave a migration with the removed table `members` and the added table `persons`. The section also tells to rename the constraints after the rename of a table. |
| 3 | `fill-gaps.md` did not give the data API of the front ends, so the agent read 6 generated files. | 3 | The Next.js and React sections give `list()` without `page` (all records), the result `{ items, total }`, `subscribe`, the result of `useResource`, the generated dashboard as an example, and the components of the view states (`ViewLoading` with its required properties, `ViewMessage`, and `RetryButton`). |
| 4 | The skill did not say that the front ends have no unit tests. | 3 | The test line of each front end says it. |
| 5 | The summary of `appgen generate` counts as "Gaps created" only the elements that a binding cannot generate. The stubs of the custom elements are in "Extension files created". Step 5 of `change-definition.md` told to read the gaps in the summary. | 1, 2 | The step tells to read the extension files in the summary, and the open gaps in `appgen check`. `SKILL.md` says the same. The count of the summary is a problem of the CLI, not of the skill: see [Limits](#limits). |

## Runs after the fixes

The skill with the fixes was installed again into the home folder of
the runs (`appgen skills install --scope user` updated the 6 files).
Then tasks 2 and 3 ran again in new sessions, with the same prompts and
new work folders. The prompts and the logs were outside the work
folders.

| Run | Task | Tries to a valid definition | `appgen check` at the end | App checks |
| --- | ---- | --------------------------: | ------------------------- | ---------- |
| 2b | Task 2 on the definition of run 2 | 1 | Not passed: the app was not generated again (see below) | Not run |
| 2c | Task 2 on the room-booking example of main after #288, with `auth.sign_up` | 1 | Passed: 0 invalid, 0 gaps, 0 orphans | 144 tests pass |
| 3b | Task 3 | 0 (no change) | Passed: 0 invalid, the 2 gaps closed | lint, typecheck, and build pass |

**Run 2b** (16 turns, about 1 minute) used the definition of run 2,
from the room-booking example before #288. The agent changed the names
from the table of the reference, also `list_members` to `list_persons`,
and the first `appgen validate` gave no diagnostics (problem 1 fixed).
Then `appgen generate` stopped with `The template 'tests/test_auth.py.j2'
needs a missing value: 'default_role' is undefined`. The agent found the
cause in the template of the installed package: since #288, the
FastAPI binding cannot generate a definition that has `access` and no
`auth.sign_up`. The agent changed no file of the app, and reported the
bug. The bug is in the binding, not in the skill. #293 fixed it: the
definition of run 2b generates on main now.

**Run 2c** (12 turns, about 1.5 minutes) used the room-booking example
of main after #288, which has `auth.sign_up`, with the same hand-written
code as run 2. The first `appgen validate` gave no diagnostics. After the
generation, the check reported 2 invalid traces, each with the new ID
as the hint: the trace to `entities.Member.fields.email` in
`cancel_booking_ext.py`, and the header of the old
`members/validation_ext.py`. The agent changed the first, and deleted
the second (a stub without code). For the migration, it made the SQLite
database and ran `uv run alembic upgrade head`, as the fixed reference
tells (problem 2 fixed). Then it did not run autogenerate: it wrote
the rename migration by hand, with the `op.rename_table` and the
constraint renames of step 3. The 144 tests of the app passed, also the
migration tests.

**Run 3b** (14 turns, about 2 minutes) did not search for the list
types, and said that the app has no unit tests and no `test` script
(problems 3 and 4 fixed). The agent still read other generated files:
the repository of the task, the widget card, and the components of the
view states. It used `<ViewLoading shape="widget" />`, and
`pnpm typecheck` reported the missing required property `indicator`.
The agent fixed it in one step. After this run, `fill-gaps.md` also
names the components of the view states, with an example that gives
the required properties (problem 3).

The tests of the skill check each fix against the code: the plurals and
the CRUD names of the references against the CRUD shorthand, the SQLite
command against the README of the generated FastAPI app, the summary of
`appgen generate`, the data API and the view states against the
generated front ends, and the missing `test` script.

## Limits

- Task 1 ran once, task 2 three times, and task 3 two times, with one
  model. Another model, or another run, can make other mistakes.
- In the first three runs, the work folders also had the prompt file and
  the log of the session. The agents of run 2 and run 3 listed them,
  and the agent of run 2 read the prompt file. The files have no text
  of the skill or of the repository. The later runs had no such files.
- The runs used the FastAPI and Next.js apps. The React binding has the
  same front-end API as the Next.js binding, and the same extension
  files.
- In the runs, the summary of `appgen generate` showed `Gaps created: 0`
  for the custom operations of all bindings. #310 fixed the CLI after
  the runs: the summary lists each element of a `@trace:gap` trace in an
  extension file that the run created, with its file.
