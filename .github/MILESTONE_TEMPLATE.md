# Milestone template

GitHub has no native template for milestones. Use this file when you
create or change a milestone.

## Fields

| Field       | Rule                                                                                    |
| ----------- | --------------------------------------------------------------------------------------- |
| Title       | `M<n>: <name>`, for example `M1: App definition DSL`. Number milestones in delivery order. |
| Due date    | Optional. Set a due date only for a real deadline.                                      |
| Description | Copy the template below and fill in each section. Keep each section short.             |

## Description template

````markdown
**Goal:** <One sentence: the outcome that this milestone delivers.>

**Scope**
- In: <what this milestone includes>
- Out: <what this milestone does not include>

**Exit criteria**
- [ ] <A testable condition that must be true before the milestone closes.>

**Demo:** <The command or the steps that show the result.>

**Depends on:** <Earlier milestones, or "None".>
````

## Rules

- Each story belongs to one milestone only.
- Close a milestone when all its stories are closed and all its exit
  criteria are true.
- If a story is not done when the milestone closes, move the story to a
  later milestone first.
- If the scope of an open milestone changes, update its description.
