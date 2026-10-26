"""The period of a dashboard (ADR 0038): the checks, the front ends, and the endpoints of the
FastAPI app."""

from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.ui.dashboards import DEFAULT_RANGES
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
          total: { type: decimal, format: currency }
    ui:
      views:
        order_table: { kind: table, entity: Order, columns: { code: {}, placed_on: {} } }
      dashboards:
        overview:
          period: { default: last_30_days, ranges: [last_7_days, last_30_days, all, custom] }
          widgets:
            orders: { kind: stat, entity: Order, period_field: placed_on, compare: previous }
            revenue:
              kind: stat
              entity: Order
              aggregate: sum
              field: total
              period_field: paid_at
            all_orders: { kind: stat, entity: Order }
            by_day:
              kind: chart
              chart: bar
              entity: Order
              group_by: placed_on
              interval: day
              period_field: paid_at
            latest: { kind: list, view: order_table, period_field: placed_on }
    pages:
      overview: { path: /, title: Overview, content: { dashboard: overview } }
    """
)
API = BASE.replace("title: Shop }", "title: Shop, x-react-data: api }")
DASHBOARD = "src/widgets/overview/ui/overview-dashboard.tsx"


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_dashboard_takes_a_period() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(
        BASE.replace(
            " { default: last_30_days, ranges: [last_7_days, last_30_days, all, custom] }", " {}"
        ),
        "app.yaml",
    )
    assert definition.ui is not None
    period = definition.ui.dashboards["overview"].period
    assert period is not None and period.id == "ui.dashboards.overview.period"
    assert (period.default, tuple(period.ranges)) == ("last_30_days", DEFAULT_RANGES)


@pytest.mark.parametrize(
    ("old", "new", "found"),
    [
        ("default: last_30_days", "default: this_year", ("invalid-value", "period")),
        ("ranges: [last_7_days,", "ranges: [all, last_7_days,", ("invalid-value", "period")),
        (
            "period_field: placed_on, compare",
            "period_field: code, compare",
            ("unsuitable-field", "orders"),
        ),
        (
            "period_field: placed_on, compare",
            "period_field: placed, compare",
            ("unknown-reference", "orders"),
        ),
        (
            "period_field: placed_on, compare: previous",
            "compare: previous",
            ("invalid-option", "orders"),
        ),
    ],
)
def test_the_checks_of_a_period(old: str, new: str, found: tuple[str, str]) -> None:
    code, name = found
    element = "ui.dashboards.overview." + ("period" if name == "period" else f"widgets.{name}")
    assert codes(BASE.replace(old, new)) == [(code, element)]


def test_a_period_field_needs_a_period_and_a_period_needs_a_period_field() -> None:
    text = "".join(line for line in BASE.splitlines(keepends=True) if "period: {" not in line)
    found = codes(text)
    assert ("invalid-option", "ui.dashboards.overview.widgets.orders") in found
    assert len(found) == 4
    head, _, tail = BASE.partition("      widgets:\n")
    widgets = "        all_orders: { kind: stat, entity: Order }\n"
    text = head + "      widgets:\n" + widgets + tail[tail.index("pages:") :]
    assert codes(text) == [("invalid-option", "ui.dashboards.overview.period")]


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_widgets_show_the_records_of_the_period(binding: Binding) -> None:
    files = files_of(BASE, binding)
    dashboard = files[DASHBOARD]
    assert (
        'const [choice, setChoice] = useState<PeriodChoice>({ range: "last_30_days", custom: {} });'
    ) in dashboard
    assert "const period = periodOf(choice.range, today(), choice.custom);" in dashboard
    assert (
        "const rows = data.records.order.filter((row) => inPeriod(row.placedOn, period));"
    ) in dashboard
    assert "inPeriod(row.paidAt, period)" in dashboard
    assert "function allOrders(data: DashboardData): number | null {" in dashboard
    assert "const latestRows = latest(data, period);" in dashboard
    assert "change={change(orders(data, period), previous && orders(data, previous))}" in dashboard
    assert (
        '<PeriodPicker ranges={["last_7_days", "last_30_days", "all", "custom"]} '
        "value={choice} onChange={setChoice} />"
    ) in dashboard
    period = files["src/shared/lib/period.ts"]
    assert "export function previousPeriod(period: Period): Period | null {" in period
    picker = files["src/shared/ui/period-picker.tsx"]
    assert "<DateRangeFilter" in picker
    assert "src/shared/ui/filters/date-range-filter.tsx" in files
    tile = files["src/shared/ui/widget-card.tsx"]
    assert "{change !== undefined && <StatChange change={change} />}" in tile


def test_a_period_without_a_custom_range_has_no_date_picker() -> None:
    files = files_of(BASE.replace(", all, custom]", ", all]"), react.BINDING)
    assert "DateRangeFilter" not in files["src/shared/ui/period-picker.tsx"]
    assert "src/shared/ui/filters/date-range-filter.tsx" not in files


def test_a_dashboard_without_a_period_has_no_picker() -> None:
    head, _, tail = BASE.partition("      period:")
    text = head + tail[tail.index("      widgets:") :]
    text = text.replace(", period_field: placed_on, compare: previous", "")
    text = "".join(line for line in text.splitlines(keepends=True) if "period_field" not in line)
    assert codes(text) == []
    files = files_of(text, react.BINDING)
    assert "src/shared/lib/period.ts" not in files
    assert "useState" not in files[DASHBOARD]
    assert "StatChange" not in files["src/shared/ui/widget-card.tsx"]


def test_with_the_api_the_endpoints_give_the_values_of_the_period() -> None:
    dashboard = files_of(API, react.BINDING)[DASHBOARD]
    assert "async function load(period: Period): Promise<DashboardData> {" in dashboard
    assert 'statValue("/dashboards/overview/orders", periodParams(period)),' in dashboard
    assert (
        'previous ? statValue("/dashboards/overview/orders", periodParams(previous)) : null,'
    ) in dashboard
    assert 'statValue("/dashboards/overview/all-orders"),' in dashboard
    assert "change={change(orders(data), data.ordersPrevious)}" in dashboard
    assert (
        'const resource = useResource(["overview", period.from, period.to].join(" "), '
        "() => load(period), subscribe, { keep: true });"
    ) in dashboard


def test_the_endpoints_take_the_days_of_the_period() -> None:
    files = files_of(BASE, fastapi.BINDING)
    code = files["app/features/dashboards/overview.py"]
    assert "    start: PeriodStart = None,\n    end: PeriodEnd = None,\n" in code
    assert "        statement = statement.where(Order.placed_on >= start)\n" in code
    assert "        statement = statement.where(Order.placed_on <= end)\n" in code
    assert "        statement = statement.where(Order.paid_at >= day_start(start))\n" in code
    assert "        statement = statement.where(Order.paid_at < day_start(end, 1))\n" in code
    tests = files["tests/features/dashboards/test_overview.py"]
    assert 'PERIOD = {"start": "2026-05-17", "end": "2026-06-15"}' in tests
    assert 'response = await client.get("/dashboards/overview/orders", params=PERIOD)' in tests
    # A record before the period and a record after it fail.
    assert "    records[3].placed_on = dt.date(2026, 5, 14)\n" in tests
    assert "    records[4].placed_on = dt.date(2026, 6, 18)\n" in tests
