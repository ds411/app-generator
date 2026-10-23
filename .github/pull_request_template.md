<!--
PR title: use the commit subject format, for example
"feat(dsl): add entity relations". The PR title becomes the subject of
the squash commit. See CONTRIBUTING.md, section "Pull requests".
-->

## Summary

<!-- What does this PR change, and why? Write one short paragraph. -->

## Related issues

<!--
Write "Closes #<n>" for each story that this PR completes.
Write "Refs #<n>" for each related issue that stays open.
-->

Closes #

## Changes

<!-- List the main changes. -->

-

## Traces and coverage

<!--
Fill in this section for changes to the DSL, the generator, a binding,
or the trace checker. Write "Not applicable" for other changes.
-->

- App definition elements that this PR adds or covers:
- Generation gaps that this PR adds or removes:
- Trace check result (uncovered elements, invalid traces):

## How to test

<!-- Give the commands that a reviewer runs to check the change. -->

```sh

```

## Squash commit message

<!--
The recommended message for "Squash and merge". Use the commit format
(see CONTRIBUTING.md, section "Commits"). The first line is the PR title
and the PR number. Keep the trailers of all authors. Do not add links to
claude.ai.
-->

```text
<type>(<scope>): <summary> (#<pr>)

<What changes and why. Wrap lines at 72 characters.>

Closes #<issue>
Co-Authored-By: <name> <email>
```

## Checklist

- [ ] The PR title and the commits follow the [commit format](https://github.com/ds411/app-generator/blob/main/CONTRIBUTING.md#commits).
- [ ] The PR has tests for the change, or the summary says why it needs none.
- [ ] The pre-push hook passes (lint, type checks, and tests).
- [ ] Generated output is deterministic: a second run gives no diff.
- [ ] The trace check reports no invalid traces.
- [ ] The docs (README, CONTRIBUTING, ADRs) agree with the change.
- [ ] The PR contains no links to claude.ai.
