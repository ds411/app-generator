# Example app definitions

| Path                       | Content                                                                    |
| -------------------------- | -------------------------------------------------------------------------- |
| `project-tracker/app.yaml` | The main example: projects, tasks, people, and comments, with CRUD and custom operations. |
| `edge-cases/app.yaml`      | Each field type, field option, relation kind, and operation kind, and extension keys. |
| `invalid/`                 | Broken definitions. Each one starts with `# expect: <code>`, the diagnostic that it causes. |

The tests in `tests/test_examples.py` load each example.

To check an example by hand:

```sh
uv run appgen validate examples/project-tracker/app.yaml
uv run appgen validate --format json examples/invalid/unknown-key.yaml
```

The exit code is 0 for a valid definition and 1 for an invalid one.
