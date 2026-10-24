# Change an app definition

Read this file when the task is to change the definition of an app that
exists: a generated app folder with `.appgen/manifest.json`, and maybe
hand-written code in its extension files. The goal: the app follows the
changed definition, the hand-written code stays, and `appgen check`
reports no invalid traces.

## Steps

1. Read the definition, and the report of the app:
   `appgen check app.yaml <dir> --format json`. Note the open `gaps`,
   and make sure that `invalid` is empty before you change anything.
2. Find the hand-written code that the change touches. Search the app
   folder for the IDs of the elements that you change, for example
   `grep -rn "entities.Task.fields.completed_at" <dir>`, and read the
   extension files with a `@trace:manual` trace.
3. Change the definition. Change only the elements of the task, and keep
   the names of the other elements.
4. Validate: `appgen validate app.yaml --format json`. Fix each
   diagnostic. A rename or a removal often leaves references to the old
   name (`unknown-reference`).
5. Generate into the same folder: `appgen generate app.yaml -b <binding>
   -o <dir>`. Read the summary: the files written and deleted, the gaps
   created, and the orphaned extension files.
6. Check: `appgen check app.yaml <dir> --format json`. Fix each entry of
   `invalid`, as the sections below tell.
7. Fill the new gaps ([fill-gaps.md](fill-gaps.md)).
8. Check again until `invalid` is empty. Then build and test the app
   with its commands.

## Add an element

A new element does not change the IDs of the other elements, so the
traces of the hand-written code stay valid. A new custom element gives
a new gap with a new extension file. A new field needs a database
migration in the FastAPI app (see [Database changes](#database-changes)).

## Rename an element

A rename changes the ID of the element and the IDs of all elements under
it. For example, the rename of the entity `Comment` to `Remark` changes
`entities.Comment.fields.body` to `entities.Remark.fields.body`.

In the definition, change all references to the old name too: the
`target` and `inverse` of relations, the field paths of views, forms,
badges (`field: Comment.body`), and dashboards, and the names in
`access`. The CRUD shorthand names its operations, views, and forms
after the entity, so a rename of an entity also renames them, for
example `create_comment` to `create_remark`.

After `appgen generate`, the generated code uses the new name. The
hand-written code keeps the old name, and the check reports each trace
to the old ID in `invalid`, with the code `unknown-element` and the hint
`Did you mean '<new ID>'?`. The extension files of the old element stay.
Move the code to the new element:

1. List the extension files of the old elements:
   `appgen orphans app.yaml <dir> --format json`. Each entry gives the
   `file`, the old `element_id`, and the `suggestion`: the element that
   most likely replaces it.
2. Open the extension file of the new element. The generator created it
   with a stub. Move the hand-written code into it, and change the names
   in the code: the types, the functions, the imports, and the fields,
   for example `record.completed_at` to `record.finished_at`.
3. In the new file, change the header to
   `@trace:manual <new ID> file`, and change the other traces to the new
   IDs.
4. Delete the old file. The next run of `appgen generate` removes it
   from the manifest.
5. For each other entry of `invalid` with the code `unknown-element`,
   for example a trace to a renamed field in the extension file of an
   operation, change the trace to the ID of the hint, and change the
   code.
6. Check again: `appgen check app.yaml <dir> --format json`, and
   `appgen orphans app.yaml <dir> --format json` lists no files.

A rename of a field or a relation has no extension files of its own, so
only step 5 applies. Do not rename an element if the task does not ask
for it.

## Remove an element

Remove the element and each reference to it from the definition, and
validate. After `appgen generate`, the generated files of the element
are gone, and its extension files stay. `appgen orphans` lists them,
often with `suggestion` `null`. Delete the hand-written code of the
element, or move the parts that other elements still need. Remove the
traces to the old ID, and check again.

## Generated files with manual edits

`appgen generate` stops and writes nothing if a generated file has
manual edits. It names the file (`changed by hand: <path>`), or a file
at the path of a new generated file that appgen did not write
(`not made by appgen: <path>`). Then:

1. Read the edit, and find where it belongs. If the DSL can describe
   it, change the definition. Else, move the code to an extension file.
2. For a `not made by appgen` file, move or rename the file.
3. Generate again with `--force`. It overwrites the generated files with
   manual edits, so do this only after step 1.

Never edit a generated file to fix a problem: the next run overwrites
the edit or stops.

## Database changes

The FastAPI app creates its first migration once, and keeps all
migrations. After a change of the entities, in the app folder:

1. `uv run alembic revision --autogenerate -m "<change>"` makes the next
   migration from the changed models.
2. Review the new file in `migrations/versions/`. Alembic writes a
   rename as a drop and an add: change it to a rename
   (`op.alter_column(..., new_column_name=...)`) to keep the data.
3. `uv run alembic upgrade head` applies it.

The Next.js app writes its SQL migrations with `pnpm db:generate`
(Drizzle). Review them in `drizzle/` in the same way.
