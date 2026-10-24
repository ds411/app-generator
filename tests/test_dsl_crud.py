"""Tests of the CRUD shorthand of an entity (`appgen.dsl.crud`, ADR 0008)."""

import re
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.dsl import DefinitionError, load_definition_text, validate_definition
from appgen.dsl.crud import operation_names, plural, snake_name
from appgen.gen import find_binding, generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Category:
        crud: true
        display_field: name
        fields:
          name: { type: string, required: true }
          notes: { type: text }
      StockItem:
        crud:
          operations: [create, read, update, list]
          views: [table, detail]
          forms: [create, update]
        fields:
          sku: { type: string, required: true }
          count: { type: integer }
        relations:
          category: { kind: many_to_one, target: Category }
    """
)


def test_the_names_follow_the_entity_and_its_plural_label() -> None:
    assert snake_name("StockItem") == "stock_item"
    assert [plural(n) for n in ("box", "city", "day", "task")] == [
        "boxes",
        "cities",
        "days",
        "tasks",
    ]
    assert operation_names("Person", {"plural_label": "People"})["list"] == "list_people"
    assert operation_names("StockItem", {})["read"] == "read_stock_item"


def test_true_gives_all_operations() -> None:
    definition = load_definition_text(BASE)

    operations = {n: (o.kind, o.entity) for n, o in definition.operations.items()}
    assert operations == {
        "create_category": ("create", "Category"),
        "read_category": ("read", "Category"),
        "update_category": ("update", "Category"),
        "delete_category": ("delete", "Category"),
        "list_categories": ("list", "Category"),
        "create_stock_item": ("create", "StockItem"),
        "read_stock_item": ("read", "StockItem"),
        "update_stock_item": ("update", "StockItem"),
        "list_stock_items": ("list", "StockItem"),
    }
    assert definition.find("operations.list_categories") is definition.operations["list_categories"]
    assert validate_definition(definition) == []


def test_the_mapping_gives_default_views_and_forms() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.ui is not None

    table = definition.ui.views["stock_item_table"]
    detail = definition.ui.views["stock_item_detail"]
    assert table.kind == "table" and list(table.columns) == ["sku", "count", "category"]
    assert detail.kind == "detail" and detail.sections["details"].fields == [
        "sku",
        "count",
        "category",
    ]
    forms = definition.ui.forms
    assert (forms["new_stock_item"].operation, forms["edit_stock_item"].operation) == (
        "create_stock_item",
        "update_stock_item",
    )
    assert list(forms["new_stock_item"].fields) == ["sku", "count", "category"]
    # Each expanded element points to the `crud` key of its entity.
    assert str(forms["new_stock_item"].location) == "app.yaml:11:5"
    assert str(definition.operations["list_categories"].location) == "app.yaml:5:5"


def test_an_explicit_element_wins_over_the_shorthand() -> None:
    text = (
        BASE + "operations:\n  read_category: { kind: read, entity: Category, description: Own. }\n"
    )

    definition = load_definition_text(text)

    assert definition.operations["read_category"].description == "Own."
    assert len(definition.operations) == 9


def test_an_unknown_operation_in_the_shorthand_is_an_error() -> None:
    with pytest.raises(DefinitionError) as error:
        load_definition_text(BASE.replace("crud: true", "crud: [create, show]"))

    [diagnostic] = error.value.diagnostics
    assert diagnostic.code == "invalid-value"
    assert diagnostic.element_id == "entities.Category.crud"
    assert "'show'" in diagnostic.message


def _explicit(text: str) -> str:
    """Return the project tracker with explicit operations in the order of the expansion."""
    definition = load_definition_text(text)
    lines = [
        f"  {name}: {{ kind: {op.kind}, entity: {op.entity} }}\n"
        for name, op in definition.operations.items()
        if op.kind != "custom"
    ]
    text = re.sub(r"\n    crud: [^\n]*", "", text)
    assert "crud" not in text
    return text.replace("\noperations:\n", "\noperations:\n" + "".join(lines), 1)


@pytest.mark.parametrize("binding", ["react", "fastapi"])
def test_the_shorthand_and_the_explicit_form_generate_the_same_code(binding: str) -> None:
    text = EXAMPLE.read_text()
    shorthand = load_definition_text(text)
    explicit = load_definition_text(_explicit(text))
    assert [e for e in explicit.elements] == [e for e in shorthand.elements]

    first = generate(shorthand, find_binding(binding))
    second = generate(explicit, find_binding(binding))

    assert [(f.path, f.content) for f in first.files] == [(f.path, f.content) for f in second.files]
