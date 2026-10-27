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
| 0016   | [Sign-up of new users](0016-sign-up.md)                                | Accepted |
| 0017   | [Password reset](0017-password-reset.md)                               | Accepted |
| 0018   | [Owner rules for single records](0018-owner-rules.md)                  | Accepted |
| 0019   | [Third-party APIs from OpenAPI documents](0019-third-party-apis.md)    | Accepted |
| 0020   | [Sign-in with OpenID Connect providers](0020-providers.md)             | Accepted |
| 0021   | [Seed data in the app definition](0021-seed-data.md)                   | Accepted |
| 0022   | [Views of API data](0022-api-views.md)                                 | Accepted |
| 0023   | [Verification of the email address](0023-email-verification.md)       | Accepted |
| 0024   | [Second factor of the sign-in](0024-second-factor.md)                  | Accepted |
| 0025   | [Record rules with field conditions and owner paths](0025-record-rules.md) | Accepted |
| 0026   | [Translations of the values of the records](0026-record-translations.md) | Accepted |
| 0027   | [Files and images in the records](0027-files.md)                       | Accepted |
| 0028   | [Signed webhooks](0028-webhooks.md)                                    | Accepted |
| 0029   | [Jobs on a schedule and at the time of a date field](0029-jobs.md)    | Accepted |
| 0030   | [Inbound email in webhooks](0030-inbound-email.md)                     | Accepted |
| 0031   | [Events of the entities](0031-events.md)                               | Accepted |
| 0032   | [Pages in frames of other websites](0032-pages-in-frames.md)           | Accepted |
| 0033   | [Calls of an API in the name of a user](0033-api-connections.md)       | Accepted |
| 0034   | [Totals of the relations in computed fields](0034-totals.md)           | Accepted |
| 0035   | [Lines of a record in create and update operations](0035-lines.md)     | Accepted |
| 0037   | [Sequence numbers of the fields](0037-sequence-numbers.md)             | Accepted |
| 0038   | [The period of a dashboard](0038-dashboard-period.md)                  | Accepted |
| 0039   | [A manual order with drag and drop](0039-manual-order.md)              | Accepted |
| 0040   | [Change log of the records](0040-history.md)                           | Accepted |
| 0041   | [Notices of the changes of records](0041-notifications.md)              | Accepted |
| 0045   | [Custom queries that return a list](0045-queries.md)                    | Accepted |
| 0046   | [Places: point fields and the geo filters](0046-geo-points.md)          | Accepted |
| 0051   | [Live updates of the records](0051-live-updates.md)                     | Accepted |
