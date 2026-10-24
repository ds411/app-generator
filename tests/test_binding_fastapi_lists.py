"""Tests of the list endpoints of the FastAPI binding: the filters, the search, and the sort.

The parameters come from the views of the definition. The pre-push hook
runs the generated tests of the project tracker on Postgres and on SQLite
(`scripts/check-fastapi.sh`). These tests check the generated code only.
"""

from pathlib import Path

import pytest

from appgen.bindings.fastapi.model import python_app
from appgen.bindings.fastapi.queries import Call, render
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen import Binding, GenerationResult, find_binding, generate
from appgen.gen.render import GenerationError

TESTS = Path(__file__).parent
VIEWS = TESTS / "fixtures" / "react-views.yaml"
TRACKER = TESTS.parent / "examples" / "project-tracker" / "app.yaml"


@pytest.fixture(scope="module")
def fastapi() -> Binding:
    return find_binding("fastapi")


@pytest.fixture(scope="module")
def views() -> AppDefinition:
    return load_definition(VIEWS)


@pytest.fixture(scope="module")
def result(views: AppDefinition, fastapi: Binding) -> GenerationResult:
    return generate(views, fastapi)


def _file(result: GenerationResult, path: str) -> str:
    return next(f.content for f in result.files if f.path == path)


def test_a_select_filter_makes_the_parameter_a_list(result: GenerationResult) -> None:
    code = _file(result, "app/features/items/list_items.py")

    assert (
        "    # @trace ui.views.item_table.filters.stage\n    stage: list[ItemStage] | None" in code
    )
    assert "statement = statement.where(Item.stage.in_(query.stage))" in code
    assert "owner_id: list[UUID] | None = None" in code
    assert "statement = statement.where(Item.owner_id.in_(query.owner_id))" in code
    assert "statement = statement.where(Item.tags.any(Member.id.in_(query.tag_ids)))" in code


def test_the_equality_filters_of_the_fields_stay(result: GenerationResult) -> None:
    code = _file(result, "app/features/items/list_items.py")

    assert "    # @trace entities.Item.fields.code\n    code: str | None = None" in code
    assert "statement = statement.where(Item.code == query.code)" in code
    assert "in_stock: bool | None = None" in code


def test_a_field_path_goes_through_the_relations(result: GenerationResult) -> None:
    code = _file(result, "app/features/items/list_items.py")

    assert 'owner__team_id: list[UUID] | None = Field(default=None, alias="owner.team_id")' in code
    assert "Item.owner.has(Member.team_id.in_(query.owner__team_id))" in code


def test_a_date_range_filter_adds_two_parameters(result: GenerationResult) -> None:
    code = _file(result, "app/features/items/list_items.py")

    assert "received_from: dt.date | None" in code
    assert "received_to: dt.date | None" in code
    assert "statement = statement.where(Item.received >= query.received_from)" in code
    assert "statement = statement.where(Item.received <= query.received_to)" in code


def test_a_date_range_on_a_date_time_field_covers_whole_days(fastapi: Binding) -> None:
    text = VIEWS.read_text().replace(
        "        received: { kind: date_range, field: received }\n",
        "        received: { kind: date_range, field: updated_at }\n",
    )
    code = _file(generate(load_definition_text(text), fastapi), "app/features/items/list_items.py")

    assert "Item.updated_at >= day_start(query.updated_at_from)" in code
    assert "Item.updated_at < day_start(query.updated_at_to, 1)" in code


def test_the_search_takes_the_fields_of_all_search_filters(result: GenerationResult) -> None:
    code = _file(result, "app/features/items/list_items.py")

    assert "    # @trace ui.views.item_table.filters.search\n" in code
    assert "    # @trace ui.views.item_cards.filters.search\n    q: str | None = Field(" in code
    assert "    for word in search_words(query.q):\n" in code
    assert "                contains(Item.code, word),\n" in code
    assert "                contains(Item.notes, word),\n" in code
    assert "                Item.owner.has(contains(Member.name, word)),\n" in code


def test_the_sort_keys_come_from_the_fields_and_the_views(result: GenerationResult) -> None:
    code = _file(result, "app/features/items/list_items.py")
    query = python_app(load_definition(VIEWS)).entity("Item").query

    keys = [k.name for k in query.sort_keys]
    assert keys[:4] == ["code", "kind", "stage", "price"]
    assert {"owner.name", "owner", "owner.team.lead.name", "owner.email"} <= set(keys)
    # A relation to many records has no column to sort by.
    assert "tags" not in keys
    assert "    # @trace ui.views.item_table.sort\n" in code
    assert '"owner": lookup(_owner.name, _owner.id == Item.owner_id),' in code
    assert "_owner_team_lead = aliased(Member)" in code
    assert "        _owner_team_lead.id == _owner_team.lead_id,\n" in code


def test_a_computed_field_has_no_sort_key(fastapi: Binding) -> None:
    text = VIEWS.read_text()
    text = text.replace(
        "      notes: { type: text }\n",
        "      notes: { type: text }\n      total: { type: decimal, computed: price * count }\n",
    )
    text = text.replace("        count: { format: number }\n", "        total: {}\n")
    query = python_app(load_definition_text(text)).entity("Item").query

    keys = [k.name for k in query.sort_keys]

    assert "total" not in keys
    assert "received" in keys


def test_each_list_endpoint_with_views_has_tests_of_its_query(result: GenerationResult) -> None:
    tests = _file(result, "tests/features/items/test_list_items_query.py")
    paths = {f.path for f in result.files}

    assert "async def test_list_items_filters_by_stage(" in tests
    assert "async def test_list_items_filters_by_a_range_of_received(" in tests
    assert "async def test_list_items_searches_the_records(" in tests
    assert "async def test_list_items_searches_the_related_records(" in tests
    assert "async def test_list_items_sorts_by_a_field(" in tests
    assert "async def test_list_items_sorts_by_owner(" in tests
    assert "tests/ordering.py" in paths


def test_an_entity_without_views_has_no_tests_of_a_query(fastapi: Binding) -> None:
    result = generate(load_definition(TESTS / "fixtures" / "project-tracker.yaml"), fastapi)
    paths = {f.path for f in result.files}

    assert "tests/features/tasks/test_list_tasks.py" in paths
    assert "tests/features/tasks/test_list_tasks_query.py" not in paths
    assert "tests/ordering.py" not in paths


def test_a_tab_of_a_many_to_many_relation_adds_the_ids_to_its_target(fastapi: Binding) -> None:
    result = generate(load_definition(TRACKER), fastapi)
    code = _file(result, "app/features/people/list_people.py")
    tests = _file(result, "tests/features/people/test_list_people_query.py")

    assert "    # @trace ui.views.project_detail.tabs.members\n    id: list[UUID] | None" in code
    assert "statement = statement.where(Person.id.in_(query.id))" in code
    assert "async def test_list_people_filters_by_id(" in tests
    # A tab of a one_to_many relation uses the foreign key of the inverse relation.
    assert "    id: list[UUID]" not in _file(result, "app/features/tasks/list_tasks.py")


def test_the_generated_python_compiles(result: GenerationResult) -> None:
    for f in result.files:
        if f.path.endswith(".py"):
            compile(f.content, f.path, "exec")


def test_two_parameters_with_the_same_name_stop_the_run(fastapi: Binding) -> None:
    text = VIEWS.read_text().replace(
        "      notes: { type: text }\n", "      notes: { type: text }\n      q: { type: string }\n"
    )

    with pytest.raises(GenerationError, match="two query parameters 'q'"):
        generate(load_definition_text(text), fastapi)


def test_render_puts_a_long_call_on_many_lines() -> None:
    short = Call("or_", ("a", "b"))
    long = Call("or_", tuple(f"contains(Entity.field_{i}, word)" for i in range(4)))

    assert render(short, 8, "x = ") == "x = or_(a, b)"
    assert render(long, 4, "x = ") == (
        "x = or_(\n"
        "        contains(Entity.field_0, word),\n"
        "        contains(Entity.field_1, word),\n"
        "        contains(Entity.field_2, word),\n"
        "        contains(Entity.field_3, word),\n"
        "    )"
    )
