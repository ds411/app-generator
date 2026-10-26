# 0025. Record rules with field conditions and owner paths

- Date: 2026-10-25
- Deciders: Maintainers

## Status

Accepted

## Context

An owner rule (ADR 0018) limits a role to the records that its user
owns. The owner is one many-to-one relation of the entity to the user
entity. Real apps need more:

- A condition on the values of fields, for example "only the open
  tasks" or "only the published articles".
- An owner through other records, for example "the tasks of the
  projects of the teams of the user".
- The same rules in the embedded relations of the FastAPI app
  (`x-fastapi-embed`), because an embedded record of another user shows
  the data that the rule hides.

A general expression language for conditions is out of scope (M25). A
row-level security of the database is out of scope too.

## Decision

### The DSL

- A record rule `access.roles.<role>.records.<entity>` has `owner`,
  `where`, or both, and `operations` (`read`, `change`, or both, as
  before).
- `owner` is a relation of the entity, or a path of relations with
  dots, for example `project.team.members`. Each step is a
  `many_to_one` or a `many_to_many` relation of the entity of the step
  before, and the last step goes to the user entity. A record belongs
  to each user at the end of the path.
- `where` maps the name of a stored field of the entity to a value, or
  to a list of values (one of them). The field is a `string`, `text`,
  `email`, `url`, `integer`, `boolean`, or `enum` field. The value must
  be a valid value of the field, as a default. All conditions of a rule
  apply.
- All rules of an entity with an owner use the same owner path, so that
  the code of the entity has one owner condition. The conditions can be
  different for each role.

### The scope of a rule

The records in the scope of a rule are the records that belong to the
user (with `owner`) and that have the values of the conditions (with
`where`). All apps apply the same rules:

- A list gives only the records in the scope. A read, a change, a
  delete, or a custom operation on another record gives "not found"
  (404), as in ADR 0018.
- A create or a change gives "forbidden" (403) if the record after it
  is not in the scope. For a direct many-to-one owner (one step), a
  create still sets the owner to the user, and a change keeps the owner
  (ADR 0018).
- A custom operation checks the record before it runs: the record must
  be in the scope. The logic of the operation can move the record out
  of the scope, for example "cancel".
- The rules of the entities (for example `no_overlap`) still see all
  records. A rule does not apply to the public operations.

### The FastAPI app

- `app/core/access.py` has the table of the rules (`RECORD_RULES`):
  for each role and entity, the actions, `owner`, and the values of the
  conditions. It replaces `OWNER_RULES`. The dependency `scope_of`
  gives a `RecordScope`: the user, the role, and the action of the
  request.
- The repository of an entity with rules has the filter (`owned`): the
  owner path as `EXISTS` subqueries (`has()` and `any()` of
  SQLAlchemy), and `IN` for the conditions. Each query of an operation
  uses it, so a list needs one query. A create and a change write the
  record in the open transaction (`flush`), and use the same filter to
  check that the record is in the scope. If it is not, the change rolls
  back, and the answer is 403 with problem details.
- An embedded relation follows the rules of its target entity, with the
  filter of the repository of the target. An embedded record of one
  (`many_to_one` or `one_to_one`) outside the scope gives `null`, and
  its ID stays. An embedded list leaves out the records outside the
  scope. The read schema declares an embedded record of one as optional
  if its target has a rule.

### The front ends

- The shared table of the permissions (`src/shared/lib/permissions.ts`,
  ADR 0012) stays the one source of the rules: for each role and
  entity, the actions, `owner`, and the values of the conditions.
  `recordScopeOf` gives the scope of a user for an action.
- The data access of each entity has its owner path. Next.js: a Drizzle
  condition with subqueries, in the repository of the entity. React
  with mock data: the steps of the path, which the mock store follows
  through the records of the other stores.
- Next.js: the repository takes the scope of the request instead of
  the owner ID, and uses the same rules as the FastAPI app. A write out
  of the scope throws a `ForbiddenError`. React with `x-react-data:
  api`: the API applies the rules. React with mock data: the mock store
  applies them in the browser, as a demonstration.
- For a user of a rule, a form of a create or a change does not show
  the direct owner (as in ADR 0018) and the fields of the conditions
  with one value, and sets their values. A form does not set an owner
  through a path: the user selects for example the project, and the
  server checks it.

## Consequences

- The definition can express "the members of a team see the tasks of
  the projects of the team" and "a reviewer sees only the done tasks"
  without code.
- A condition cannot compare two fields, or use a range, a date, or a
  relation. A custom operation or a custom rule (ADR 0005) can add
  them.
- A path cannot use a `one_to_many` or a `one_to_one` relation. A
  new record has no records on the other side of such a relation yet,
  so it cannot belong to a user.
- A create and a change of a record with a rule need one more query.
- The read schema of the FastAPI app changes for an embedded record of
  one whose target has a rule: the object can be `null`.
