"""Tests of the full-text search of the FastAPI binding (`x-fastapi-search: fulltext`).

`scripts/check-fastapi.sh` runs the generated tests of the project tracker,
which has the full-text search, on Postgres and on SQLite, and
`scripts/check_full_text_search.py` adds the indexes to an app that exists.
These tests check the generated code only.
"""

import re
from pathlib import Path

import pytest

from appgen.bindings.fastapi.model import python_app
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen import Binding, GenerationResult, find_binding, generate
from appgen.gen.extensions import check_extensions

TESTS = Path(__file__).parent
FIXTURE = TESTS / "fixtures" / "project-tracker.yaml"
EXAMPLE = TESTS.parent / "examples" / "project-tracker" / "app.yaml"


@pytest.fixture(scope="module")
def fastapi() -> Binding:
    return find_binding("fastapi")


def _with_app_keys(path: Path, keys: str) -> AppDefinition:
    text = re.sub(r"(?m)^app:\n", f"app:\n{keys}", path.read_text(), count=1)
    return load_definition_text(text, str(path))


def _file(result: GenerationResult, path: str) -> str:
    return next(f.content for f in result.files if f.path == path)


@pytest.fixture(scope="module")
def result(fastapi: Binding) -> GenerationResult:
    return generate(_with_app_keys(FIXTURE, "  x-fastapi-search: fulltext\n"), fastapi)


def test_by_default_the_search_finds_each_word_with_like(fastapi: Binding) -> None:
    result = generate(load_definition(FIXTURE), fastapi)

    assert "app/core/search.py" not in {f.path for f in result.files}
    code = _file(result, "app/features/tasks/list_tasks.py")
    assert "    for word in search_words(query.q):\n" in code
    assert "full_text" not in code
    assert "rank" not in _file(result, "app/core/pagination.py")


def test_the_full_text_search_has_a_vector_and_a_rank_on_postgres(
    result: GenerationResult,
) -> None:
    code = _file(result, "app/features/tasks/list_tasks.py")

    assert "from app.core.search import full_text, matches, search_rank, search_vector" in code
    assert (
        "    rank = None\n"
        "    if query.q and full_text(session):\n"
        "        words = web_query(query.q)\n"
        "        vector = search_vector(Task.title)\n"
        "        statement = statement.where(or_(matches(vector, words)))\n"
        "        rank = search_rank(vector, words)\n"
        "    else:\n"
        "        for word in search_words(query.q):\n"
        "            statement = statement.where(or_(contains(Task.title, word)))\n"
    ) in code
    assert "    order = sort_order(query.sort, SORTABLE, Task.id, rank)\n" in code
    pagination = _file(result, "app/core/pagination.py")
    assert (
        "    if not terms and rank is not None:\n        terms.append(rank.desc())\n" in pagination
    )


def test_a_gin_index_on_postgres_has_the_vector_of_the_query(result: GenerationResult) -> None:
    models = _file(result, "app/features/tasks/models.py")
    assert (
        "Index(\n"
        '    "ix_tasks_search",\n'
        "    search_vector(Task.title),\n"
        '    postgresql_using="gin",\n'
        ').ddl_if(dialect="postgresql")\n'
    ) in models
    assert "from app.core.search import search_vector" in models
    migration = _file(result, "migrations/versions/0001_schema.py")
    assert (
        '    if op.get_bind().dialect.name == "postgresql":\n'
        "        # The GIN indexes of the full-text search (`x-fastapi-search: fulltext`).\n"
        "        vector = \"to_tsvector('simple'::regconfig, coalesce(\\\"name\\\", ''))\"\n"
        '        op.create_index("ix_projects_search", "projects", [sa.text(vector)], '
        'postgresql_using="gin")\n'
    ) in migration
    env = _file(result, "migrations/env.py")
    assert "        process_revision_directives=rewriter,\n" in env
    assert 'return PostgresOnly(op) if op.kw.get("postgresql_using") == "gin" else op' in env


def test_the_text_search_configuration_is_the_default_language(fastapi: Binding) -> None:
    assert python_app(_with_app_keys(FIXTURE, "  x-fastapi-search: fulltext\n")).search_config == (
        "simple"
    )
    assert python_app(load_definition(EXAMPLE)).search_config == "english"
    text = EXAMPLE.read_text().replace(
        "translations:\n  default: en\n", "translations:\n  default: de\n"
    )
    text = text.replace(
        "    de:\n      label: Deutsch\n", "    de:\n      label: Deutsch\n      locale: de-CH\n"
    )
    assert python_app(load_definition_text(text, str(EXAMPLE))).search_config == "german"
    assert python_app(load_definition(FIXTURE)).search_config is None


def test_a_field_of_a_related_record_has_its_own_vector(fastapi: Binding) -> None:
    result = generate(load_definition(EXAMPLE), fastapi)
    code = _file(result, "app/features/projects/list_projects.py")

    assert "        vector = search_vector(Project.name, Project.key)\n" in code
    assert (
        "                Project.owner.has(matches(search_vector(Person.name), words)),\n" in code
    )
    tests = _file(result, "tests/features/projects/test_list_projects_query.py")
    assert "async def test_list_projects_finds_the_words_in_the_order_of_their_rank(" in tests
    assert '    assert await found("report -draft") == [many]\n' in tests


@pytest.mark.parametrize("value", ["elastic", "true", "[fulltext]"])
def test_the_search_is_like_or_fulltext(fastapi: Binding, value: str) -> None:
    definition = _with_app_keys(FIXTURE, f"  x-fastapi-search: {value}\n")
    assert validate_definition(definition) == []
    codes = [d.code for d in check_extensions(definition, [fastapi])]
    assert codes == ["invalid-value"]
