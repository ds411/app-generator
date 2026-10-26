"""The daily snapshots of the stat widgets (ADR 0042): the check, the built-in job of the
FastAPI and the Next.js apps, and the charts of the front ends."""

from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.ui.dashboards import ChartWidget, StatWidget
from appgen.gen import Binding
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

BASE = dedent(
    """\
    version: 0
    app: { name: sprint, title: Sprint }
    entities:
      Task:
        crud: [create, list]
        display_field: title
        fields:
          title: { type: string, required: true }
          points: { type: integer }
          due_on: { type: date }
          status: { type: enum, values: [open, done], default: open }
        relations:
          sprint: { kind: many_to_one, target: Sprint }
      Sprint:
        crud: [create, list]
        display_field: name
        fields:
          name: { type: string, required: true }
          goal: { type: integer }
    ui:
      dashboards:
        overview:
          widgets:
            open_points:
              kind: stat
              entity: Task
              aggregate: sum
              field: points
              filter: { status: open, due_on: { gte: $today } }
              snapshots: daily
            burndown:
              kind: chart
              chart: line
              snapshots: open_points
              days: 14
    pages:
      overview: { path: /, title: Overview, content: { dashboard: overview } }
    """
)
API = BASE.replace("title: Sprint }", "title: Sprint, x-react-data: api }")


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def chart(extra: str) -> str:
    """Return the definition with more keys on the chart of snapshots."""
    return BASE.replace(f"{W}days: 14\n", f"{W}days: 14\n{W}{extra}\n")


W = " " * 10
"""The indent of the keys of a widget in `BASE`."""
BURNDOWN = "ui.dashboards.overview.widgets.burndown"
OPEN_POINTS = "ui.dashboards.overview.widgets.open_points"


def test_a_line_chart_shows_the_snapshots_of_a_stat() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.ui is not None
    widgets = definition.ui.dashboards["overview"].widgets
    stat, burndown = widgets["open_points"], widgets["burndown"]
    assert isinstance(stat, StatWidget) and stat.snapshots == "daily"
    assert isinstance(burndown, ChartWidget)
    assert (burndown.snapshots, burndown.days, burndown.entity) == ("open_points", 14, None)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("entity: Task", "invalid-option"),
        ("filter: { status: open }", "invalid-option"),
        ("interval: day", "invalid-option"),
    ],
)
def test_a_chart_of_snapshots_takes_no_keys_of_a_chart_of_records(change: str, code: str) -> None:
    assert codes(chart(change)) == [(code, BURNDOWN)]


def test_a_chart_of_snapshots_is_a_line_chart() -> None:
    text = BASE.replace(f"chart: line\n{W}snapshots", f"chart: bar\n{W}snapshots")
    assert codes(text) == [("invalid-value", BURNDOWN)]


def test_a_chart_of_snapshots_names_a_stat_with_snapshots() -> None:
    unknown = BASE.replace("snapshots: open_points", "snapshots: closed_points")
    assert [code for code, _ in codes(unknown)] == ["unknown-reference"]
    without = BASE.replace(f"{W}snapshots: daily\n", "")
    assert codes(without) == [("unknown-reference", BURNDOWN)]


def test_a_chart_of_records_needs_an_entity_and_a_group() -> None:
    text = BASE.replace(f"snapshots: open_points\n{W}days: 14\n", "entity: Task\n")
    assert codes(text) == [("missing-key", BURNDOWN)]
    days = BASE.replace(
        f"snapshots: open_points\n{W}days: 14\n", f"entity: Task\n{W}group_by: status\n"
    ).replace("chart: line", "chart: bar")
    assert codes(days) == []
    days = days.replace("group_by: status\n", f"group_by: status\n{W}days: 7\n")
    assert codes(days) == [("invalid-option", BURNDOWN)]


def test_a_stat_with_snapshots_has_no_record_rule() -> None:
    access = dedent(
        """\
        auth: { user_entity: Person, username_field: email }
        access:
          role_field: role
          roles:
            admin: { operations: ["*"], pages: ["*"] }
            member:
              operations: [list_tasks, create_task]
              records:
                Task: { owner: owner }
        """
    )
    text = BASE.replace(
        "      sprint: { kind: many_to_one, target: Sprint }\n",
        "      sprint: { kind: many_to_one, target: Sprint }\n"
        "      owner: { kind: many_to_one, target: Person }\n",
    ).replace(
        "  Sprint:\n",
        "  Person:\n"
        "    crud: [list]\n"
        "    display_field: email\n"
        "    fields:\n"
        "      email: { type: string, required: true, unique: true }\n"
        "      role: { type: enum, values: [admin, member], default: member }\n"
        "  Sprint:\n",
    )
    assert codes(text + access) == [("invalid-option", OPEN_POINTS)]


def test_the_snapshots_have_no_period() -> None:
    assert codes(chart("period_field: due_on")) == [("invalid-option", BURNDOWN)]
    period = BASE.replace(
        "      widgets:\n", "      period: { default: last_30_days }\n      widgets:\n"
    ).replace(f"{W}snapshots: daily\n", f"{W}period_field: due_on\n{W}snapshots: daily\n")
    assert codes(period) == [("invalid-option", OPEN_POINTS)]


def test_the_fastapi_app_stores_the_values_with_a_built_in_job() -> None:
    files = files_of(BASE, fastapi.BINDING)
    module = files["app/features/dashboards/overview.py"]
    assert "async def overview_open_points_value(session: AsyncSession, day: dt.date)" in module
    assert "value = await overview_open_points_value(session, today or utc_today())" in module
    assert 'StatSnapshot.widget == "open_points"' in module
    assert "StatSnapshot.day > day - dt.timedelta(days=14)" in module
    job = files["app/jobs/stat_snapshots.py"]
    assert "value = await overview_open_points_value(session, day)" in job
    assert 'await store_snapshot(session, "overview", "open_points", day, value)' in job
    assert '"stat_snapshots": stat_snapshots.run,' in files["app/worker.py"]
    assert "class StatSnapshot(Base):" in files["app/core/snapshots.py"]
    assert '"stat_snapshots",' in files["migrations/versions/0001_schema.py"]
    assert "StatSnapshot" in files["app/models.py"]
    test = files["tests/jobs/test_stat_snapshots.py"]
    assert "async def test_the_chart_overview_burndown_shows_the_stored_values(" in test
    assert "| `stat_snapshots` | The schedule `0 0 * * *` |" in files["README.md"]
    # Without a stat with snapshots, the app has no job.
    plain = files_of(
        BASE.replace(f"{W}snapshots: daily\n", "").replace(
            f"chart: line\n{W}snapshots: open_points\n{W}days: 14\n",
            f"chart: bar\n{W}entity: Task\n{W}group_by: status\n",
        ),
        fastapi.BINDING,
    )
    assert "app/worker.py" not in plain
    assert "app/core/snapshots.py" not in plain


def test_the_next_js_app_stores_the_values_with_a_route_of_the_job() -> None:
    files = files_of(BASE, nextjs.BINDING)
    job = files["src/app/jobs/stat-snapshots.ts"]
    assert "async function overviewOpenPoints(now: Date): Promise<number | null> {" in job
    assert "const today = dateOf(now);" in job
    assert "sum(taskTable.points)" in job
    assert "return Number(rows[0]?.value ?? 0);" in job
    route = files["app/api/jobs/stat_snapshots/route.ts"]
    assert 'handleJob(request, "stat_snapshots", runStatSnapshots)' in route
    actions = files["src/shared/api/snapshot-actions.ts"]
    assert "export async function overviewBurndownAction(today: string)" in actions
    assert 'readSnapshots("overview", "open_points", 14, daySchema.parse(today))' in actions
    assert 'export * from "./stat-snapshots";' in files["src/shared/db/schema/index.ts"]
    dashboard = files["src/widgets/overview/ui/overview-dashboard.tsx"]
    assert "overviewBurndownAction(today())," in dashboard
    assert "return snapshotData(data.snapshots.burndown, today(), 14);" in dashboard
    assert "for job in stat_snapshots; do" in files["compose.yaml"]


def test_the_react_app_shows_the_value_of_today_or_the_values_of_the_api() -> None:
    files = files_of(BASE, react.BINDING)
    dashboard = files["src/widgets/overview/ui/overview-dashboard.tsx"]
    body = "return snapshotData([{ key: today(), value: openPoints(data) }], today(), 14);"
    assert body in dashboard
    assert "export function snapshotData(" in files["src/shared/lib/aggregate.ts"]
    api = files_of(API, react.BINDING)["src/widgets/overview/ui/overview-dashboard.tsx"]
    assert 'chartValues("/dashboards/overview/burndown", { today: today() }),' in api
    assert "return snapshotData(data.burndown, today(), 14);" in api


def test_the_next_js_app_needs_a_stored_field_of_the_entity() -> None:
    text = BASE.replace("field: points", "field: sprint.goal")
    assert codes(text) == []
    with pytest.raises(GenerationError, match="stored field of 'Task'"):
        files_of(text, nextjs.BINDING)
    # The FastAPI app joins the related records.
    assert "app/jobs/stat_snapshots.py" in files_of(text, fastapi.BINDING)


@pytest.mark.parametrize("binding", [fastapi.BINDING, nextjs.BINDING])
def test_the_names_of_the_job_and_of_the_table_are_taken(binding: Binding) -> None:
    job = BASE + 'jobs:\n  stat_snapshots: { schedule: "@daily" }\n'
    with pytest.raises(GenerationError, match="built-in job"):
        files_of(job, binding)
    if binding is fastapi.BINDING:
        table = BASE.replace("  Sprint:\n", "  Sprint:\n    x-fastapi-table: stat_snapshots\n")
    else:
        # The Next.js app names the table after the entity.
        table = BASE.replace(
            "  Sprint:\n",
            "  StatSnapshots:\n    crud: [list]\n"
            "    fields:\n      name: { type: string }\n  Sprint:\n",
        )
    with pytest.raises(GenerationError, match="table 'stat_snapshots'"):
        files_of(table, binding)
