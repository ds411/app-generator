"""The intervals of the charts of dates (`interval`): the check, the front ends, and the
endpoints of the FastAPI app."""

from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.ui.dashboards import ChartWidget
from appgen.gen import Binding
from appgen.gen.generator import generate

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        crud: [create, list]
        display_field: code
        fields:
          code: { type: string, required: true }
          placed_on: { type: date, required: true }
          paid_at: { type: datetime }
          status: { type: enum, values: [open, paid], default: open }
    ui:
      dashboards:
        overview:
          widgets:
            by_week:
              kind: chart
              chart: line
              entity: Order
              group_by: paid_at
              interval: week
            by_day: { kind: chart, chart: bar, entity: Order, group_by: placed_on, interval: day }
            by_month: { kind: chart, chart: bar, entity: Order, group_by: placed_on }
    pages:
      overview: { path: /, title: Overview, content: { dashboard: overview } }
    """
)
API = BASE.replace("title: Shop }", "title: Shop, x-react-data: api }")
LANGUAGES = dedent(
    """\
    translations:
      default: en
      languages:
        en: { label: English }
        de: { label: Deutsch, locale: de-DE }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_chart_of_dates_takes_an_interval() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.ui is not None
    widgets = definition.ui.dashboards["overview"].widgets
    assert isinstance(widgets["by_month"], ChartWidget)
    assert widgets["by_month"].interval == "month"


def test_only_a_chart_of_dates_takes_an_interval() -> None:
    text = BASE.replace("group_by: placed_on, interval: day", "group_by: status, interval: day")
    assert codes(text) == [("invalid-option", "ui.dashboards.overview.widgets.by_day")]
    # The default interval is not an error.
    assert codes(BASE.replace("group_by: placed_on }", "group_by: status }")) == []


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_chart_groups_the_records_by_the_interval(binding: Binding) -> None:
    files = files_of(BASE, binding)
    dashboard = files["src/widgets/overview/ui/overview-dashboard.tsx"]
    assert (
        'return intervalRows(rows, (row) => row.paidAt, (group) => group.length, "week");'
    ) in dashboard
    assert '(row) => row.placedOn, (group) => group.length, "day");' in dashboard
    assert '(row) => row.placedOn, (group) => group.length, "month");' in dashboard
    assert "import { intervalRows, type ChartDatum } from" in dashboard
    lib = files["src/shared/lib/aggregate.ts"]
    assert "export function intervalRows<T>(" in lib
    assert "const firstWeekday = () => 1;" in lib
    assert "for (let key = first; key <= last; key = nextKey(key, interval)) {" in lib


def test_the_weeks_start_on_the_first_day_of_the_locale() -> None:
    files = files_of(BASE + LANGUAGES, react.BINDING)
    lib = files["src/shared/lib/aggregate.ts"]
    assert 'import { dateTimeFormat, firstWeekday } from "@/shared/lib/format";' in lib
    assert "const firstWeekday" not in lib


def test_a_dashboard_without_a_chart_of_dates_has_no_intervals() -> None:
    head, _, tail = BASE.partition("      widgets:\n")
    widgets = "        by_status: { kind: chart, chart: donut, entity: Order, group_by: status }\n"
    text = head + "      widgets:\n" + widgets + tail[tail.index("pages:") :]
    assert codes(text) == []
    lib = files_of(text, react.BINDING)["src/shared/lib/aggregate.ts"]
    assert "intervalRows" not in lib and "firstWeekday" not in lib


@pytest.mark.parametrize("i18n", [False, True], ids=["one-language", "languages"])
def test_with_the_api_the_endpoint_gives_the_intervals(i18n: bool) -> None:
    files = files_of(API + (LANGUAGES if i18n else ""), react.BINDING)
    dashboard = files["src/widgets/overview/ui/overview-dashboard.tsx"]
    assert 'return chartIntervals(data.byWeek, "week");' in dashboard
    assert 'return chartIntervals(data.byDay, "day");' in dashboard
    week = 'chartValues("/dashboards/overview/by-week", { week_start: String(firstWeekday()) }),'
    assert (week in dashboard) == i18n
    assert 'chartValues("/dashboards/overview/by-day"),' in dashboard
    lib = files["src/shared/lib/aggregate.ts"]
    assert "export function chartIntervals(" in lib


def test_the_endpoint_groups_the_dates_by_the_interval() -> None:
    files = files_of(BASE, fastapi.BINDING)
    code = files["app/features/dashboards/overview.py"]
    assert (
        'key = interval_of(session, Order.paid_at, "week", utc=True, week_start=week_start)'
    ) in code
    assert "week_start: WeekStart = 1" in code
    assert 'key = interval_of(session, Order.placed_on, "day")' in code
    assert 'key = interval_of(session, Order.placed_on, "month")' in code
    assert "from app.features.dashboards.aggregates import WeekStart, chart_values" in code
    helpers = files["app/features/dashboards/aggregates.py"]
    assert "def interval_of(" in helpers
    tests = files["tests/features/dashboards/test_overview.py"]
    # A Thursday and a Sunday: the weeks start on Monday, the default of `week_start`.
    assert '{"key": "2025-01-13", "value": 1.0},' in tests
    assert '{"key": "2026-02-09", "value": 2.0},' in tests
    assert '{"key": "2025-01-16", "value": 1.0},' in tests
    assert '{"key": "2026-02", "value": 2.0},' in tests
