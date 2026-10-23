import json
from pathlib import Path
from textwrap import dedent
from typing import Any

import jsonschema
import pytest
import yaml
from typer.testing import CliRunner

from appgen.cli import app
from appgen.dsl.schema import json_schema, json_schema_text

ROOT = Path(__file__).parent.parent
COMMITTED = ROOT / "schema" / "app.schema.json"

DEFINITION = dedent(
    """\
    version: 0
    x-owner: team-a
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        x-table: tasks
        fields:
          title: { type: string, required: true }
          status: { type: enum, values: [open, done], default: open }
        relations:
          parent: { kind: many_to_one, target: Task }
    operations:
      list_tasks: { kind: list, entity: Task }
    pages:
      tasks: { path: /tasks, title: Tasks }
    """
)

runner = CliRunner()


def schema_errors(text: str) -> list[str]:
    instance: Any = yaml.safe_load(text)
    validator = jsonschema.Draft202012Validator(json_schema())
    errors = validator.iter_errors(instance)  # pyright: ignore[reportUnknownMemberType]
    return [error.message for error in errors]


def test_committed_schema_is_up_to_date() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == json_schema_text(), (
        "Run 'uv run appgen schema --out schema/app.schema.json'."
    )


def test_schema_is_a_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(json_schema())


def test_schema_accepts_a_valid_definition() -> None:
    assert schema_errors(DEFINITION) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("type: string", "type: strng"),
        ("required: true", "requird: true"),
        ("  Task:\n", "  task:\n"),
        ("version: 0", "version: 1"),
        ("x-owner: team-a", "auth: {}"),
    ],
)
def test_schema_rejects_an_invalid_definition(old: str, new: str) -> None:
    assert schema_errors(DEFINITION.replace(old, new, 1)) != []


def test_schema_command_writes_to_stdout() -> None:
    result = runner.invoke(app, ["schema"])

    assert result.exit_code == 0
    assert json.loads(result.output)["$id"].endswith("/schema/app.schema.json")


def test_schema_command_writes_to_a_file(tmp_path: Path) -> None:
    out = tmp_path / "out" / "app.schema.json"

    result = runner.invoke(app, ["schema", "--out", str(out)])

    assert result.exit_code == 0
    assert out.read_text(encoding="utf-8") == json_schema_text()
