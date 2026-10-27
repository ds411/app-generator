# Evaluation of the agent skills

This report records the tasks that agents did with only the installed
skills of appgen. It shows if the text of the skill `appgen`
(`src/appgen/skills/appgen/`) gives an agent enough context to write,
change, and fill an app definition, and if the quick-start skill
(`src/appgen/skills/appgen-quickstart/`) makes the same app from the
same prompts. It lists the problems that the runs showed and the fix of
each problem.

The first part records the manual runs of three tasks (#260, milestone
M15). The second part records three runs of each task with two models,
and a fourth task, with the script `scripts/evaluate_skill.py` (#319,
milestone M22): see [Repeated runs with the script](#repeated-runs-with-the-script).
The third part records the tasks of the quick-start skill (#489,
milestone M39): see [Runs of the quick-start skill](#runs-of-the-quick-start-skill).

## Contents

- [Summary](#summary)
- [Method](#method)
- [Run 1: a new app from a short text](#run-1-a-new-app-from-a-short-text)
- [Run 2: add a field and rename an entity](#run-2-add-a-field-and-rename-an-entity)
- [Run 3: fill two gaps](#run-3-fill-two-gaps)
- [Problems and fixes](#problems-and-fixes)
- [Runs after the fixes](#runs-after-the-fixes)
- [Repeated runs with the script](#repeated-runs-with-the-script)
- [Runs of the quick-start skill](#runs-of-the-quick-start-skill)
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

## Repeated runs with the script

The runs of the first part were manual, and each task ran one to three
times with one model. `scripts/evaluate_skill.py` (#319) prepares,
runs, and scores the tasks, so that a task can run more times and with
other models, and the results compare.

### Method of the script

- `prepare <task> <folder>` copies the example of the task without its
  extension files, generates the app, and adds the files of the task,
  for example the hand-written code of `cancel_booking` for
  `change-definition`. It installs the skill into an empty home folder
  (`appgen skills install --scope user`). The prompts of the tasks are in
  [evaluation/skill-tasks/](evaluation/skill-tasks/): the first three
  are the prompts of the first part.
- `run <folder> --model <model>` starts Claude Code in print mode
  (`claude -p`) in the work folder, with the empty home folder and the
  permission mode `bypassPermissions`. The work folder has only the
  definition, the app, and the files of the task. The script writes the
  session (`log.jsonl`) and its summary (`run.json`) outside the work
  folder.
- `score <folder>` writes `score.json`. The run passes when the
  definition is valid, `appgen check` reports no invalid traces, the
  gaps of the task are closed, a new `appgen generate` into a copy of
  the app writes no file (no manual edits, and the app is generated
  from the last definition), the tests of the app pass,
  and the checks of the task pass (for example, no entity `Member` and
  a field `phone` of `Person`). The FastAPI tests ran on SQLite
  (`TEST_DATABASE_URL`), because the machine of the runs had no Docker.
- `report <folder>...` prints the table of the runs below.
- `tests/test_evaluate_skill.py` runs `prepare` and `score` on each
  task, before and after a solution that the test writes. No test and
  no hook runs an agent, because the runs cost money.

All runs were on 2026-10-25, with appgen 0.1.0 (installed as a tool
from the branch of #319), Claude Code 2.1.310, and the models
`claude-sonnet-5-5` and `claude-opus-5-5`. The first runs of
`new-definition`, `change-definition`, and `fill-gaps` used main at
`e51f88a` with the script. The first runs of `seed-csv` used main at
`1c9d234` (after #316) with the script and the fixes of the first runs.
The runs after the fixes used main at `b8f0ea0` or `1c9d234` with the
script and the fixes. The work folders and the logs of the runs are
not in the repository.

### Results

| Task | Model | Passed | Turns | Time (s) | Cost (USD) |
| ---- | ----- | -----: | ----: | -------: | ---------: |
| `new-definition` | `claude-sonnet-5-5` | 1 of 3 | 7 to 9 | 49 to 52 | 0.14 to 0.15 |
| `new-definition` | `claude-opus-5-5` | 3 of 3 | 11 to 16 | 58 to 81 | 0.40 to 0.51 |
| `change-definition` | `claude-sonnet-5-5` | 2 of 3 | 16 to 17 | 106 to 153 | 0.21 to 0.24 |
| `change-definition` | `claude-opus-5-5` | 3 of 3 | 21 to 25 | 176 to 221 | 0.63 to 0.88 |
| `fill-gaps` | `claude-sonnet-5-5` | 3 of 3 | 11 to 12 | 99 to 109 | 0.17 to 0.18 |
| `fill-gaps` | `claude-opus-5-5` | 3 of 3 | 15 to 18 | 95 to 137 | 0.46 to 0.52 |
| `seed-csv` | `claude-sonnet-5-5` | 3 of 3 | 6 to 7 | 14 to 15 | 0.10 |
| `seed-csv` | `claude-opus-5-5` | 3 of 3 | 8 to 10 | 54 to 70 | 0.25 to 0.29 |

In all 24 runs, the definition was valid, `appgen check` reported no
invalid traces, the gaps of the task were closed, and no agent edited a
generated file. Each failed run failed only the tests of the app. Of the
18 runs that changed the definition, 17 got a valid definition at the
first `appgen validate`. In the other run (`change-definition`,
`claude-opus-5-5`, run 1), the agent wrote `type: phone`. The diagnostic
`invalid-value` listed the field types, and the agent changed the field
to a `string` with a `pattern`.

`claude-opus-5-5` took more turns and about three times the cost, and
passed all 12 runs. `claude-sonnet-5-5` was faster, and passed 9 of 12.

Each run, from the output of `report`:

| Run | Task | Model | Turns | Time (s) | Cost (USD) | `validate` runs | Valid | No invalid traces | Gaps closed | No manual edits | App tests | Task checks | Passed |
| --- | ---- | ----- | ----: | -------: | ---------: | --------------: | ----- | ----------------- | ----------- | --------------- | --------- | ----------- | ------ |
| new-definition-claude-sonnet-5-5-1 | new-definition | claude-sonnet-5-5 | 8 | 52 | 0.15 | 1 | yes | yes | yes | yes | no | yes | no |
| new-definition-claude-sonnet-5-5-2 | new-definition | claude-sonnet-5-5 | 7 | 49 | 0.15 | 1 | yes | yes | yes | yes | no | yes | no |
| new-definition-claude-sonnet-5-5-3 | new-definition | claude-sonnet-5-5 | 9 | 52 | 0.14 | 1 | yes | yes | yes | yes | yes | yes | yes |
| new-definition-claude-opus-5-5-1 | new-definition | claude-opus-5-5 | 14 | 58 | 0.42 | 1 | yes | yes | yes | yes | yes | yes | yes |
| new-definition-claude-opus-5-5-2 | new-definition | claude-opus-5-5 | 11 | 62 | 0.40 | 1 | yes | yes | yes | yes | yes | yes | yes |
| new-definition-claude-opus-5-5-3 | new-definition | claude-opus-5-5 | 16 | 81 | 0.51 | 1 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-sonnet-5-5-1 | change-definition | claude-sonnet-5-5 | 16 | 106 | 0.21 | 1 | yes | yes | yes | yes | no | yes | no |
| change-definition-claude-sonnet-5-5-2 | change-definition | claude-sonnet-5-5 | 16 | 111 | 0.22 | 1 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-sonnet-5-5-3 | change-definition | claude-sonnet-5-5 | 17 | 153 | 0.24 | 1 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-opus-5-5-1 | change-definition | claude-opus-5-5 | 21 | 209 | 0.63 | 2 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-opus-5-5-2 | change-definition | claude-opus-5-5 | 25 | 221 | 0.88 | 1 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-opus-5-5-3 | change-definition | claude-opus-5-5 | 22 | 176 | 0.71 | 1 | yes | yes | yes | yes | yes | yes | yes |
| fill-gaps-claude-sonnet-5-5-1 | fill-gaps | claude-sonnet-5-5 | 12 | 100 | 0.18 | 0 | yes | yes | yes | yes | yes | yes | yes |
| fill-gaps-claude-sonnet-5-5-2 | fill-gaps | claude-sonnet-5-5 | 12 | 99 | 0.18 | 0 | yes | yes | yes | yes | yes | yes | yes |
| fill-gaps-claude-sonnet-5-5-3 | fill-gaps | claude-sonnet-5-5 | 11 | 109 | 0.17 | 0 | yes | yes | yes | yes | yes | yes | yes |
| fill-gaps-claude-opus-5-5-1 | fill-gaps | claude-opus-5-5 | 16 | 136 | 0.51 | 0 | yes | yes | yes | yes | yes | yes | yes |
| fill-gaps-claude-opus-5-5-2 | fill-gaps | claude-opus-5-5 | 18 | 137 | 0.52 | 0 | yes | yes | yes | yes | yes | yes | yes |
| fill-gaps-claude-opus-5-5-3 | fill-gaps | claude-opus-5-5 | 15 | 95 | 0.46 | 0 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-sonnet-5-5-1 | seed-csv | claude-sonnet-5-5 | 6 | 15 | 0.10 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-sonnet-5-5-2 | seed-csv | claude-sonnet-5-5 | 6 | 14 | 0.10 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-sonnet-5-5-3 | seed-csv | claude-sonnet-5-5 | 7 | 14 | 0.10 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-opus-5-5-1 | seed-csv | claude-opus-5-5 | 10 | 54 | 0.29 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-opus-5-5-2 | seed-csv | claude-opus-5-5 | 10 | 70 | 0.28 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-opus-5-5-3 | seed-csv | claude-opus-5-5 | 8 | 58 | 0.25 | 1 | yes | yes | yes | yes | yes | yes | yes |

### Problems and fixes of the repeated runs

The three failed runs had one cause: the agent did not run the tests of
the database. The generated FastAPI tests start Postgres with
Testcontainers, so they need Docker, and the skill did not say how to
run them without Docker. `claude-opus-5-5` found `TEST_DATABASE_URL` in
the README of the app and ran the tests on SQLite in each of its 6
FastAPI runs. `claude-sonnet-5-5` did so in 1 of 6 runs. In the other
runs, it saw the errors of Testcontainers and stopped. The failures
were in the hand-written code and in the migration of the agent, so the
tests would have shown them.

| # | Problem | Runs | Fix |
| - | ------- | ---- | --- |
| 6 | The skill did not tell how to run the FastAPI tests without Docker. | `claude-sonnet-5-5`: `new-definition` 1 and 2, `change-definition` 1 | Step 7 of the CLI loop in `SKILL.md`, the FastAPI section of `fill-gaps.md`, and step 4 of the database section of `change-definition.md` give `TEST_DATABASE_URL=sqlite+aiosqlite:///./test.db uv run pytest`. A test checks the command against the README and `tests/conftest.py` of the generated app. |
| 7 | The agent tested its operation `return_loan` with a loan of `make_loan(session)`, and expected no return date. The factories give a value to each field, also to the optional fields, so the operation gave 409. | `claude-sonnet-5-5`: `new-definition` 1 and 2 | `fill-gaps.md` says that the factories give a value to each field, and gives the example `make_task(session, status="todo", completed_at=None)`. A test checks the statement against `tests/payloads.py` and `tests/factories.py`. |
| 8 | `change-definition.md` told to rename the constraints of a renamed table "for Postgres". On SQLite, the unique constraint kept its old name `uq_members_email`, and `tests/test_migrations.py` failed. | `claude-sonnet-5-5`: `change-definition` 1 | The step tells to make each unique constraint again with its new name in `op.batch_alter_table` on SQLite. Two other runs of `claude-sonnet-5-5` did so without the text, and passed. |
| 9 | `claude-sonnet-5-5` did not build the React app in the runs of `seed-csv`, and said so in its answer. Step 7 of the CLI loop tells to build and test the app. | `claude-sonnet-5-5`: `seed-csv` 1 to 3 | No fix. The task changed only the definition, the data files, and the generated files, and the app built in each score. A change of step 8 of `seed-data.md` to "Generate, check, and build and test the app" did not change it in 3 more runs, so the skill keeps its text. |

### Runs after the fixes

The fixes 6 to 8 were installed into new home folders, and
`claude-sonnet-5-5` ran `new-definition`, `change-definition`, and
`seed-csv` again, three times each, with the same prompts. The runs of
`new-definition` had the fixes 6 and 7. The runs of `change-definition`
had the fixes 6 to 8. The runs of `seed-csv` had the test change of
step 8 (problem 9), which is not in the skill.

| Run | Task | Model | Turns | Time (s) | Cost (USD) | `validate` runs | Valid | No invalid traces | Gaps closed | No manual edits | App tests | Task checks | Passed |
| --- | ---- | ----- | ----: | -------: | ---------: | --------------: | ----- | ----------------- | ----------- | --------------- | --------- | ----------- | ------ |
| new-definition-claude-sonnet-5-5-fixed-1 | new-definition | claude-sonnet-5-5 | 10 | 43 | 0.12 | 2 | yes | yes | yes | yes | yes | yes | yes |
| new-definition-claude-sonnet-5-5-fixed-2 | new-definition | claude-sonnet-5-5 | 10 | 44 | 0.16 | 1 | yes | yes | yes | yes | yes | yes | yes |
| new-definition-claude-sonnet-5-5-fixed-3 | new-definition | claude-sonnet-5-5 | 9 | 37 | 0.14 | 1 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-sonnet-5-5-fixed-1 | change-definition | claude-sonnet-5-5 | 15 | 78 | 0.22 | 1 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-sonnet-5-5-fixed-2 | change-definition | claude-sonnet-5-5 | 16 | 83 | 0.22 | 2 | yes | yes | yes | yes | yes | yes | yes |
| change-definition-claude-sonnet-5-5-fixed-3 | change-definition | claude-sonnet-5-5 | 13 | 85 | 0.19 | 2 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-sonnet-5-5-fixed-1 | seed-csv | claude-sonnet-5-5 | 6 | 17 | 0.10 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-sonnet-5-5-fixed-2 | seed-csv | claude-sonnet-5-5 | 6 | 15 | 0.10 | 1 | yes | yes | yes | yes | yes | yes | yes |
| seed-csv-claude-sonnet-5-5-fixed-3 | seed-csv | claude-sonnet-5-5 | 6 | 13 | 0.10 | 1 | yes | yes | yes | yes | yes | yes | yes |

All 9 runs passed. In each FastAPI run, the agent ran the tests with
`TEST_DATABASE_URL` (fix 6), as the skill tells. In `new-definition`,
one run wrote a test of the logic of its operation, with
`make_loan(session, returned_on=None)` (fix 7). The other two runs wrote
no test of the logic. In `change-definition`, each migration made the
unique constraint again on SQLite (fix 8). In one run of
`new-definition`, the first `appgen validate` reported
`display_field: id`, because `id` is not a field of the definition. The
agent fixed it in one step.

### Seed records from a CSV file

The task `seed-csv` gives the room-booking example with the binding
`react`, and a file `rooms.csv`: an export with the columns `Room`,
`Floor`, `Seats`, `Rate per hour (EUR)`, and `Equipment`. The columns
are not the field names, the file has no column `key`, and the
equipment is text, not the keys of `Amenity` records. The check of the
task loads the definition with its data files, and compares the seed
records of `Room` with the file: the names, the floors, the seats, the
rates (Borealis has no rate), and the amenities. It also checks that the
mock data of the React app has the rooms.

Each of the 9 runs read `references/seed-data.md` and did the steps of
the reference:

- It mapped the columns to the fields `name`, `floor`, `capacity`, and
  `hourly_rate`, and the equipment to the relation `amenities`.
- It added `Amenity` seed records for the 3 kinds of equipment, because
  each target of a relation needs a seed record.
- It took the record keys from the names (`atlas`, `video_conference`),
  and left out the rate of Borealis.
- It kept `rooms.csv` as it was. 5 runs wrote a new data file
  `data/rooms.csv` in the format of the reference, with `file`, and 4
  runs wrote the records in `records`.

No run needed a second `appgen validate`.

## Runs of the quick-start skill

The quick-start skill `appgen-quickstart` (ADR 0053) makes an app from
one or more prompts without questions. Its table gives the defaults that
the prompts do not name, for example the binding `nextjs` for a web app.
The tasks of this part check that an agent with the installed skills
picks the defaults of the table, records them at the top of `app.yaml`,
and makes a working app.

### Method of the quick-start tasks

- The work folder is empty, or has only the files that the prompts
  name, and the home folder has both skills
  (`appgen skills install --scope user`). The prompts are in
  [evaluation/skill-tasks/](evaluation/skill-tasks/), in the files that
  start with `quickstart-`. They name no key of the DSL.
- A task with more than one prompt sends each further prompt in the same
  session: `run` starts `claude -p` again with `--resume` and the ID of
  the session. After `--resume`, the result of Claude Code gives the
  total cost of the session, so the script adds only the cost since the
  last result (`model_usage_since_last_result`).
- The score checks each expected app folder: `appgen check`, a new
  `appgen generate` into a copy, and the tests of the app. The check
  `Defaults` compares the work folder with the expected defaults of the
  task:
  - the binding of each app folder (in `.appgen/manifest.json`), and no
    other app folder;
  - the keys of the definition, for example `auth.user_entity` or
    `app.x-react-data: api`, and the keys that must not exist, for
    example `auth.providers`;
  - the record of the defaults: the line `# appgen-quickstart defaults:`,
    a line in the format of the skill for each default, and the expected
    rows, for example `binding` and `auth`.
- `tests/test_evaluate_skill.py` prepares and scores each task before
  and after a solution that the test writes, checks the defaults score
  with wrong defaults, and runs a fake `claude` command for a task with
  two prompts.

| Task | Prompts | Expected defaults |
| ---- | ------- | ----------------- |
| `quickstart-tool-library` | "Make an app for our neighborhood tool library. Members lend their tools to each other, and borrow a tool for a few days." | `nextjs` in `nextjs/`, a sign-in with a password and no provider, and the rows `binding`, `app`, and `auth`. |
| `quickstart-mobile-api` | "We are building a mobile app for a running club. Make the REST API behind it: ..." | Only `fastapi` in `fastapi/`, a sign-in, and the row `binding`. |
| `quickstart-company-jira` | "Make an internal IT help desk for our company. The staff sign in with their work Microsoft account: our Entra ID is connected to the Amazon Cognito user pool eu-west-1_Hd7Qm2xYz in eu-west-1, and its identity provider there has the name EntraID. Nobody needs another password for the help desk. ... The OpenAPI document of Jira is jira.openapi.json in this folder, and the app calls Jira with the email address and an API token of our Jira bot account." The work folder has the trimmed Jira document of `tests/fixtures/jira/`. | `nextjs` in `nextjs/`, no password and no sign-up, a provider with the issuer of the user pool, `authorize_params.identity_provider: EntraID`, `trust_email: true`, and `create_users: true`, the API `jira.openapi.json` with HTTP Basic (`username_env`), and the rows `binding`, `auth`, `providers`, `password`, and `apis`. |
| `quickstart-change-bindings` | First "Make an app for a small bike repair shop. ... A mechanic marks a repair as picked up, and that sets the pickup date to today.", then "Make the front end React with a Python API." | `react` in `react/` and `fastapi` in `fastapi/`, `app.x-react-data: api`, and the row `binding`. The folder `nextjs/` of the first prompt stays with its hand-written code, and the new apps have hand-written code for each element of it. |

The runs were on 2026-10-27, with appgen 0.1.0 (installed as a tool from
the branch of #489), Claude Code 2.1.311, and the model
`claude-sonnet-5-5` only: the runs cost money, and the maintainer chose
one model for this part. The work folders and the logs of the runs are
not in the repository. The task `quickstart-company-jira` needs the keys
of #483 and #486, so it ran later, with the fixes of the first runs
(see [The company sign-in and Jira](#the-company-sign-in-and-jira)).

### Results of the first runs

| Run | Task | Model | Turns | Time (s) | Cost (USD) | `validate` runs | Valid | No invalid traces | Gaps closed | No manual edits | App tests | Defaults | Task checks | Passed |
| --- | ---- | ----- | ----: | -------: | ---------: | --------------: | ----- | ----------------- | ----------- | --------------- | --------- | -------- | ----------- | ------ |
| change-bindings-claude-sonnet-5-5-1 | quickstart-change-bindings | claude-sonnet-5-5 | 20 | 135 | 0.33 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| change-bindings-claude-sonnet-5-5-2 | quickstart-change-bindings | claude-sonnet-5-5 | 21 | 150 | 0.31 | 2 | yes | yes | yes | yes | yes | no | yes | no |
| change-bindings-claude-sonnet-5-5-3 | quickstart-change-bindings | claude-sonnet-5-5 | 23 | 189 | 0.34 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| mobile-api-claude-sonnet-5-5-1 | quickstart-mobile-api | claude-sonnet-5-5 | 17 | 131 | 0.24 | 2 | yes | yes | yes | yes | yes | no | yes | no |
| mobile-api-claude-sonnet-5-5-2 | quickstart-mobile-api | claude-sonnet-5-5 | 12 | 97 | 0.20 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| mobile-api-claude-sonnet-5-5-3 | quickstart-mobile-api | claude-sonnet-5-5 | 12 | 316 | 0.17 | 3 | yes | yes | yes | yes | yes | yes | yes | yes |
| tool-library-claude-sonnet-5-5-1 | quickstart-tool-library | claude-sonnet-5-5 | 9 | 66 | 0.18 | 1 | yes | yes | yes | yes | yes | yes | yes | yes |
| tool-library-claude-sonnet-5-5-2 | quickstart-tool-library | claude-sonnet-5-5 | 13 | 80 | 0.22 | 1 | yes | yes | yes | yes | yes | yes | yes | yes |
| tool-library-claude-sonnet-5-5-3 | quickstart-tool-library | claude-sonnet-5-5 | 10 | 77 | 0.23 | 1 | yes | yes | yes | yes | yes | yes | yes | yes |

7 of 9 runs passed. In each run, the agent loaded `appgen-quickstart`
first, asked no question, and made the expected bindings in the
expected folders. Then it used the skill `appgen`: of the 18 runs of
this part, 7 loaded it with the Skill tool, and 11 read its files
(`../appgen/SKILL.md` and `references/new-definition.md`) as the
quick-start skill tells for other agents. Each definition was valid,
`appgen check` reported no invalid traces, no agent edited a generated
file, and the tests of each app passed. In each run of
`quickstart-change-bindings`, the folder `nextjs/` kept the
hand-written logic of the pickup (the custom operation `mark_picked_up`,
or `mark_repair_picked_up` in one run), and the FastAPI app had the same
logic again in Python. The React app with `x-react-data: api` calls the
operation of the FastAPI app, so it has no gap of its own.

The two failed runs failed only the check `Defaults`, because of the
record (problems 10 and 11). The runs also showed where the agents still
guessed (problem 12).

### Problems and fixes of the quick-start runs

| # | Problem | Runs | Fix |
| - | ------- | ---- | --- |
| 10 | The agent wrote a note after the words of the prompt: `... Prompt: "Make the REST API behind it" (only an API for a mobile app)`. | `quickstart-mobile-api` 1 | The skill gives the rules of a line of the record: the line ends with the closing quote, and a note goes into the summary. |
| 11 | The agent wrote a line for a default that it did not choose: `# - no auth: the prompt names no sign-in or roles; ...`. | `quickstart-change-bindings` 2 | The skill says that a row without its signal gets no line, for example no line `no auth`. |
| 12 | The roles were a guess. Without roles in the prompts, 5 of 6 runs of the tool library and the running club added `access` with invented roles, and 1 run did not. In the bike shop, 1 of 3 runs made no sign-in, because the row `auth` named customers as a signal, and the customers of the shop are only records. | all tasks | The row `auth` names the people who use the app as the signal, and says that people who are only records are no signal. The row `access` always comes with `auth`: the roles of the prompts, or else `admin` and one role for the other users. |

### Runs after the fixes

The fixes 10 to 12 were installed into new home folders, and each task
ran three more times.

| Run | Task | Model | Turns | Time (s) | Cost (USD) | `validate` runs | Valid | No invalid traces | Gaps closed | No manual edits | App tests | Defaults | Task checks | Passed |
| --- | ---- | ----- | ----: | -------: | ---------: | --------------: | ----- | ----------------- | ----------- | --------------- | --------- | -------- | ----------- | ------ |
| change-bindings-claude-sonnet-5-5-fixed-1 | quickstart-change-bindings | claude-sonnet-5-5 | 22 | 173 | 0.34 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| change-bindings-claude-sonnet-5-5-fixed-2 | quickstart-change-bindings | claude-sonnet-5-5 | 21 | 190 | 0.30 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| change-bindings-claude-sonnet-5-5-fixed-3 | quickstart-change-bindings | claude-sonnet-5-5 | 24 | 204 | 0.39 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| mobile-api-claude-sonnet-5-5-fixed-1 | quickstart-mobile-api | claude-sonnet-5-5 | 12 | 66 | 0.21 | 2 | yes | yes | yes | yes | yes | yes | yes | yes |
| mobile-api-claude-sonnet-5-5-fixed-2 | quickstart-mobile-api | claude-sonnet-5-5 | 14 | 101 | 0.23 | 3 | yes | yes | yes | yes | yes | yes | yes | yes |
| mobile-api-claude-sonnet-5-5-fixed-3 | quickstart-mobile-api | claude-sonnet-5-5 | 16 | 99 | 0.24 | 3 | yes | yes | yes | yes | yes | yes | yes | yes |
| tool-library-claude-sonnet-5-5-fixed-1 | quickstart-tool-library | claude-sonnet-5-5 | 12 | 69 | 0.19 | 1 | yes | yes | yes | yes | yes | yes | yes | yes |
| tool-library-claude-sonnet-5-5-fixed-2 | quickstart-tool-library | claude-sonnet-5-5 | 10 | 106 | 0.22 | 1 | yes | yes | yes | yes | yes | yes | yes | yes |
| tool-library-claude-sonnet-5-5-fixed-3 | quickstart-tool-library | claude-sonnet-5-5 | 14 | 102 | 0.25 | 1 | yes | yes | yes | yes | yes | yes | yes | yes |

All 9 runs passed. Each record had the format of the skill. Each run
made a sign-in and the roles `admin` and one role for the other users
(`member`, or `mechanic` in the bike shop). The other defaults still
differ between runs of the same prompt, because their signals are a
matter of judgment: the record rules (`records`) in 2 of 3 runs of the
tool library and in 3 of 3 runs of the running club, a workflow of the
loans in 3 of 3 runs of the tool library, and seed records in 1 run of
the tool library, which the prompt did not ask for. The expected
defaults of the tasks do not include these rows.

### The company sign-in and Jira

The task `quickstart-company-jira` ran after #483 and #486 were on
main, with the fixes 10 to 12 and two new parts of the skill: the keys
of a user pool of Amazon Cognito with an identity provider
(`authorize_params` and `trust_email`), and HTTP Basic for an API
(`username_env`, or `per_user` for the own account of each user). The
skill also tells the agent to leave out `roles` and `sign_out` when the
prompts do not give the IDs of the groups or the domain of the user
pool, and to name them in the summary.

| Run | Task | Model | Turns | Time (s) | Cost (USD) | `validate` runs | Valid | No invalid traces | Gaps closed | No manual edits | App tests | Defaults | Task checks | Passed |
| --- | ---- | ----- | ----: | -------: | ---------: | --------------: | ----- | ----------------- | ----------- | --------------- | --------- | -------- | ----------- | ------ |
| company-jira-claude-sonnet-5-5-1 | quickstart-company-jira | claude-sonnet-5-5 | 16 | 141 | 0.31 | 3 | yes | yes | yes | yes | yes | yes | yes | yes |
| company-jira-claude-sonnet-5-5-2 | quickstart-company-jira | claude-sonnet-5-5 | 15 | 130 | 0.29 | 3 | yes | yes | yes | yes | yes | yes | yes | yes |
| company-jira-claude-sonnet-5-5-3 | quickstart-company-jira | claude-sonnet-5-5 | 18 | 132 | 0.31 | 3 | yes | yes | yes | yes | yes | yes | yes | yes |

All 3 runs passed, and the three definitions agree in each expected
default:

- Each agent loaded both skills with the Skill tool, asked no question,
  and made `nextjs` in `nextjs/`. The provider had the issuer of the
  user pool, `authorize_params: { identity_provider: EntraID }`,
  `trust_email: true`, `create_users: true`, and `default_role: staff`,
  and `auth.password` was `false`.
- Each agent called Jira with HTTP Basic (`JIRA_EMAIL` and
  `JIRA_API_TOKEN`), selected only the search operation, and showed the
  open issues of the project IT in a view of API data with the JQL
  `project = IT AND statusCategory != Done ORDER BY created DESC`. The
  app needs no hand-written code for it.
- No agent added `roles` or `sign_out`. Each summary told that the
  sign-out ends only the session of the app until the user gives the
  domain of the user pool, and two summaries told that the roles from
  the groups of Entra ID need the IDs of the groups.
- Each run made the roles `it_team` and `staff`, the record rules (a
  member of the staff sees only the own tickets), and a workflow of the
  status of a ticket. The task does not expect these rows.

The three runs cost 0.91 USD.

## Limits

- In the first part, task 1 ran once, task 2 three times, and task 3
  two times, with one model. The repeated runs ran each task three
  times with two models. The runs of the quick-start skill used one
  model. Other models, or more runs, can make other mistakes.
- The score of the quick-start tasks checks the defaults that the table
  of the skill fixes. It does not check the entities, the fields, or the
  pages that the agent chose.
- The repeated runs used SQLite for the FastAPI tests, because the
  machine had no Docker. A migration that works on SQLite can fail on
  Postgres.
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
