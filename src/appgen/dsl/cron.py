"""Cron expressions: the schedules of the jobs, in UTC (ADR 0029).

An expression has five fields: the minute (0-59), the hour (0-23), the
day of the month (1-31), the month (1-12 or `jan`-`dec`), and the day of
the week (0-7 or `sun`-`sat`, where 0 and 7 are Sunday). A field is `*`,
a value, a range (`1-5`), a step (`*/15`, `0-30/10`), or a list of these
(`1,15`). A macro replaces the five fields: `@hourly`, `@daily`
(`@midnight`), `@weekly`, `@monthly`, and `@yearly` (`@annually`).

The day fields follow the rule of the Vixie cron and of Kubernetes: if
both fields are restricted (they do not start with `*`), a day matches
when one of them matches. Else a day must match both.
"""

import datetime as dt
import re
from dataclasses import dataclass

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
"""The macros and the five fields that each one stands for."""
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_FIELDS = (
    ("minute", 0, 59, ()),
    ("hour", 0, 23, ()),
    ("day of the month", 1, 31, ()),
    ("month", 1, 12, _MONTHS),
    ("day of the week", 0, 7, _WEEKDAYS),
)
"""The name, the lowest value, the highest value, and the value names of each field."""
_PART = re.compile(r"^(?:(\*)|([0-9a-z]+)(?:-([0-9a-z]+))?)(?:/([0-9]+))?$")


class CronError(ValueError):
    """A cron expression is not valid. The message tells why."""


@dataclass(frozen=True, slots=True)
class Cron:
    """A cron expression, with the values that each field allows."""

    expression: str
    """The five fields, with a macro replaced, and one space between the fields."""
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    """The days of the week: 0 is Sunday. A 7 in the expression is 0 here."""
    either_day: bool
    """True if both day fields are restricted: a day matches when one of them matches."""

    def matches(self, time: dt.datetime) -> bool:
        """Return True if the schedule runs at the minute of a time (in UTC)."""
        time = time.astimezone(dt.UTC)
        if time.minute not in self.minutes or time.hour not in self.hours:
            return False
        if time.month not in self.months:
            return False
        day, weekday = time.day in self.days, time.isoweekday() % 7 in self.weekdays
        return day or weekday if self.either_day else day and weekday

    def next_after(self, time: dt.datetime, limit: int = 366 * 24 * 60) -> dt.datetime | None:
        """Return the first time of the schedule after a time, or None in the next `limit` minutes.

        A schedule can have no time, for example on 31 February.
        """
        current = time.astimezone(dt.UTC).replace(second=0, microsecond=0)
        for _ in range(limit):
            current += dt.timedelta(minutes=1)
            if self.matches(current):
                return current
        return None


def parse_cron(text: str) -> Cron:
    """Parse a cron expression. Raise CronError if it is not valid."""
    expression = MACROS.get(text.strip().lower(), text.strip())
    if expression.startswith("@"):
        names = ", ".join(sorted(MACROS))
        raise CronError(f"The macro '{text.strip()}' is not known. The macros are {names}.")
    parts = expression.split()
    if len(parts) != 5:
        raise CronError(
            f"A cron expression has 5 fields (minute, hour, day of the month, month, and "
            f"day of the week), but '{text}' has {len(parts)}."
        )
    values = [
        _field(part.lower(), name, low, high, names)
        for part, (name, low, high, names) in zip(parts, _FIELDS, strict=True)
    ]
    restricted = [not parts[i].startswith("*") for i in (2, 4)]
    return Cron(
        expression=" ".join(parts),
        minutes=values[0],
        hours=values[1],
        days=values[2],
        months=values[3],
        weekdays=frozenset(day % 7 for day in values[4]),
        either_day=all(restricted),
    )


def _field(text: str, name: str, low: int, high: int, names: tuple[str, ...]) -> frozenset[int]:
    found: set[int] = set()
    for part in text.split(","):
        match = _PART.match(part)
        if match is None:
            raise CronError(f"The {name} field has the part '{part}', which is not valid.")
        star, first, last, step = match.groups()
        if star:
            start, end = low, high
        else:
            start = _value(first, name, low, high, names)
            end = _value(last, name, low, high, names) if last else start
            if end < start:
                raise CronError(f"The range '{part}' of the {name} field ends before it starts.")
            if step and not last:
                # A value with a step, for example 5/15, goes to the end of the field.
                end = high
        increment = int(step) if step else 1
        if increment < 1:
            raise CronError(f"The step of '{part}' in the {name} field must be 1 or more.")
        found.update(range(start, end + 1, increment))
    return frozenset(found)


def _value(text: str, name: str, low: int, high: int, names: tuple[str, ...]) -> int:
    if text in names:
        return names.index(text) + (1 if name == "month" else 0)
    if not text.isdigit():
        hint = f" Use {low}-{high} or a name such as '{names[0]}'." if names else ""
        raise CronError(f"The value '{text}' of the {name} field is not valid.{hint}")
    value = int(text)
    if not low <= value <= high:
        raise CronError(f"The value {value} of the {name} field is not in the range {low}-{high}.")
    return value
