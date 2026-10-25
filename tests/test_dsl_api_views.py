"""The views of API data in the DSL: a view with `source` (ADR 0022)."""

from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, load_definition_text
from appgen.dsl.ui.api_data import api_data
from appgen.dsl.ui.views import ApiCardsView, ApiDetailView, ApiTableView
from appgen.dsl.validator import validate_definition

FIXTURE = Path(__file__).parent / "fixtures" / "api-views.yaml"
TEXT = FIXTURE.read_text()


def load(text: str = TEXT) -> AppDefinition:
    return load_definition_text(text, str(FIXTURE))


def changed(old: str, new: str) -> str:
    assert old in TEXT, old
    return TEXT.replace(old, new, 1)


def problems(text: str) -> list[tuple[str, str | None, str]]:
    return [(d.code, d.element_id, d.message) for d in validate_definition(load(text))]


def errors(text: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(text)
    return caught.value.diagnostics


def test_the_fixture_is_valid() -> None:
    assert problems(TEXT) == []


def test_a_view_with_a_source_is_a_view_of_api_data() -> None:
    definition = load()
    assert definition.ui is not None
    views = definition.ui.views
    table = views["book_table"]
    assert isinstance(table, ApiTableView)
    assert (table.api, table.operation) == ("books", "listBooks")
    assert table.params == {"genre": "fiction", "limit": 50}
    assert table.items == "data.items"
    assert table.columns["author"].field == "author.name"
    assert table.columns["author"].id == "ui.views.book_table.columns.author"
    assert isinstance(views["author_books"], ApiCardsView)
    detail = views["book_detail"]
    assert isinstance(detail, ApiDetailView)
    assert detail.params == {"isbn": "$route.isbn"}
    data = api_data(definition, table)
    assert data is not None and data.item is not None
    assert data.operation.id == "listBooks"


def test_a_view_has_an_entity_or_a_source_not_both() -> None:
    text = changed(
        "      kind: table\n      source: apis.books.operations.listBooks\n",
        "      kind: table\n      entity: Note\n      source: apis.books.operations.listBooks\n",
    )
    [diagnostic] = errors(text)
    assert diagnostic.message == ("A view has an entity or a source, not both (key 'entity').")


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("row_actions: {}", "A view of API data has no row actions: its items are not records"),
        ("selection: true", "A view of API data has no selection"),
        ("actions: {}", "A view of API data has no actions"),
    ],
)
def test_a_view_of_api_data_has_no_actions_of_records(key: str, reason: str) -> None:
    text = changed(
        "      items: data.items\n      columns:",
        f"      {key}\n      items: data.items\n      columns:",
    )
    [diagnostic] = errors(text)
    assert diagnostic.message.startswith(reason)


def test_a_view_of_api_data_has_only_search_filters() -> None:
    text = changed(
        "search: { kind: search, label: Search books, fields: [title, author.name] }",
        "format: { kind: select, field: format }",
    )
    assert errors(text)


def test_a_board_cannot_have_a_source() -> None:
    text = changed("    author_books:\n      kind: cards", "    author_books:\n      kind: board")
    [diagnostic] = errors(text)
    assert diagnostic.message.startswith(
        "The kind 'board' of a view with 'source' is not valid. Expected 'table', 'cards', "
        "'detail'."
    )


@pytest.mark.parametrize(
    ("old", "new", "code", "element_id", "message"),
    [
        (
            "source: apis.books.operations.listBooks\n      params: { genre",
            "source: apis.novels.operations.listBooks\n      params: { genre",
            "unknown-reference",
            "ui.views.book_table",
            "The API 'novels' does not exist.",
        ),
        (
            "source: apis.books.operations.getBook",
            "source: apis.books.operations.getBooks",
            "unknown-reference",
            "ui.views.book_detail",
            "The API 'books' has no operation 'getBooks' in its 'operations'.",
        ),
        (
            "params: { genre: fiction, limit: 50 }",
            "params: { genre: fiction, limit: 50, size: 3 }",
            "unknown-reference",
            "ui.views.book_table",
            "The operation 'listBooks' has no parameter 'size'.",
        ),
        (
            "params: { genre: fiction, limit: 50 }",
            "params: { genre: poetry, limit: 50 }",
            "invalid-value",
            "ui.views.book_table",
            "The value \"poetry\" of the parameter 'genre' does not match the schema of the "
            "parameter in the document of the API 'books'.",
        ),
        (
            "params: { genre: fiction, limit: 50 }",
            "params: { genre: fiction, limit: fifty }",
            "invalid-value",
            "ui.views.book_table",
            "The value \"fifty\" of the parameter 'limit' does not match the schema of the "
            "parameter in the document of the API 'books'.",
        ),
        (
            "params: { isbn: $route.isbn }",
            "params: { isbn: $page.isbn }",
            "invalid-value",
            "ui.views.book_detail",
            "The value '$page.isbn' of the parameter 'isbn' is not valid. A value that starts "
            "with '$' must be '$route.<name>', a path parameter of the page.",
        ),
        (
            "params: { isbn: $route.isbn }",
            "params: {}",
            "missing-key",
            "ui.views.book_detail",
            "The operation 'getBook' needs the parameter 'isbn'.",
        ),
        (
            "      items: data.items\n      columns:",
            "      columns:",
            "unsuitable-operation",
            "ui.views.book_table",
            "A table needs an answer that is a list of objects, but the operation 'listBooks' "
            "does not give it.",
        ),
        (
            "      items: data.items\n      columns:",
            "      items: data.total\n      columns:",
            "unsuitable-operation",
            "ui.views.book_table",
            "A table needs an answer with a list of objects in the property 'data.total', but "
            "the operation 'listBooks' does not give it.",
        ),
        (
            "source: apis.books.operations.getBook",
            "source: apis.books.operations.listAuthorBooks",
            "unsuitable-operation",
            "ui.views.book_detail",
            "A detail view needs an answer that is an object, but the operation "
            "'listAuthorBooks' does not give it.",
        ),
        (
            "author: { field: author.name, label: Author }",
            "author: { field: author.nam, label: Author }",
            "unknown-reference",
            "ui.views.book_table.columns.author",
            "The items of 'listBooks' have no property 'author.nam'.",
        ),
        (
            "author: { field: author.name, label: Author }",
            "author: { field: author, label: Author }",
            "unsuitable-field",
            "ui.views.book_table.columns.author",
            "The property 'author' of the items of 'listBooks' is an object. A view shows a "
            "text, a number, a boolean, or a list of these.",
        ),
        (
            "fields: [isbn, published, pages, format]",
            "fields: [isbn, released]",
            "unknown-reference",
            "ui.views.book_detail.sections.facts",
            "The answer of 'getBook' has no property 'released'.",
        ),
        (
            "sort: { field: published, direction: desc }",
            "sort: { field: date, direction: desc }",
            "unknown-reference",
            "ui.views.book_table.sort",
            "The items of 'listBooks' have no property 'date'.",
        ),
    ],
)
def test_the_validator_checks_the_operation_and_the_properties(
    old: str, new: str, code: str, element_id: str, message: str
) -> None:
    found = problems(changed(old, new))
    assert (code, element_id, message) in found, found


def test_an_operation_with_a_body_cannot_be_the_source() -> None:
    text = changed(
        "operations: [listBooks, getBook, listAuthorBooks]",
        "operations: [listBooks, getBook, listAuthorBooks, createBook]",
    ).replace("source: apis.books.operations.getBook", "source: apis.books.operations.createBook")
    text = text.replace("params: { isbn: $route.isbn }", "params: {}")
    assert (
        "unsuitable-operation",
        "ui.views.book_detail",
        "The operation 'createBook' has a body, but a view sends no body.",
    ) in problems(text)


def test_a_route_parameter_must_be_in_the_path_of_the_page() -> None:
    text = changed('path: "/books/{isbn}"', 'path: "/books/{id}"')
    found = [p for p in problems(text) if p[0] == "unsuitable-view"]
    assert len(found) == 1
    assert found[0][1] == "pages.book.content"
    assert "isbn" in found[0][2]


def test_a_page_of_api_data_has_no_entity() -> None:
    text = changed(
        "    title: Books\n    content: { view: book_table }",
        "    title: Books\n    entity: Note\n    content: { view: book_table }",
    )
    found = [p for p in problems(text) if p[0] == "unsuitable-view"]
    assert [p[1] for p in found] == ["pages.books.content"]
