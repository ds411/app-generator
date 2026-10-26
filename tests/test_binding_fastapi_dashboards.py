"""Tests of the dashboard endpoints of the FastAPI binding: one endpoint for each widget.

The pre-push hook runs the generated tests of the examples on Postgres and
on SQLite (`scripts/check-fastapi.sh`): they check the value of each
widget from known records. These tests check the generated code only.
"""

from pathlib import Path

import pytest

from appgen.bindings.fastapi.model import python_app
from appgen.dsl import load_definition, load_definition_text
from appgen.gen import Binding, GenerationResult, find_binding, generate
from appgen.gen.render import GenerationError

TESTS = Path(__file__).parent
VIEWS = TESTS / "fixtures" / "react-views.yaml"
EXAMPLES = TESTS.parent / "examples"

# The widgets of a dashboard for the entities of the views fixture: each
# filter operator, a field path through relations, the groups, and a list.
DASHBOARD = """\
  dashboards:
    board:
      widgets:
        not_closed:
          kind: stat
          entity: Item
          filter: { stage: { ne: closed }, kind: [book], in_stock: true, count: [2, null] }
        old:
          kind: stat
          entity: Item
          aggregate: avg
          field: price
          filter: { received: { lt: $today }, updated_at: { gte: $today }, count: { not_in: [1] } }
        team_items:
          kind: stat
          entity: Item
          aggregate: max
          field: count
          filter: { owner.team.name: Core, tags: { eq: 00000000-0000-4000-8000-000000000001 } }
        by_month:
          kind: chart
          chart: line
          entity: Item
          group_by: updated_at
        by_owner:
          kind: chart
          chart: bar
          entity: Item
          group_by: owner
          aggregate: sum
          field: price
        latest:
          kind: list
          view: item_table
          sort: { field: updated_at, direction: desc }
          limit: 3
"""


@pytest.fixture(scope="module")
def fastapi() -> Binding:
    return find_binding("fastapi")


def _definition_text(dashboard: str = DASHBOARD) -> str:
    return VIEWS.read_text() + dashboard


@pytest.fixture(scope="module")
def result(fastapi: Binding) -> GenerationResult:
    return generate(load_definition_text(_definition_text()), fastapi)


def _file(result: GenerationResult, path: str) -> str:
    return next(f.content for f in result.files if f.path == path)


def test_each_widget_has_an_endpoint_in_the_slice_of_the_dashboards(
    result: GenerationResult,
) -> None:
    paths = {f.path for f in result.files}
    assert {
        "app/features/dashboards/__init__.py",
        "app/features/dashboards/router.py",
        "app/features/dashboards/schemas.py",
        "app/features/dashboards/aggregates.py",
        "app/features/dashboards/board.py",
        "tests/features/dashboards/test_board.py",
    } <= paths
    code = _file(result, "app/features/dashboards/board.py")
    assert 'router = APIRouter(prefix="/dashboards/board")' in code
    assert '    "/not-closed",\n' in code
    assert '    operation_id="board_not_closed",\n' in code
    assert "async def board_by_owner(session: SessionDep) -> ChartValues:" in code
    assert "async def board_latest(session: SessionDep) -> list[ItemRead]:" in code
    main = _file(result, "app/main.py")
    assert "from app.features.dashboards.router import router as dashboards_router" in main
    assert "    app.include_router(dashboards_router)\n" in main
    openapi = _file(result, "tests/test_openapi.py")
    assert '    ("get", "/dashboards/board/by-month"),\n' in openapi
    assert '    "StatValue",\n' in openapi


def test_a_filter_has_the_semantics_of_the_browser(result: GenerationResult) -> None:
    code = _file(result, "app/features/dashboards/board.py")

    # An empty value is not equal to a value: `ne` keeps the empty values.
    assert "statement.where(or_(Item.stage.is_(None), Item.stage != ItemStage.CLOSED))" in code
    assert "statement.where(Item.kind.in_([ItemKind.BOOK]))" in code
    assert "statement.where(or_(Item.count.is_(None), Item.count.in_([2])))" in code
    assert "statement.where(Item.in_stock.is_(True))" in code
    assert "statement.where(or_(Item.count.is_(None), Item.count.not_in([1])))" in code
    # `$today` is the parameter of the endpoint, and a date-time compares by the day in UTC.
    assert "today: Today = None" in code
    assert "    day = today or utc_today()\n" in code
    assert "statement.where(Item.received < day)" in code
    assert "statement.where(Item.updated_at >= day_start(day))" in code


def test_a_field_path_joins_the_related_records(result: GenerationResult) -> None:
    code = _file(result, "app/features/dashboards/board.py")

    assert "_item_owner = aliased(Member)" in code
    assert "_item_owner_team = aliased(Team)" in code
    assert "statement.outerjoin(_item_owner, _item_owner.id == Item.owner_id)" in code
    assert (
        "statement.outerjoin(_item_owner_team, _item_owner_team.id == _item_owner.team_id)" in code
    )
    assert 'statement.where(_item_owner_team.name == "Core")' in code
    assert "Item.tags.any(Member.id.in_([UUID(" in code
    assert "value = func.max(Item.count)" in code


def test_a_chart_groups_by_a_month_or_a_relation(result: GenerationResult) -> None:
    code = _file(result, "app/features/dashboards/board.py")

    assert '    key = interval_of(session, Item.updated_at, "month", utc=True)\n' in code
    assert "    key = Item.owner_id\n" in code
    assert "    value = func.coalesce(func.sum(Item.price), 0)\n" in code
    assert "statement = select(key, value).select_from(Item).group_by(key)" in code
    assert "return chart_values(await session.execute(statement))" in code


def test_a_list_gives_its_first_records_in_its_order(result: GenerationResult) -> None:
    code = _file(result, "app/features/dashboards/board.py")

    assert (
        "statement = statement.order_by(Item.updated_at.desc().nulls_last(), Item.id.asc())"
        ".limit(3)"
    ) in code
    assert "return [ItemRead.model_validate(record) for record in records]" in code


def test_the_generated_tests_check_the_values_of_known_records(
    result: GenerationResult,
) -> None:
    code = _file(result, "tests/features/dashboards/test_board.py")

    assert "async def test_board_not_closed_without_records(client: AsyncClient) -> None:" in code
    # An empty value in a filter has no generated value test.
    assert "test_board_not_closed_computes_its_value" not in code
    # Three records pass the filter, and each next record fails one path of it.
    assert "    records = [await make_item(session) for _ in range(6)]\n" in code
    assert "    records[0].received = dt.date(2026, 6, 12)\n" in code
    assert "    records[3].received = dt.date(2026, 6, 15)\n" in code
    assert "    records[5].count = 1\n" in code
    # The average of 1, 2, and 3, for the records that pass the filter.
    assert '    assert response.json() == {"value": 2.0}\n' in code
    assert 'params={"today": TODAY}' in code
    # A field path through relations has no generated value test.
    assert "test_board_team_items_computes_its_value" not in code
    assert "    expected = sorted([(str(parents[0].id), 1.0), (str(parents[1].id), 5.0)])\n" in code
    assert '    {"key": "2025-01", "value": 1.0},\n' in code
    assert "    ids = [str(records[i].id) for i in (0, 1, 2)]\n" in code


def test_a_widget_needs_the_list_operation_of_its_entity(fastapi: Binding) -> None:
    result = generate(load_definition(EXAMPLES / "room-booking" / "app.yaml"), fastapi)
    access = _file(result, "app/core/access.py")
    assert '    "overview_requested": "list_bookings",\n' in access
    assert "operation = NEEDS.get(str(operation), str(operation))" in access
    code = _file(result, "app/features/dashboards/overview.py")
    # The rooms are public: `list_rooms` is a public operation.
    rooms = code.split('operation_id="overview_rooms"')[1].split("@router")[0]
    assert "dependencies" not in rooms
    assert "dependencies=[Depends(check_access)]" in code
    assert 'Scope = Annotated[RecordScope | None, Depends(scope_of("read"))]' in code
    assert "    statement = booking_repository.owned(statement, scope)\n" in code
    tests = _file(result, "tests/features/dashboards/test_overview.py")
    assert "test_overview_requested_counts_only_the_records_of_the_role_member" in tests


def test_a_widget_of_a_computed_field_has_no_endpoint(fastapi: Binding) -> None:
    text = _definition_text(
        "  dashboards:\n    board:\n      widgets:\n"
        "        total: { kind: stat, entity: Item, aggregate: sum, field: price }\n"
    ).replace(
        "      price: { type: decimal }\n",
        "      price: { type: decimal, computed: count * 2 }\n",
    )
    with pytest.raises(GenerationError, match="computed field 'price'"):
        python_app(load_definition_text(text))


def test_an_entity_cannot_have_the_prefix_of_the_dashboards(fastapi: Binding) -> None:
    text = _definition_text().replace(
        "  Item:\n    fields:\n", "  Item:\n    x-fastapi-path: /dashboards\n    fields:\n"
    )
    with pytest.raises(GenerationError, match="the URL prefix of the dashboards"):
        python_app(load_definition_text(text))


def test_an_app_without_dashboards_has_no_slice_of_the_dashboards(fastapi: Binding) -> None:
    result = generate(load_definition(TESTS / "fixtures" / "project-tracker.yaml"), fastapi)
    assert not [f.path for f in result.files if "dashboards" in f.path]


def test_a_widget_reads_only_the_records_of_the_record_rules(fastapi: Binding) -> None:
    widgets = (
        "  dashboards:\n    overview:\n      widgets:\n"
        "        open_tasks: { kind: stat, entity: Task, filter: { status: { ne: done } } }\n"
        "        latest_tasks: { kind: list, view: task_table, limit: 5 }\n"
        "        teams: { kind: stat, entity: Team }\n"
    )
    text = (TESTS / "fixtures" / "record-rules.yaml").read_text()
    result = generate(
        load_definition_text(text.replace("\nauth:\n", f"\n{widgets}\nauth:\n")), fastapi
    )
    code = _file(result, "app/features/dashboards/overview.py")

    assert 'Scope = Annotated[RecordScope | None, Depends(scope_of("read"))]' in code
    assert "async def overview_open_tasks(session: SessionDep, scope: Scope) -> StatValue:" in code
    assert "    statement = task_repository.owned(statement, scope)\n" in code
    # A task embeds its project, which a record rule can hide.
    assert "    await task_repository.hide(session, items, scope)\n" in code
    # No record rule names the teams.
    assert "scope" not in code.split('operation_id="overview_teams"')[1]
    tests = _file(result, "tests/features/dashboards/test_overview.py")
    assert "    for _ in range(3):\n        await make_team(session)\n" in tests
