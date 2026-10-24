# Architecture decision records

This folder contains the architecture decision records (ADRs) of this
project. An ADR records one important design decision, its context, and
its consequences. [ADR 0001](0001-record-architecture-decisions.md)
gives the rules.

## Add an ADR

1. Copy [template.md](template.md) to `NNNN-short-title.md`. Use the
   next free number with four digits.
2. Fill in each section. Set the status to "Proposed".
3. Add the ADR to the list below.
4. Open a pull request. Set the status to "Accepted" before the merge.

## List of ADRs

| Number | Title                                                                  | Status   |
| ------ | ---------------------------------------------------------------------- | -------- |
| 0001   | [Record architecture decisions](0001-record-architecture-decisions.md) | Accepted |
| 0002   | [App definition DSL v0](0002-app-definition-dsl-v0.md)                 | Accepted |
| 0003   | [UI DSL](0003-ui-dsl.md)                                               | Accepted |
| 0004   | [Trace format](0004-trace-format.md)                                   | Accepted |
| 0005   | [Generation gaps](0005-generation-gaps.md)                             | Accepted |
| 0006   | [FastAPI binding](0006-fastapi-binding.md)                             | Accepted |
| 0007   | [Local database without a Postgres server](0007-local-database.md)     | Accepted |
| 0008   | [CRUD shorthand](0008-crud-shorthand.md)                               | Accepted |
| 0009   | [Schema changes of the FastAPI app](0009-fastapi-schema-changes.md)    | Accepted |
| 0010   | [Translations of the UI text](0010-translations.md)                    | Accepted |
| 0011   | [Sign-in of the generated apps](0011-auth.md)                          | Accepted |
| 0012   | [Roles and permissions](0012-access.md)                                | Accepted |
| 0013   | [Production settings of the FastAPI app](0013-fastapi-production.md)   | Accepted |
| 0014   | [API client of the React app](0014-react-api-client.md)               | Accepted |
| 0015   | [Agent skills](0015-agent-skills.md)                                   | Accepted |
