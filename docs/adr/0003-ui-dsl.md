# 0003. UI DSL

- Date: 2026-10-23
- Deciders: Maintainers

## Status

Accepted

## Context

The Next.js and the React bindings generate apps with a detailed UI:
an app shell, navigation, tables, boards, detail views with tabs,
dashboards, and forms in dialogs. The proof of concept must show that
the app definition can encode many of these UI details, and also the
design tokens (color, typography, spacing, and so on).

[ADR 0002](0002-app-definition-dsl-v0.md) reserves the top-level key
`ui` for this part of the DSL, and gives the pages a path and a title
only. It also gives the rules that this ADR keeps: YAML, mappings of
named elements (not lists), names without dots, element IDs that are
paths of mapping keys, and `x-` extension keys.

The UI part must not depend on one framework. The Next.js binding and
the React binding render the same definition, and both use shadcn/ui.
The FastAPI binding ignores the UI part.

We looked at these formats and tools:

- **The W3C Design Tokens Community Group (DTCG) format** keeps tokens
  in nested groups. A token has `$value`, and optional `$type` and
  `$description`. A group can set `$type` for its tokens. A reference
  is the path of a token in braces, for example `{color.blue.600}`.
  The format has composite types, for example `shadow` and
  `typography`. It has no simple way to give a token one value for each
  theme mode.
- **Style Dictionary** reads DTCG tokens and writes them for each
  platform. It resolves references, and it reports loops.
- **shadcn/ui** themes its components with CSS variables that have
  semantic names, for example `--primary` and `--primary-foreground`,
  with one set for the light mode and one set for the dark mode.
- **Low-code tools** (for example Retool and the admin UIs of
  Amplication and React Admin) describe a screen as a tree of
  components with properties. They show that tables, forms, and detail
  views of an entity follow a small number of patterns.

## Decision

### Overview

The `ui` section has these keys. All keys are optional.

| Key          | Content                                                           |
| ------------ | ----------------------------------------------------------------- |
| `theme`      | Theme settings, for example the default color mode.              |
| `tokens`     | The design tokens.                                                |
| `badges`     | Colors, icons, and labels for the values of an `enum` field.      |
| `layouts`    | App shells: sidebar, top bar, content, and footer regions.        |
| `navigation` | Menus with groups and items that open pages.                      |
| `views`      | Tables, card lists, boards, and detail views of an entity.        |
| `forms`      | Create, edit, and custom operation forms.                         |
| `dashboards` | Stat tiles, charts, and record lists on a grid.                   |
| `defaults`   | Values that apply when an element does not set them.              |

The `pages` section of ADR 0002 gets new optional keys: `layout`,
`content`, `actions`, and `breadcrumb`. A page is a route. It puts
one view, form, or dashboard into a layout.

The `ui` section is a part of DSL version 0. It only adds optional
keys, so the definitions that exist stay valid (see "Versions" in ADR
0002). The loader stops to report `ui` as "not supported in this
version".

### Element IDs

UI elements follow the ID rule of ADR 0002:

| Element           | ID                                                  |
| ----------------- | --------------------------------------------------- |
| Token or group    | `ui.tokens.<group>.<name>...`                       |
| Badge             | `ui.badges.<badge>`                                 |
| Layout            | `ui.layouts.<layout>`                               |
| Menu              | `ui.navigation.<menu>`                              |
| Menu group        | `ui.navigation.<menu>.groups.<group>`               |
| Menu item         | `ui.navigation.<menu>.groups.<group>.items.<item>`, or `ui.navigation.<menu>.items.<item>` |
| View              | `ui.views.<view>`                                   |
| Table column      | `ui.views.<view>.columns.<column>`                  |
| Filter            | `ui.views.<view>.filters.<filter>`                  |
| Action            | `ui.views.<view>.actions.<action>`, `ui.views.<view>.row_actions.<action>`, or `ui.views.<view>.bulk_actions.<action>` |
| Detail section    | `ui.views.<view>.sections.<section>`                |
| Detail tab        | `ui.views.<view>.tabs.<tab>`                        |
| Form              | `ui.forms.<form>`                                   |
| Form field        | `ui.forms.<form>.fields.<field>`                    |
| Form section      | `ui.forms.<form>.sections.<section>`                |
| Form rule         | `ui.forms.<form>.rules.<rule>`                      |
| Dashboard         | `ui.dashboards.<dashboard>`                         |
| Dashboard widget  | `ui.dashboards.<dashboard>.widgets.<widget>`        |
| Page action       | `pages.<page>.actions.<action>`                     |

### Names

UI element names follow the rule for fields: `^[a-z][a-z0-9_]*$`.
Token names have one more rule, `^[a-z0-9][a-z0-9_]*$`, so that a
scale step can be a number, for example `blue.600` or `spacing.4`.
The loader reads each mapping key as its text, so `600` and `"600"` are
the same name.

Icon names are the kebab-case names of [Lucide](https://lucide.dev),
the icon set of shadcn/ui, for example `folder-kanban`. The rule is
`^[a-z][a-z0-9-]*$`. The validator checks the format only. The
binding build fails for an icon that does not exist.

### References

UI elements refer to other elements in these ways:

| Target            | Syntax                         | Example                     |
| ----------------- | ------------------------------ | --------------------------- |
| Token             | Token path in braces           | `"{color.primary}"`         |
| Entity            | Entity name                    | `entity: Task`              |
| Field or relation | Field path from the entity     | `title`, `project.name`     |
| Operation         | Operation name                 | `operation: create_task`    |
| Page (route)      | Page name                      | `page: project_detail`      |
| View, form, dashboard, badge, layout, menu | Element name | `form: edit_task`  |
| Breakpoint        | Breakpoint token name          | `md`                        |
| Action            | Action name in the same scope  | `action: new_task`          |

A **field path** starts at the entity of the element. Each segment
before the last is a `many_to_one` or a `one_to_one` relation, and the
last segment is a field or a relation of the entity that it gets to.
`project.owner.name` on `Task` is the name of the owner of the project
of the task. A path that ends at a relation shows the `display_field`
of the target. The path `id` is the implicit primary key.

A **token reference** is a string that is one token path in braces.
The path starts below `ui.tokens`. Style properties in the UI (colors,
gaps, widths, and so on) take token references only, not literal
values. Thus all style values come from one source.

### Theme

```yaml
ui:
  theme:
    default_mode: system   # light, dark, or system
    mode_toggle: true      # show a light/dark switch in the top bar
```

### Design tokens

The tokens follow the DTCG format where it fits. `ui.tokens` has a
fixed set of top-level groups. Each group sets the type of its tokens:

| Group            | Type          | Value                                                        |
| ---------------- | ------------- | ------------------------------------------------------------ |
| `color`          | `color`       | `#rgb`, `#rrggbb`, `#rrggbbaa`, or `oklch()`, `rgb()`, `hsl()` |
| `font_family`    | `fontFamily`  | A family name, or a list of names (the fallback stack).      |
| `font_size`      | `dimension`   | A number with `px` or `rem`, for example `0.875rem`.         |
| `font_weight`    | `fontWeight`  | An integer from 1 to 1000.                                   |
| `line_height`    | `number`      | A number, for example `1.5`.                                 |
| `letter_spacing` | `dimension`   | A number with `px`, `rem`, or `em`.                          |
| `typography`     | `typography`  | `font_family`, `font_size`, `font_weight`, `line_height`, and `letter_spacing` (optional). |
| `spacing`        | `dimension`   | A number with `px` or `rem`, or `0`.                         |
| `size`           | `dimension`   | Widths and heights, for example a sidebar width.             |
| `radius`         | `dimension`   | A number with `px` or `rem`, or `0`.                         |
| `shadow`         | `shadow`      | `color`, `offset_x`, `offset_y`, `blur`, `spread`, and `inset` (optional), or a list of these. |
| `breakpoint`     | `dimension`   | A minimum screen width with `px`.                            |
| `duration`       | `duration`    | A number with `ms`, for example `150ms`.                     |

A **token** is a mapping with a `$value` key. A **group** is a mapping
without `$value`. Groups can nest to any depth. Tokens and groups can
have `$description`. A token can have `$type`, and it must agree with
its group. Other keys that start with `$` are errors.

A token value is a literal or a reference to a token of the same type.
A member of a composite value (`typography` or `shadow`) is a literal
or a reference to a token of the member type, for example
`font_size: "{font_size.sm}"`.

**Modes.** A token can have `$modes`, a mapping from a mode (`light`
or `dark`) to a value. The value of a mode is `$modes.<mode>`, or else
`$value`. A token without `$modes` has the same value in both modes.
Thus each color token has a light and a dark value. We do not use the
DTCG resolver module for modes: it puts each mode in a separate file,
and the DSL keeps one file for one app.

**Semantic tokens.** Base tokens hold literal values, for example
`color.blue.600`. Semantic tokens refer to base tokens, and they can
have modes, for example `color.primary`. The UI refers to semantic
tokens.

**Validation.** The validator reports a reference to a token that
does not exist, a reference to a group, a reference to a token of the
wrong type, a value that does not suit the type, and a loop of
references (with all the tokens in the loop).

**Resolution.** The generator core (M3, #30) resolves the tokens for
each mode into a flat, sorted list of final values. Each value keeps
the ID of its token for the traces.

```yaml
ui:
  tokens:
    color:
      blue:
        "50": { $value: "#eff6ff" }
        600: { $value: "#2563eb" }
        400: { $value: "#60a5fa" }
      white: { $value: "#ffffff" }
      slate:
        950: { $value: "#020617" }
      primary:
        $value: "{color.blue.600}"
        $modes: { dark: "{color.blue.400}" }
      background:
        $value: "{color.white}"
        $modes: { dark: "{color.slate.950}" }
    font_family:
      sans: { $value: [Inter, ui-sans-serif, system-ui, sans-serif] }
    font_size:
      sm: { $value: 0.875rem }
    font_weight:
      semibold: { $value: 600 }
    line_height:
      normal: { $value: 1.5 }
    typography:
      body:
        $value:
          font_family: "{font_family.sans}"
          font_size: "{font_size.sm}"
          font_weight: 400
          line_height: "{line_height.normal}"
    spacing:
      4: { $value: 1rem }
    radius:
      lg: { $value: 0.625rem }
    shadow:
      card:
        $value: { color: "#0000001a", offset_x: 0px, offset_y: 1px, blur: 3px, spread: 0px }
    breakpoint:
      md: { $value: 768px }
```

### Badges

A badge set gives each value of an `enum` field a label, a color, and
an icon. Views and dashboards use it to show the field.

```yaml
ui:
  badges:
    task_status:
      field: Task.status            # <Entity>.<field>, an enum field
      values:
        todo: { label: To do, color: "{color.status.todo}", icon: circle }
        in_progress: { label: In progress, color: "{color.status.active}", icon: loader }
        done: { label: Done, color: "{color.status.done}", icon: circle-check }
```

Each key of `values` must be a value of the enum. A value without an
entry shows its name and the default badge color.

### Layouts

A layout is an app shell with fixed regions:

| Region    | Keys                                                                                         |
| --------- | -------------------------------------------------------------------------------------------- |
| `sidebar` | `navigation` (a menu), `title`, `icon`, `width` (token), `mode` (`expanded`, `icons`, `drawer`, or `hidden`), `side` (`left` or `right`). |
| `topbar`  | `breadcrumbs` (boolean), `mode_toggle` (boolean), `search` (boolean), `actions` (actions).  |
| `content` | `max_width` (token), `padding` (token).                                                      |
| `footer`  | Optional. `text`.                                                                            |

`responsive` maps a breakpoint name to overrides of the region keys.
An override applies when the screen is narrower than the breakpoint.
When more than one override applies, the override of the smallest
breakpoint wins. The same rule applies to each `responsive` key in
this ADR.

```yaml
ui:
  layouts:
    app_shell:
      sidebar: { navigation: main, title: Project Tracker, icon: folder-kanban, width: "{size.sidebar}" }
      topbar: { breadcrumbs: true, mode_toggle: true }
      content: { max_width: "{size.content}", padding: "{spacing.6}" }
      responsive:
        lg: { sidebar: { mode: icons } }
        md: { sidebar: { mode: drawer }, content: { padding: "{spacing.4}" } }
```

### Navigation

A menu has `items`, or `groups` with `items`, or both. An item has
`page` (required), `label` (default: the page title), `icon`, and
`items` (one level of sub-items). A group has `label`, `icon`,
`collapsible`, and `items`. The order in the file is the order on the
screen. The items without a group show before the groups. The binding marks the item of the current route.

```yaml
ui:
  navigation:
    main:
      groups:
        workspace:
          label: Workspace
          items:
            dashboard: { page: dashboard, icon: layout-dashboard }
            projects: { page: projects, icon: folder-kanban }
            board: { page: task_board, label: Board, icon: square-kanban }
```

### Pages

The new page keys:

- `layout`: a layout name. Default: `ui.defaults.layout`.
- `content`: one of `view: <view>`, `form: <form>`,
  `dashboard: <dashboard>`, or `custom: true` (a generation gap).
- `actions`: actions in the page header, for example "New project".
- `breadcrumb`: the label of the page in the breadcrumbs. Default: the
  title. For a page with an `entity` and a path parameter, the default
  is the `display_field` of the record.
- `arrangement` (added in M12): layout hints for the page. `regions`
  gives the order of the title, the actions, and the content, and
  `columns` gives the grid columns. The key is not `layout`, because
  `layout` already names the app shell of the page. The hints stay
  small: a page has one content, so the hints only place the header
  parts around it. Without hints, the page keeps the default header.

**Breadcrumbs.** The breadcrumbs come from the route structure. The
parent of a page is the page whose path is the longest prefix of the
page path, segment by segment. `/projects/{id}` has the parent
`/projects`, and `/` is the root. The validator reports two pages with
the same path.

A path parameter of a page with an `entity` is a field of that entity,
usually `id`.

### Actions

Views, pages, and layouts have actions: a mapping from a name to an
action. Each action has a `kind`, and these common keys: `label`,
`icon`, `variant` (`default`, `secondary`, `outline`, `ghost`, or
`destructive`, the shadcn button variants), and `confirm` (`title`,
`message`, `confirm_label`).

| Kind        | Keys                                                                           |
| ----------- | ------------------------------------------------------------------------------ |
| `navigate`  | `page`, and `params`: a mapping from a path parameter to a field path (default: `id` to `id`). |
| `form`      | `form`: opens the form. In a row or a record, an edit form gets the record.    |
| `operation` | `operation`: runs the operation on the record, for example a delete.           |
| `custom`    | A generation gap.                                                              |

`form` and `operation` actions take `on_success`: `toast` (a text) and
`navigate` (a page).

### Views

A view shows the records of one `entity`. Each view has `kind`,
`entity`, and optional `title`, `description`, `actions`, and `states`.

#### Table

| Key            | Content                                                                          |
| -------------- | -------------------------------------------------------------------------------- |
| `columns`      | A mapping from a column name to a column. Required.                              |
| `sort`         | The default sort: `field` and `direction` (`asc` or `desc`).                     |
| `filters`      | A mapping from a filter name to a filter.                                        |
| `pagination`   | `page_size` and `page_sizes` (a list).                                           |
| `row_actions`  | Actions for each row.                                                            |
| `row_click`    | The name of a row action that runs when the user clicks a row.                   |
| `selection`    | Boolean. The rows get check boxes.                                               |
| `bulk_actions` | Actions for the selected rows. They need `selection: true`.                      |

A column has `field` (a field path, default: the column name),
`label` (default: the field label), `format`, `badge` (a badge set,
for `format: badge`), `width` (a `size` token), `align` (`start`,
`center`, or `end`), `sortable` (default `true`), `link` (a page that
the cell opens, with the record ID), and `hide_below` (a breakpoint:
the column hides on narrower screens).

| Format          | Field types                       |
| --------------- | --------------------------------- |
| `text`          | All                               |
| `number`        | `integer`, `decimal`              |
| `currency`      | `integer`, `decimal`              |
| `percent`       | `integer`, `decimal`              |
| `date`          | `date`, `datetime`                |
| `datetime`      | `datetime`                        |
| `relative_time` | `date`, `datetime`                |
| `boolean`       | `boolean`                         |
| `badge`         | `enum`                            |
| `email`         | `email`                           |
| `url`           | `url`                             |
| `avatar`        | A relation (initials of the display field) |

The default format is the `format` of the field (an entity field key,
added in M12), else a format for the field type.

A filter has `kind` and these keys:

| Kind         | Keys and field types                                                    |
| ------------ | ----------------------------------------------------------------------- |
| `search`     | `fields`: a list of `string`, `text`, or `email` field paths.           |
| `select`     | `field`: an `enum` field or a relation. `multiple` (boolean).           |
| `boolean`    | `field`: a `boolean` field.                                             |
| `date_range` | `field`: a `date` or `datetime` field.                                  |

All filters take `label` and `default`.

#### Cards

A card list has `card` and `grid`. `card` has `title` (a field path,
default: the display field), `subtitle`, `badge` (`field` and
`badge`), `fields` (a list of field paths), and `footer` (a list of
field paths). `grid` is a grid (see "Grids"). It also takes `sort`,
`filters`, `pagination`, and `row_actions`, as a table does.

#### Board

A board groups the records by `group_by`, an `enum` field. Each enum
value is a column, in the order of the enum values. `columns` maps an
enum value to `label`, `color` (a color token), and `limit` (a work in
progress limit). `card` is the same as for a card list. `move` is an
operation of kind `update` on the entity, or a `custom` operation with
a parameter of the `group_by` name. The binding calls it when the user
moves a card to another column. A board without `move` is read-only.

#### Detail

A detail view shows one record. The page gives the record from its
path parameter.

| Key        | Content                                                                         |
| ---------- | ------------------------------------------------------------------------------- |
| `header`   | `title` (a field path), `subtitle`, `badges` (a list of enum fields, each with the badge set of its field). |
| `sections` | A mapping from a section name to a section.                                     |
| `tabs`     | A mapping from a tab name to a tab.                                             |
| `actions`  | Actions on the record, for example edit and delete.                             |

A section has `title`, `description`, `fields` (a list of field paths),
`columns` (an integer from 1 to 4), and `custom: true` (a generation
gap). A tab has `label`, `icon`, and one of these:

- `sections`: sections, as above.
- `relation` and `view`: a list of related records. `relation` is a
  `one_to_many` or a `many_to_many` relation of the entity. `view` is a
  table or a card list of the target entity.
- `custom: true`: a generation gap.

Sections without tabs show above the tabs.

### Forms

A form has these keys:

| Key             | Content                                                                         |
| --------------- | ------------------------------------------------------------------------------- |
| `entity`        | The entity. Required.                                                           |
| `operation`     | The operation that the submit calls: `create`, `update`, or `custom`, on the entity. Required. |
| `mode`          | `dialog`, `sheet`, or `page`. Default: `dialog`.                                |
| `title`, `description`, `submit_label`, `cancel_label` | Texts.                                   |
| `fields`        | A mapping from a field name to a form field. Required.                          |
| `sections`      | A mapping from a section name to `title`, `description`, and `fields` (a list of form field names). |
| `grid`          | The column grid of the form (see "Grids").                                      |
| `rules`         | Rules across fields.                                                            |
| `defaults`      | A mapping from a field name to a literal, or to `$route.<param>`.               |
| `on_success`    | `toast`, `close` (default `true`), and `navigate` (a page).                     |

The name of a form field is a field or a relation of the entity. For a
`custom` operation, it is a parameter of the operation. Each form field
is in one section at most. Fields without a section go in a first
section without a title.

A form field has `widget`, `label`, `placeholder`, `help`, `span` (the
number of grid columns), `rows` (for `textarea`), `step` (for
`number`), `options` (for `select` and `radio` on a relation: a filter
on the target records), and `rules`.

| Widget     | Field types                                                  |
| ---------- | ------------------------------------------------------------ |
| `text`     | `string`, `email`, `url`, `uuid`                             |
| `textarea` | `string`, `text`                                             |
| `number`   | `integer`, `decimal`                                         |
| `select`   | `enum`, `many_to_one`, `one_to_one`                          |
| `radio`    | `enum`                                                       |
| `checkbox` | `boolean`                                                    |
| `switch`   | `boolean`                                                    |
| `date`     | `date`                                                       |
| `datetime` | `datetime`                                                   |
| `relation` | `many_to_one`, `one_to_one`, `many_to_many` (a search picker)|
| `custom`   | All. A generation gap.                                       |

The default widget comes from the field type. A `json` field needs
`widget: custom`.

**Rules.** The field types give the first checks, for example
`max_length`. A form field adds `rules`: a mapping from a rule to
`value` and `message`. The rules are `required`, `min_length`,
`max_length`, `pattern`, `min`, and `max`. `required` takes `message`
only. The form `rules` key holds rules across fields:

```yaml
rules:
  due_after_start:
    kind: compare           # compare or custom (a generation gap)
    field: due_date
    op: gte                 # eq, ne, lt, lte, gt, gte
    other: start_date
    message: The due date must be on or after the start date.
```

A `custom` rule is a generation gap. It has `message` and `fields` (the
form fields that show the message). The client and the server use the
same rules.

### Dashboards

A dashboard has `title`, `description`, `grid`, and `widgets`. Each
widget has `kind`, `label`, `span` (the number of grid columns), and
these keys:

| Kind    | Keys                                                                                     |
| ------- | ---------------------------------------------------------------------------------------- |
| `stat`  | `entity`, `aggregate` (`count`, `sum`, `avg`, `min`, or `max`), `field` (a number field, not for `count`), `filter`, `format` (`number`, `currency`, or `percent`; the default is the `format` of the field, else `number`), `icon`, `color` (a color token), `link` (a page). |
| `chart` | `chart` (`bar`, `line`, or `donut`), `entity`, `group_by` (an `enum`, `date`, or relation field), `aggregate`, `field`, `filter`, `badge` (colors for the groups). |
| `list`  | `view` (a table or a card list), `filter`, `sort`, `limit`, `link` (a page for "View all"). |
| `custom`| A generation gap.                                                                        |

A **filter** is a mapping from a field path to a value (equal to) or
to a mapping of operators: `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`,
and `not_in`. A value is a literal, or `$today` or `$now` for a date.

```yaml
widgets:
  overdue_tasks:
    kind: stat
    label: Overdue tasks
    entity: Task
    aggregate: count
    filter: { due_date: { lt: $today }, status: { ne: done } }
    icon: alarm-clock
    color: "{color.destructive}"
    link: task_board
```

### Grids

A grid has `columns` (an integer from 1 to 12), `gap` (a `spacing`
token), and `responsive` (a mapping from a breakpoint to `columns` and
`gap`). Forms, card lists, and dashboards use grids.

### UI states

Each view can have `states` with `loading`, `empty`, and `error`. Each
state has `title`, `text`, `icon`, and `action` (the name of an action
of the view). `loading` also has `indicator` (`skeleton` or
`spinner`). `error` can use the action name `retry`, which loads the
data again.

`ui.defaults.states` gives the states for views that do not define
them. Its only action is `retry`, in the error state, because the views
have different actions. The bindings have built-in states for what both leave out.

### Defaults

```yaml
ui:
  defaults:
    layout: app_shell
    page_size: 20
    states:
      loading: { indicator: skeleton }
      empty: { title: Nothing here yet, icon: inbox }
      error: { title: Something went wrong, icon: triangle-alert, action: retry }
```

### Binding map

The bindings map the UI elements to shadcn/ui components:

| UI element                | shadcn/ui and libraries                              |
| ------------------------- | ---------------------------------------------------- |
| Layout, sidebar           | `Sidebar` (`collapsible="icon"` or `"offcanvas"`)    |
| Breadcrumbs               | `Breadcrumb`                                         |
| Mode toggle               | `DropdownMenu` and the theme provider                |
| Table view                | Data table: `Table` and TanStack Table               |
| Filters                   | `Input`, `Select`, `Popover` and `Calendar`          |
| Card list, detail section | `Card`                                               |
| Board                     | `Card` columns, with drag and drop from dnd-kit      |
| Detail tabs               | `Tabs`                                               |
| Badge                     | `Badge`                                              |
| Stat tile                 | `Card`                                               |
| Chart                     | `Chart` (Recharts)                                   |
| Form                      | `Form` with react-hook-form and zod                  |
| Form mode                 | `Dialog`, `Sheet`, or a page                         |
| Widgets                   | `Input`, `Textarea`, `Select`, `RadioGroup`, `Checkbox`, `Switch`, `Calendar`, `Command` (relation picker) |
| Confirm                   | `AlertDialog`                                        |
| Toast                     | `Sonner`                                             |
| Loading, empty states     | `Skeleton`, `Empty`                                  |

The theme comes from the resolved tokens. The color tokens with the
names of the shadcn variables give these variables in each mode:
`color.background` gives `--background`, `color.primary_foreground`
gives `--primary-foreground`, and so on (`_` becomes `-`). `radius.lg`
gives `--radius`. The other tokens give Tailwind CSS theme variables,
for example `spacing.4` gives `--spacing-4`. A shadcn variable without
a token keeps the shadcn default.

### What the DSL does not describe

The DSL does not describe these UI details. A generation gap covers
each of them where an app needs it. The generation gap ADR (#25)
defines the mechanism.

| Detail                                              | Generation gap                                |
| --------------------------------------------------- | --------------------------------------------- |
| A custom page, section, tab, or widget              | `custom: true` or `kind: custom`              |
| A widget for a field that the widgets do not suit   | `widget: custom`                              |
| A validation rule that is not in the list           | A rule with `kind: custom`                    |
| A custom action                                     | An action with `kind: custom`                 |
| Animations and transitions                          | Hand-written code in the extension files.     |
| Pixel-level layout inside a component               | The shadcn component sources, which the app developer can change. |
| A page layout beyond the order and the columns of its regions | A page with `content: { custom: true }`. |
| Accessibility beyond the shadcn components          | Hand-written code.                            |
| Authentication, roles, and translations of the UI   | Later sections (ADR 0002).                    |

## Consequences

- An app author describes a detailed UI with a small number of
  patterns: tables, cards, boards, detail views, dashboards, and forms.
  Both front-end bindings render the same definition.
- All style values come from the tokens, so a change to a token
  changes the whole UI. The cost is that an app author cannot set a
  one-time color in a view.
- The tokens are close to the DTCG format, so tools such as Style
  Dictionary can read them with small changes. `$modes` and the fixed
  top-level groups are not in the DTCG format.
- Field paths across relations let views show related data. The
  bindings must load these relations, which makes the queries more
  complex.
- The UI part is large, so the validator has many rules for
  references between UI elements and the data model (#22).
- Details that the DSL does not describe need generation gaps. The
  `custom` keys make these gaps explicit, so that the trace checker
  can report them.
