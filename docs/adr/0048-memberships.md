# 0048. Roles from membership records

- Date: 2026-10-27
- Deciders: Maintainers

## Status

Accepted

## Context

The roles of `access` (ADR 0012) are global: a field of the user
entity gives one role to a user, for all records. The record rules
(ADR 0018, ADR 0025) limit a role to the records of the user or to the
records with some values. But many apps give a user a role in one
record: a teacher of one course is a student of another course, and a
user is an owner of one team and a member of another team. The role is
in a record of a join entity, for example an enrollment, and not in
the user entity.

The options:

- **More record rules.** A rule with an owner path through the
  enrollments gives the courses of the user. But a rule has no role:
  the student and the teacher of a course get the same operations.
- **A role field in a many-to-many relation.** The relations of the
  DSL have no fields, and a join entity with its own fields is already
  a normal entity.
- **A membership entity with a role field.** A record has the user,
  the scope record, and the role. The role gives operations on the
  records of the scope.

## Decision

`access.memberships` names the membership entity (`entity`), its
`many_to_one` relation to the user entity (`user`), its `many_to_one`
relation to the scope entity (`scope`), and its `enum` role field
(`role_field`). `roles` gives the operations of each value of the role
field, or `*` for all operations of the entities of the scope.

The scope has the scope entity and the entities of `paths`: for each
entity, a path of `many_to_one` relations to the scope entity, for
example `lesson.course`. A record is in the scope record that its path
gives. The membership entity can have a path too.

The validator reports a missing entity, relation, or field, a relation
that is not `many_to_one`, a `user` that does not go to the user entity,
a `scope` that goes to the user entity, a role field that is not an
`enum` field, a role that is not a value of the field, a path that does
not end at the scope entity, a path for the scope entity, and an
operation that is a query or that is not an operation of an entity of
the scope.

The role of `access.roles` comes first. If it gives the operation, the
memberships do not apply, and the record rules of the role apply as
before. Else the request passes if a membership of the user has a role
that gives the operation, and it uses the records of the scopes of
these memberships only:

- A list gives the records in these scopes.
- A read, a change, a delete, or a custom operation on a record in
  another scope of the user gives 403: the user knows the record, but
  the role in that scope does not give the operation. A record out of
  all scopes of the user gives 404, as a record rule does.
- A create or a change that puts the record out of these scopes gives
  403, and the record does not change.
- An operation that no role of the user gives is 403.

The FastAPI app reads the scopes of the user from the database in each
request that needs them: a query of the membership entity, filtered by
the user and by the roles that give the operation. A change of a
membership applies at the next request, without a new token.

The front ends apply the memberships in a later change. Until
then, they show the pages and the actions of the role of
`access.roles` only, and the trace check reports the memberships.

## Consequences

- An app author gives a role in a team, a course, or a project with
  one membership entity, without a role field for each scope in the
  user entity.
- A user with a role of `access.roles` that gives an operation has
  that operation on all records. A typical app gives the members a role
  with few operations, and the memberships give the rest.
- Each request that the memberships allow has one more query, or two
  for an operation on one record.
- A user has one role in a scope record at most if the app makes the
  pair of the user and the scope unique, for example with a unique rule.
  With two memberships in one scope, the roles add up.
- The scope is one entity. An app with two kinds of scope, for example
  teams and projects, gives the project a path to its team.
