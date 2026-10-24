# 0004. Trace format

- Date: 2026-10-23
- Deciders: Maintainers

## Status

Accepted

## Context

Traces connect the code of an app to the elements of its app
definition. The generator writes traces into the generated code, and
app developers write traces into hand-written code. The trace checker
(M4) reads the traces of an app, and reports two things:

- The definition elements that no code covers.
- The traces that are not valid, for example a trace to an element
  that does not exist.

Thus the generator, the developers, and the checker must agree on one
syntax. The syntax has these constraints:

- The PoC bindings write TypeScript, TSX, Python, SQL, CSS,
  Dockerfiles, YAML, and Markdown. Each file type has its own comment
  syntax. Some file types, for example JSON, have no comments.
- A trace must not change the behavior of the code. Thus it must be in
  a comment.
- The checker must find traces with a simple text scan. A parser for
  each language is too much work for the PoC.
- A trace refers to an element by its element ID (ADR 0002, #10), for
  example `entities.Task.fields.title`. Token IDs of the UI DSL (ADR
  0003) can have segments that start with a digit, for example
  `ui.tokens.color.blue.600`.
- The checker must see the difference between generated code, a
  generation gap (code that the developer must write), and
  hand-written code.

We looked at similar mechanisms:

- **Requirement tags** such as `@req REQ-12` in safety-critical code
  refer to requirement IDs in comments. They usually mark functions
  and have no end.
- **Region markers** such as `// #region` in TypeScript and
  `# region` in some Python editors mark a block with a begin and an
  end comment.
- **Generated-file headers** such as `// Code generated ... DO NOT
  EDIT.` in Go mark a whole file with one comment at the top.

## Decision

### Syntax

A trace is a tag in a comment:

```text
trace = "@trace" [ ":" kind ] 1*SP id [ 1*SP scope ]
kind  = "generated" / "gap" / "manual"   ; default: generated
scope = "file" / "begin" / "end"         ; default: a line trace
id    = segment *( "." segment )
segment = 1*( ALPHA / DIGIT / "_" )
```

Examples:

```text
@trace app file
@trace entities.Task.fields.title
@trace:gap operations.complete_task begin
@trace:gap operations.complete_task end
@trace:manual operations.complete_task
```

- One trace has one element ID. For many elements, write one trace
  for each element.
- The tag is case sensitive.
- A trace ends at the end of the ID or the scope. Text after it (for
  example the `*/` of a block comment, or an explanation) is not a part
  of the trace.
- The segment rule permits all names of ADR 0002 and ADR 0003. The
  checker, not the syntax, decides if the ID exists.

The checker finds traces with this regular expression, on a line that
has a comment opener of the file type before the tag (see "Comment
syntax"):

```text
@trace(?::(?P<kind>[a-z]+))?[ \t]+(?P<id>[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)(?:[ \t]+(?P<scope>file|begin|end)\b)?
```

The checker reads the kind as text, and reports an unknown kind as an
invalid trace.

### Comment syntax

The trace must be on the same line as a comment opener, after it. The
checker does not read traces inside the later lines of a multi-line
comment, or in strings. Thus a Python decorator named `trace`, or the
text `@trace` in a string, is not a trace.

| File type                | Extensions                           | Trace comment                         |
| ------------------------ | ------------------------------------ | ------------------------------------- |
| TypeScript, JavaScript   | `.ts`, `.mts`, `.js`, `.mjs`, `.cjs` | `// @trace ...` or `/* @trace ... */` |
| TSX, JSX                 | `.tsx`, `.jsx`                       | `// @trace ...`, and `{/* @trace ... */}` in JSX children |
| Python                   | `.py`, `.pyi`                        | `# @trace ...`                        |
| SQL                      | `.sql`                               | `-- @trace ...`                       |
| CSS                      | `.css`                               | `/* @trace ... */`                    |
| Dockerfile               | `Dockerfile`, `*.dockerfile`         | `# @trace ...`                        |
| YAML                     | `.yaml`, `.yml`                      | `# @trace ...`                        |
| Markdown                 | `.md`                                | `<!-- @trace ... -->`                 |
| TOML, shell, `.env`      | `.toml`, `.sh`, `.env`, `.env.*`     | `# @trace ...`                        |
| HTML                     | `.html`                              | `<!-- @trace ... -->`                 |

A binding that writes another file type adds it to this table, with
a change to this ADR.

Some files cannot hold comments, for example JSON files
(`package.json`, `tsconfig.json`, `components.json`) and lock files.
The generator writes no trace into these files. The output manifest
(#31) lists the element IDs of each generated file, and the checker
reads the traces of these files from the manifest.

### Kinds

| Kind        | Who writes it | Meaning                                                                             |
| ----------- | ------------- | ----------------------------------------------------------------------------------- |
| `generated` | The generator | This code comes from the element. The default kind, so `@trace <id>` is generated.  |
| `gap`       | The generator | The element needs hand-written code here. The binding cannot generate it.           |
| `manual`    | The developer | This hand-written code covers the element.                                           |

The generation gap ADR (#25) defines where the generator writes gap
traces. When the developer writes the code of a gap, the developer
changes `@trace:gap` to `@trace:manual` in the same place.

The checker uses the kinds for coverage:

- An element with a `gap` trace is an open gap, also when it has other
  traces (changed by #151: the generated code that calls a stub has a
  `generated` trace to the same element).
- An element with a `generated` or a `manual` trace, and no `gap`
  trace, is covered.
- An element with no trace is uncovered.

A trace covers only its own element. A trace to an entity does not
cover the fields of the entity. The templates write a trace for each
element that they render.

### Scope

A trace has one of three scopes:

| Scope   | Written as             | Applies to                                                                 |
| ------- | ---------------------- | -------------------------------------------------------------------------- |
| File    | `@trace <id> file`     | The whole file.                                                            |
| Block   | `@trace <id> begin` and `@trace <id> end` | The lines between the two traces.                       |
| Line    | `@trace <id>`          | The line of the trace, if the comment follows code on that line. Else the next line that is not blank and not a comment. |

Rules:

- **File traces** are in the header of the file: the comment lines and
  blank lines at the top. Only a shebang (`#!`), a Python encoding
  line, and Dockerfile parser directives (for example `# syntax=...`)
  can come before the header. A TypeScript directive such as
  `"use client"` comes after the header, because comments can come
  before it.
- **Block traces** have a `begin` and an `end` with the same kind and
  the same ID. Blocks can nest, but they cannot overlap: an `end`
  closes the innermost open block, and its kind and ID must agree. An
  `end` without a `begin`, or a `begin` without an `end` at the end of
  the file, is an invalid trace.
- **Line traces** have no end.

Each generated file starts with a header that says that the generator
wrote it, and that has at least one file trace. The header has no date
and no generator version, so that the output does not change from one
run to the next:

```ts
// Generated by appgen. Do not edit: change the app definition instead.
// @trace entities.Task file
```

### Invalid traces

The checker reports these traces as invalid:

- A trace with an ID that is not an element of the definition, for
  example after a rename.
- A trace with an unknown kind or an unknown scope word.
- A file trace that is not in the header.
- A block trace without its other end, or with an end that does not
  agree with the innermost open block.
- A `generated` trace in a file that the output manifest does not list
  as a generated file, for example code that a developer copied into
  an extension file.

### Examples

TypeScript:

```ts
// Generated by appgen. Do not edit: change the app definition instead.
// @trace entities.Task file

export type Task = {
  id: string;
  title: string; // @trace entities.Task.fields.title
  // @trace entities.Task.fields.due_date
  dueDate: string | null;
};
```

TSX:

```tsx
// @trace ui.views.task_table file
export function TaskTable() {
  return (
    <Table>
      {/* @trace ui.views.task_table.columns.title begin */}
      <TableHead>Title</TableHead>
      {/* @trace ui.views.task_table.columns.title end */}
    </Table>
  );
}
```

Python, an extension file as the generator creates it:

```python
# @trace:gap operations.complete_task file


def complete_task(task: Task, note: str | None) -> Task:
    raise NotImplementedError  # TODO: write the logic of complete_task.
```

The same file after the developer writes the code:

```python
# @trace:manual operations.complete_task file


def complete_task(task: Task, note: str | None) -> Task:
    task.done = True
    return task
```

SQL:

```sql
-- @trace entities.Task file
CREATE TABLE task (
  id uuid PRIMARY KEY,
  title text NOT NULL -- @trace entities.Task.fields.title
);
```

CSS:

```css
/* @trace ui.tokens file */
:root {
  --primary: #2563eb; /* @trace ui.tokens.color.primary */
}
```

Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
# @trace app file
FROM python:3.14-slim
```

YAML:

```yaml
# @trace app file
services:
  db: # @trace app
    image: postgres:18
```

Markdown:

```md
<!-- @trace app file -->
# Project Tracker
```

## Consequences

- One text scan with one regular expression finds all traces in all
  file types. The checker needs no parser for each language.
- The default kind and the default scope keep the most common trace
  short: `// @trace entities.Task.fields.title`.
- Coverage is explicit: each element needs its own trace. The
  templates must write more traces, and the generated code has more
  comments.
- The `gap` to `manual` change gives the checker a list of the open
  gaps, but the developer must remember to change the trace.
- Traces in strings and in the later lines of block comments are not
  found. The generator never writes them there, and developers must
  put a trace on the line of its comment opener. The checker shows a
  warning for such trace text (#153).
- Files without comments get their traces from the manifest, so the
  checker of these files depends on the manifest.
- A rename in the definition makes the traces to the old ID invalid.
  The checker reports them, so that the developer can fix them.
