# Diagnostic codes

Read this file when `appgen validate` or `appgen check` reports a code
that you do not understand. Each entry of the JSON has `code`,
`message`, the position (`file`, `line`, `column`), `element_id`, and
`hint`. Read the `message` and the `hint` first: they name the key, the
value, and often the fix. Then use the tables below.

## Diagnostics of a definition

`appgen validate --format json` gives these codes in `diagnostics`.
`appgen generate`, `appgen check`, and `appgen orphans` stop with the
same diagnostics if the definition is not valid.

| Code                   | Cause                                                                 | Fix                                                                 |
| ---------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `file-error`           | appgen cannot read the file, for example a wrong path.                | Give the path of a YAML file that exists.                           |
| `yaml-syntax`          | The text is not valid YAML. In a flow mapping (`{ ... }`), a text with `: `, `?`, `#`, `{`, `[`, or `,` often causes it. | Fix the YAML at the line and column. Put quotes around the text, for example `title: "Cancel?"`. |
| `duplicate-key`        | A mapping has the same key two times.                                 | Remove one key, or merge the two values. The hint gives the first one. |
| `invalid-key`          | A mapping key is a list or a mapping.                                 | Use a plain name as the key.                                        |
| `empty-definition`     | The file has no content.                                              | Write the definition. Start from the start definition of `new-definition.md`. |
| `missing-version`      | The key `version` is missing.                                         | Add `version: 0` at the top of the file.                            |
| `unsupported-version`  | `version` is not a version that this appgen reads.                    | Use `version: 0`.                                                   |
| `not-supported`        | A section that this version of the DSL does not support.              | Remove the section, or keep its data in an extension key, for example `x-<section>`. |
| `missing-key`          | A required key is missing, for example `title` of `app`, or `kind` of an operation. | Add the key. `dsl.md` gives the required keys of each element. |
| `unknown-key`          | A key that the element does not have, often a typo, or an extension key that no binding in use declares. | Use the key of the hint, or remove the key. |
| `invalid-value`        | A value of the wrong type or not in the allowed values, for example `type: strng`, or a boolean where a name must be. | Use a value from the message or the hint. Put quotes around `yes`, `no`, `on`, and `off`. |
| `invalid-name`         | A name does not match its pattern, for example an entity name in snake case. | Rename it: entities in PascalCase, other names in snake case. |
| `duplicate-name`       | Two names differ only in case, or two elements of a kind have the same name. | Give each element its own name.                                |
| `duplicate-id`         | Two elements have the same element ID.                                | Rename one element. The hint gives the other element.               |
| `reserved-name`        | A name that appgen reserves, for example a field `id`.                | Use another name. Each entity has an implicit `id` field.           |
| `duplicate-path`       | Two pages have the same path.                                         | Give each page its own path.                                        |
| `unknown-reference`    | A reference to an element that does not exist: an entity, a field, an operation, a page, a view, a form, a token, and so on. | Use the name of an element that exists, or add the element. Check the spelling and the case. |
| `invalid-option`       | An option that does not suit the element, for example `max_length` on a `boolean` field, or `min` greater than `max`. | Remove the option, or change the type. The message names the types of the option. |
| `missing-inverse`      | A `one_to_many` relation has no `inverse`.                            | Add a `many_to_one` relation back on the target, and name it in `inverse`. |
| `invalid-inverse`      | The `inverse` is not the other side of the relation.                  | Name the `many_to_one` relation of the target that points back to this entity. |
| `missing-translation`  | A language of `translations` does not translate a key that another language translates. | Give each language the same keys of `text`.             |
| `invalid-token-value`  | The `$value` of a token does not suit its group, for example `blue` in `color`. | Use a value of the group, for example `#2563eb` for a color. |
| `token-type-mismatch`  | A token has a type that its group does not have.                      | Move the token to the group of its type, or change its value.       |
| `token-loop`           | Tokens refer to each other in a loop.                                 | Give one token of the loop a literal value.                         |
| `unsuitable-token`     | A style key refers to a token of the wrong group, for example a `color` token as a `padding`. | Refer to a token of the group that the message names. |
| `unsuitable-field`     | A field of the wrong type or kind for its use, for example a board that groups by a `string` field, a form field `id`, or a rule on a computed field. | Use a field of the type that the message names, or change the field. |
| `unsuitable-badge`     | A badge set for another field.                                        | Use the badge set of the field, or add one for it.                  |
| `unsuitable-operation` | An operation of the wrong kind or entity, for example a form with a delete operation. | Use an operation of the kind and the entity that the message names. |
| `unsuitable-view`      | A view that does not suit the page, for example a detail view on a page without a path parameter. | Change the page path (for example `/tasks/{id}`), or use another view. |
| `missing-selection`    | A table view has `bulk_actions` but no `selection: true`.             | Add `selection: true` to the view.                                  |
| `missing-widget`       | A form field has no default widget, for example a `json` field.       | Set a `widget`, or `widget: custom` and write the widget by hand.   |

## Problems of a trace check

`appgen check --format json` gives these codes in `invalid`,
`warnings`, and `gaps_to_close`. Only the codes in `invalid` fail the
check.

| Code                             | Where           | Cause                                                       | Fix                                                        |
| -------------------------------- | --------------- | ----------------------------------------------------------- | ---------------------------------------------------------- |
| `unknown-element`                | `invalid`       | A trace to an element that the definition does not have, for example after a rename or a removal. | After a rename, change the trace to the new ID of the hint, and move the code with `appgen orphans`. After a removal, delete the trace and its code. |
| `malformed-trace`                | `invalid`       | The trace has no valid element ID.                          | Write `@trace[:kind] <element ID> [file\|begin\|end]`.     |
| `unknown-kind`                   | `invalid`       | A kind that is not `generated`, `gap`, or `manual`.         | Use `@trace:manual` for hand-written code.                 |
| `unknown-scope`                  | `invalid`       | A word after the ID that is not `file`, `begin`, or `end`.  | Remove the word, or put the text on another line.          |
| `file-trace-not-in-header`       | `invalid`       | A `file` trace after the first line of code.                | Move it to the comment lines at the top of the file.       |
| `unclosed-block`                 | `invalid`       | A `begin` trace without its `end` trace.                    | Add the `end` trace of the hint after the block.           |
| `unmatched-end`                  | `invalid`       | An `end` trace without a `begin` trace.                     | Add the `begin` trace, or remove the `end` trace.          |
| `mismatched-end`                 | `invalid`       | An `end` trace that does not close the innermost open block. | Close the inner block first. Blocks can nest, but not overlap. |
| `generated-trace-in-manual-file` | `invalid`       | A `generated` trace in a file that appgen did not write, for example code copied into an extension file. | Change it to `@trace:manual <element ID>`. |
| `skipped-trace`                  | `warnings`      | `@trace` text that is not in a comment of its own line, so the scan does not read it. | Put the trace in a comment on its own line, for example `// @trace:manual <element ID>`. |
| `gap-to-close`                   | `gaps_to_close` | A gap file without stub markers that still has a `gap` trace. | If the code is done, change `@trace:gap` to `@trace:manual` in its header. |
