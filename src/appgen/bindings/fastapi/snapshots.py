"""The daily snapshots of the stat widgets in the FastAPI app (ADR 0042).

A stat widget with `snapshots: daily` gets a value function in the module
of its dashboard: the endpoint of the stat and the built-in job
`stat_snapshots` call it. The worker runs the job at 00:00 UTC, and each
run stores the value of each stat as the value of its day in the table
`stat_snapshots` (`app/core/snapshots.py`). The endpoint of a chart of
snapshots gives the stored values of the days of the chart.
"""

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.dashboards import PyDashboard, PyWidget
from appgen.bindings.fastapi.jobs import PyJob, PySchedule
from appgen.bindings.fastapi.pysource import call
from appgen.dsl.cron import parse_cron
from appgen.dsl.model import AppDefinition
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity

TABLE = "stat_snapshots"
"""The table of the daily values. The Next.js app has the same table."""
JOB = "stat_snapshots"
"""The name of the built-in job, and of its module in `app/jobs/`."""
SCHEDULE = "0 0 * * *"
"""The schedule of the job in UTC: each day at 00:00."""
TEST_DAYS = (dt.date(2026, 6, 13), dt.date(2026, 6, 14), dt.date(2026, 6, 15))
"""The days of the runs of the generated tests."""


@dataclass(frozen=True, slots=True)
class PySnapshotStat:
    """A stat widget with daily snapshots, in the module of its dashboard."""

    dashboard: PyDashboard
    widget: PyWidget

    @property
    def key(self) -> str:
        """The dashboard and the widget, for example `overview.rooms`."""
        return f"{self.dashboard.name}.{self.widget.name}"

    def value_args(self, session: str, day: str, time: str) -> list[str]:
        """Return the arguments of the value function: the session, the day, and the time."""
        args = [session]
        if self.widget.today:
            args.append(day)
        if self.widget.now:
            args.append(time)
        return args

    def store_lines(self) -> list[str]:
        """Return the lines of a run that store the value of the stat, at an indent of 8."""
        args = self.value_args("session", "day", "item.time")
        value = call("value = await ", self.widget.value_function, args, 8)
        store = call(
            "await ",
            "store_snapshot",
            ["session", f'"{self.dashboard.name}"', f'"{self.widget.name}"', "day", "value"],
            8,
        )
        return [value, store]


@dataclass(frozen=True, slots=True)
class PySnapshots:
    """The stats with daily snapshots, the charts of their values, and the built-in job."""

    stats: list[PySnapshotStat]
    charts: list[tuple[PyDashboard, PyWidget]]
    job: PyJob
    test_days: tuple[dt.date, ...] = TEST_DAYS

    @property
    def ids(self) -> list[str]:
        """The element IDs of the stats, for the traces."""
        return [stat.widget.id for stat in self.stats]

    def factory_names(self) -> list[str]:
        """The factories of the entities of the stats, for example `make_room`."""
        return [f"make_{entity.snake}" for entity in self.factories()]

    def factories(self) -> list[PyEntity]:
        """The entities of the stats, for the factories of the generated tests."""
        found: dict[str, PyEntity] = {}
        for stat in self.stats:
            found.setdefault(stat.widget.entity.name, stat.widget.entity)
        return list(found.values())


def python_snapshots(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    dashboards: dict[str, PyDashboard],
) -> PySnapshots | None:
    """Return the stats with daily snapshots and their charts, or None without them.

    Raise GenerationError if an entity has the table of the snapshots, or
    if a job has the name of the built-in job.
    """
    stats = [
        PySnapshotStat(dashboard, widget)
        for dashboard in dashboards.values()
        for widget in dashboard.widgets
        if widget.snapshots
    ]
    if not stats:
        return None
    if JOB in definition.jobs:
        raise GenerationError(
            f"The job '{JOB}' has the name of the built-in job of the snapshots of the stat "
            "widgets (ADR 0042). Give the job another name."
        )
    for entity in entities.values():
        if entity.table == TABLE:
            raise GenerationError(
                f"The entity '{entity.name}' has the table '{TABLE}' of the snapshots of the "
                "stat widgets. Give it another table with x-fastapi-table."
            )
    charts = [
        (dashboard, widget)
        for dashboard in dashboards.values()
        for widget in dashboard.widgets
        if widget.snapshot_of is not None
    ]
    job = PyJob(
        name=JOB,
        id=stats[0].widget.id,
        description="Store the daily values of the stat widgets with `snapshots: daily`.",
        schedule=PySchedule(parse_cron(SCHEDULE)),
        builtin=True,
    )
    return PySnapshots(stats, charts, job)
