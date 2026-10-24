"""Tests of the check of the extension keys of the bindings in use (`appgen.gen.extensions`)."""

from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from appgen.cli import app
from appgen.dsl import load_definition_text
from appgen.gen import find_binding
from appgen.gen.extensions import check_extensions

TEXT = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        x-mock-count: 5
        fields:
          code: { type: string, x-example: A-1 }
        relations:
          lines: { kind: one_to_many, target: Line, inverse: order, x-fastapi-embed: true }
      Line:
        x-own-note: An author key that no binding reads.
        fields:
          count: { type: integer }
        relations:
          order: { kind: many_to_one, target: Order, inverse: lines }
    """
)


def check(text: str, *bindings: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    diagnostics = check_extensions(definition, [find_binding(b) for b in bindings])
    return [(d.code, d.element_id, str(d.location)) for d in diagnostics]


def test_the_declared_keys_with_valid_values_give_no_error() -> None:
    assert check(TEXT, "fastapi", "react", "nextjs") == []


def test_a_wrong_value_gives_its_file_and_line() -> None:
    text = TEXT.replace("x-fastapi-embed: true", 'x-fastapi-embed: "yes"')
    text = text.replace("x-mock-count: 5", "x-mock-count: 0")

    assert check(text, "fastapi", "react") == [
        ("invalid-value", "entities.Order", "app.yaml:5:19"),
        ("invalid-value", "entities.Order.relations.lines", "app.yaml:9:82"),
    ]


def test_a_key_on_the_wrong_element_kind_is_an_error() -> None:
    text = TEXT.replace("x-mock-count: 5", "x-fastapi-embed: true")

    [diagnostic] = check_extensions(load_definition_text(text), [find_binding("fastapi")])

    assert diagnostic.code == "invalid-option"
    assert diagnostic.message == (
        "The extension key 'x-fastapi-embed' of the binding 'fastapi' is for 'relation', "
        "not for 'entity'."
    )


def test_a_typo_in_a_key_of_a_binding_is_an_error() -> None:
    text = TEXT.replace("x-fastapi-embed", "x-fastapi-embedded").replace(
        "x-mock-count", "x-mock-cont"
    )
    definition = load_definition_text(text, "app.yaml")

    diagnostics = check_extensions(definition, [find_binding("fastapi"), find_binding("react")])

    assert [(d.code, d.hint) for d in diagnostics] == [
        ("unknown-key", "Did you mean 'x-mock-count'?"),
        ("unknown-key", "Did you mean 'x-fastapi-embed'?"),
    ]
    assert diagnostics[1].message == (
        "The extension key 'x-fastapi-embedded' is not a key of the binding 'fastapi'."
    )


def test_the_keys_of_a_binding_that_is_not_in_use_give_no_error() -> None:
    text = TEXT.replace("x-fastapi-embed: true", "x-fastapi-embed: 3")

    assert check(text, "react") == []
    assert check(text, "fastapi") != []


def test_validate_and_generate_report_the_keys(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(TEXT.replace("x-fastapi-embed: true", "x-fastapi-embed: 3"))
    runner = CliRunner()

    assert runner.invoke(app, ["validate", str(path)]).exit_code == 1
    assert runner.invoke(app, ["validate", str(path), "-b", "react"]).exit_code == 0
    result = runner.invoke(app, ["generate", str(path), "-b", "fastapi", "-o", str(tmp_path / "o")])
    assert result.exit_code == 1
    assert f"{path}:9:82:" in result.output
    assert not (tmp_path / "o").exists()


def test_the_naming_keys_of_fastapi_need_valid_names() -> None:
    keys = "x-fastapi-path: orders/all\n    x-fastapi-table: Orders"
    text = TEXT.replace("x-mock-count: 5", keys)
    valid = text.replace("orders/all", "/orders/all").replace("Orders", "order")

    assert [c[0] for c in check(text, "fastapi")] == ["invalid-value", "invalid-value"]
    assert check(valid, "fastapi") == []
