"""The jobs: work that the apps run on a schedule, or at the time of a date field (ADR 0029)."""

import datetime as dt
import re
from typing import Annotated

import pydantic
from pydantic import JsonValue

from appgen.dsl.element import Element, EntityName, MemberName, Text
from appgen.dsl.ui.dashboards import RecordFilter

OFFSET_PATTERN = r"^[+-]?[0-9]+[mhdw]$"
"""An offset: a whole number with a sign and a unit, for example `-24h`."""
OFFSET_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
"""The units of an offset, and the argument of `timedelta` for each one."""
_OFFSET = re.compile(OFFSET_PATTERN)

type Offset = Annotated[str, pydantic.Field(json_schema_extra={"pattern": OFFSET_PATTERN})]
"""An offset. The validator checks the pattern, so that its message names the units."""


class Job(Element):
    """An operation that the apps run on a schedule, or at the time that a date field gives.

    A job with an entity runs a custom operation of the entity on each
    record that its filter selects. A job without an entity runs a
    function that hand-written code gives (a generation gap).
    """

    description: Text | None = None
    schedule: Text | None = None
    """A cron expression in UTC, for example `0 7 * * 1` (each Monday at 07:00)."""
    at: MemberName | None = None
    """A `date` or `datetime` field of the entity: the job runs for each record at its time."""
    offset: Offset | None = None
    """The time before (`-`) or after the time of `at`, for example `-24h`. The default is 0."""
    entity: EntityName | None = None
    operation: MemberName | None = None
    """A custom operation of the entity, without required params."""
    filter: RecordFilter = pydantic.Field(default_factory=dict[str, JsonValue])
    """The records of the job: the filter syntax of the dashboards, with `$now`."""
    user: MemberName | None = None
    """A relation of the entity to the user entity of `auth`, or `id` for the user entity: the
    clients of the APIs with the authorization code flow send the token of this user
    (ADR 0033)."""

    def offset_delta(self) -> dt.timedelta:
        """Return the offset as a time span. Raise ValueError if it is not valid."""
        return parse_offset(self.offset or "0m")


def parse_offset(text: str) -> dt.timedelta:
    """Return an offset, for example `-24h`, as a time span. Raise ValueError if it is not valid."""
    if not _OFFSET.match(text):
        raise ValueError(f"The offset {text!r} is not valid.")
    unit = OFFSET_UNITS[text[-1]]
    return dt.timedelta(**{unit: int(text[:-1])})
