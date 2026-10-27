"""The daily snapshots of the stat widgets in the Next.js app (ADR 0042).

A stat widget with `snapshots: daily` gets a value function in the module
of the built-in job `stat_snapshots` (`src/app/jobs/stat-snapshots.ts`): a
Drizzle query with the filter of the stat, as the FastAPI app does. The
job runs at 00:00 UTC, and each run stores the value of each stat as the
value of its day in the table `stat_snapshots`. A chart of snapshots
reads the values of its days with a server action, with the permission
of the list operation of the entity of the stat.
"""

import re
from dataclasses import dataclass, field

from appgen.bindings.nextjs.db import Table, TsCall, TsChain, TsCode, format_ts
from appgen.bindings.nextjs.jobs import FilterBuilder, TsFilter, TsJob, TsSchedule
from appgen.bindings.shared.auth import kind_operations, public_kinds
from appgen.bindings.shared.dashboards import snapshot_action, snapshot_stat
from appgen.dsl.cron import parse_cron
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.dashboards import ChartWidget, StatWidget
from appgen.gen.naming import camel
from appgen.gen.render import GenerationError

TABLE = "stat_snapshots"
"""The table of the daily values. The FastAPI app has the same table."""
TABLE_CONST = "statSnapshotsTable"
TABLE_MODULE = "stat-snapshots"
JOB = "stat_snapshots"
"""The name of the built-in job, and of its route `/api/jobs/stat_snapshots`."""
SCHEDULE = "0 0 * * *"
"""The schedule of the job in UTC: each day at 00:00."""

_OPERATORS = (
    *("and", "avg", "count", "eq", "gt", "gte", "inArray", "isNotNull", "isNull"),
    *("lt", "lte", "max", "min", "ne", "notInArray", "or", "sum"),
)
"""The functions of `drizzle-orm` that the value functions can call."""


@dataclass(slots=True)
class TsSnapshotStat:
    """A stat widget with daily snapshots: the function that gives its value at a time."""

    dashboard: str
    widget: str
    id: str
    function: str
    """The value function of the job module, for example `overviewRooms`."""
    body: str
    """The lines of the body of the function, at an indent of 2."""
    now: bool = False
    """True if the function reads the time of the run (`$now` or `$today`)."""


@dataclass(slots=True)
class TsSnapshotChart:
    """A chart of snapshots: the server action that gives the values of its days."""

    dashboard: str
    widget: str
    id: str
    stat: str
    """The stat widget of the chart."""
    action: str
    days: int
    options: str
    """The options of `runAction`: the permission of the list operation of the entity."""


@dataclass(slots=True)
class TsSnapshots:
    """The stats with daily snapshots, their charts, and the built-in job."""

    stats: list[TsSnapshotStat]
    charts: list[TsSnapshotChart]
    job: TsJob
    tables: list[str] = field(default_factory=list[str])
    """The tables of `@/shared/db` that the value functions read."""

    @property
    def ids(self) -> list[str]:
        """The element IDs of the stats, for the traces."""
        return [stat.id for stat in self.stats]

    def imports(self) -> list[str]:
        """Return the import lines of the job module, after `server-only`."""
        code = " ".join(stat.body for stat in self.stats)
        drizzle = [name for name in _OPERATORS if re.search(rf"\b{name}\(", code)]
        if "sql`" in code:
            drizzle.append("sql")
        helpers = ["dateOf", "type JobResult", "runDue", "Schedule"]
        if "dayStart(" in code:
            helpers.append("dayStart")
        schedule = self.job.schedule
        if schedule is not None and "span(" in schedule.code():
            helpers.append("span")
        lines = [
            _import("drizzle-orm", drizzle) if drizzle else "",
            "",
            _import("@/shared/db", ["getDb", *self.tables]),
            'import { storeSnapshot } from "@/shared/db/snapshots";',
            _import("@/shared/lib/jobs", helpers),
        ]
        return lines if drizzle else lines[2:]


def ts_snapshots(definition: AppDefinition, tables: dict[str, Table]) -> TsSnapshots | None:
    """Return the stats with daily snapshots and their charts, or None without them.

    Raise GenerationError if a table of the app has the name of the table
    of the snapshots, if a job has the name of the built-in job, or if a
    stat reads a field that the database cannot aggregate.
    """
    if definition.ui is None:
        return None
    stats: list[TsSnapshotStat] = []
    charts: list[TsSnapshotChart] = []
    used: set[str] = set()
    for dashboard_name, dashboard in definition.ui.dashboards.items():
        for name, widget in dashboard.widgets.items():
            if isinstance(widget, StatWidget) and widget.snapshots is not None:
                stat, found = _stat(definition, tables, dashboard_name, name, widget)
                stats.append(stat)
                used |= found
            elif isinstance(widget, ChartWidget) and widget.snapshots is not None:
                stat_name, stat_widget = snapshot_stat(dashboard, widget)
                entity = stat_widget.entity
                options = ""
                if "list" in public_kinds(definition, entity):
                    options = ", { public: true }"
                elif definition.access is not None:
                    operation = kind_operations(definition, entity).get("list")
                    options = f', {{ operation: "{operation}" }}' if operation else ""
                charts.append(
                    TsSnapshotChart(
                        dashboard=dashboard_name,
                        widget=name,
                        id=widget.id,
                        stat=stat_name,
                        action=snapshot_action(dashboard_name, name),
                        days=widget.days,
                        options=options,
                    )
                )
    if not stats:
        return None
    if JOB in definition.jobs:
        raise GenerationError(
            f"The job '{JOB}' has the name of the built-in job of the snapshots of the stat "
            "widgets (ADR 0042). Give the job another name."
        )
    for table in tables.values():
        names = {table.name, *(j.name for j in table.join_tables)}
        if TABLE in names or table.const == TABLE_CONST or table.module == TABLE_MODULE:
            raise GenerationError(
                f"The entity '{table.entity}' has the table '{TABLE}', or its module, and the "
                "snapshots of the stat widgets need it. Give the entity another name or table."
            )
    job = TsJob(
        name=JOB,
        id=stats[0].id,
        description="Store the daily values of the stat widgets with `snapshots: daily`.",
        schedule=TsSchedule(parse_cron(SCHEDULE)),
        builtin=True,
    )
    return TsSnapshots(stats, charts, job, sorted(used))


def _stat(
    definition: AppDefinition,
    tables: dict[str, Table],
    dashboard: str,
    name: str,
    widget: StatWidget,
) -> tuple[TsSnapshotStat, set[str]]:
    """Return the value function of a stat with snapshots, and the tables that it reads."""
    entity = widget.entity
    table = tables[entity]
    found = TsFilter(tables={table.const})
    builder = FilterBuilder(definition, tables, widget.id, found)
    conditions = [builder.filter(entity, path, c) for path, c in widget.filter.items()]
    if widget.aggregate == "count" or widget.field is None:
        value = "count()"
    else:
        value = f"{widget.aggregate}({table.const}.{_column(definition, table, widget)})"
    calls = [TsCall("select", [f"{{ value: {value} }}"]), TsCall("from", [table.const])]
    if conditions:
        where: TsCode = conditions[0] if len(conditions) == 1 else TsCall("and", conditions)
        calls.append(TsCall("where", [where]))
    lines = ["const today = dateOf(now);"] if found.today else []
    lines.append(format_ts(TsChain("getDb()", calls), 2, "const rows = await ", ";"))
    if widget.aggregate == "count" or widget.field is None:
        lines.append("return rows[0]?.value ?? 0;")
    elif widget.aggregate == "sum":
        # As in the FastAPI app: the sum of no records is 0.
        lines.append("return Number(rows[0]?.value ?? 0);")
    else:
        lines.append("const value = rows[0]?.value ?? null;")
        lines.append("return value === null ? null : Number(value);")
    stat = TsSnapshotStat(
        dashboard=dashboard,
        widget=name,
        id=widget.id,
        function=camel(f"{dashboard}_{name}"),
        body="\n".join("  " + line for line in lines),
        now=found.today or found.now,
    )
    return stat, found.tables


def _column(definition: AppDefinition, table: Table, widget: StatWidget) -> str:
    """Return the column of the field of an aggregate: a stored field of the entity."""
    path = widget.field or ""
    spec = definition.entities[widget.entity]
    member = spec.fields.get(path)
    if member is None or member.computed is not None:
        raise GenerationError(
            f"The stat widget '{widget.id}' has daily snapshots of the field '{path}'. The "
            "Next.js app computes a snapshot in the database, so the field must be a stored "
            f"field of '{widget.entity}', not a field of a related record or a computed field."
        )
    return next(c.key for c in table.columns if c.element_id == member.id)


def _import(module: str, names: list[str]) -> str:
    ordered = sorted(set(names), key=lambda name: name.removeprefix("type ").lower())
    return f'import {{ {", ".join(ordered)} }} from "{module}";'
