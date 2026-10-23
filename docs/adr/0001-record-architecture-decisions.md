# 0001. Record architecture decisions

- Date: 2026-10-23
- Deciders: Maintainers

## Status

Accepted

## Context

This project is a proof of concept for an application code generator.
It has many design decisions with long effects: the YAML DSL, the UI
DSL, the trace format, the generation gaps, and the bindings. A
decision that has no written record is difficult to review, to explain
to new contributors, and to change later.

CONTRIBUTING.md asks for a record of each important design decision.

## Decision

We record each important design decision as an architecture decision
record (ADR). We use the format of Michael Nygard, as described in
"Documenting Architecture Decisions" (2011).

- Each ADR is one Markdown file in `docs/adr/`.
- The file name is `NNNN-short-title.md`. `NNNN` is a number with four
  digits. The numbers start at `0001` and increase by one.
- Each ADR starts from `docs/adr/template.md` and has the sections
  Status, Context, Decision, and Consequences.
- The status is Proposed, Accepted, Deprecated, or Superseded.
- We do not change the decision of an accepted ADR. To change a
  decision, we write a new ADR that supersedes the old ADR. We then set
  the status of the old ADR to "Superseded by NNNN".
- `docs/adr/README.md` lists each ADR with its number, title, and
  status. The pull request that adds or changes an ADR also updates
  this list.

## Consequences

- Each important decision has a record of its context and its results.
- Reviewers can discuss a decision in the pull request that adds the
  ADR, before the code depends on it.
- Contributors must write an ADR for important decisions. This adds a
  small amount of work to each such change.
- The index in `docs/adr/README.md` is maintained by hand. A pull
  request can forget to update it, so reviewers must check it.
