"""The seed records of the entities: the data that the apps start with (ADR 0021).

The optional section `seed` maps an entity name to the seed of the
entity. Each record of `records` is an element with the ID
`seed.<Entity>.records.<key>`. A record gives its values by field name
and by relation name. A relation takes the key of a seed record of the
target entity, or a list of keys for a `many_to_many` relation. The key
also gives the ID of the record: a UUID (version 5) from the app name,
the entity name, and the key, so that a change of another record does
not change it.

The model of a record depends on its entity, so the model keeps the
values as they are, and the validator checks them. The bindings read the
values in their normal form (`normal_value`).
"""

import datetime
import json
import math
import re
import uuid
from typing import TYPE_CHECKING, Annotated, Any, cast
from urllib.parse import urlparse

import pydantic
from pydantic import ConfigDict, StringConstraints

from appgen.dsl.element import Element

if TYPE_CHECKING:
    from appgen.dsl.model import Field, Relation

RECORD_KEY_PATTERN = r"^[A-Za-z0-9_]+$"
SEED_NAMESPACE = uuid.UUID("97298d18-e518-4f95-9016-d8efd1b8eab0")
"""The namespace of the UUIDs of the seed records. Do not change it: it gives the IDs."""

type RecordKey = Annotated[str, StringConstraints(pattern=RECORD_KEY_PATTERN)]
"""The key of a seed record. It is a segment of an element ID, so it has only letters, digits,
and `_`."""

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SeedRecord(Element):
    """A seed record: the values of its fields and relations, by name."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, Any] = pydantic.Field(init=False)  # pyright: ignore[reportIncompatibleVariableOverride]

    @property
    def values(self) -> dict[str, Any]:
        """The values by field or relation name, in source order."""
        return dict(self.__pydantic_extra__)

    @property
    def key(self) -> str:
        """The key of the record, the last segment of its ID."""
        return self.id.rpartition(".")[2]


class EntitySeed(Element):
    """The seed of an entity: its records, and the number of generated records."""

    records: dict[RecordKey, SeedRecord] = pydantic.Field(default_factory=dict[str, SeedRecord])
    """The records by key. The other records refer to a record by its key."""
    mock: Annotated[int, pydantic.Field(ge=0)] = 0
    """The number of generated records in addition to the seed records."""


def record_id(app: str, entity: str, key: str) -> str:
    """Return the ID of a seed record: a UUID (version 5) from the app, the entity, and the key."""
    return str(uuid.uuid5(SEED_NAMESPACE, f"{app}:{entity}:{key}"))


def normal_value(field: Field, value: object) -> Any:
    """Return a value of a field in its normal form. Raise ValueError if it does not suit the type.

    A date is `YYYY-MM-DD`. A date-time is in UTC, for example
    `2026-01-05T09:30:00Z`: a date-time without an offset is in UTC. A
    UUID is in small letters. None stays None. The function does not
    check the options of the field (`min`, `max_length`, and so on).
    """
    if value is None:
        return None
    match field.type:
        case "string" | "text":
            return _string(value)
        case "email":
            text = _string(value)
            if not _EMAIL.fullmatch(text):
                raise ValueError("expected an email address, for example 'ada@example.com'")
            return text
        case "url":
            text = _string(value)
            parts = urlparse(text)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError("expected an http or https URL")
            return text
        case "enum":
            text = _string(value)
            if text not in (field.values or []):
                choices = ", ".join(f"'{v}'" for v in field.values or [])
                raise ValueError(f"expected one of {choices}")
            return text
        case "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("expected an integer")
            return value
        case "decimal":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("expected a number")
            if not math.isfinite(value):
                raise ValueError("expected a finite number")
            return value
        case "boolean":
            if not isinstance(value, bool):
                raise ValueError("expected true or false")
            return value
        case "date":
            return _date(value).isoformat()
        case "datetime":
            return format_datetime(_datetime(value))
        case "uuid":
            try:
                return str(uuid.UUID(_string(value)))
            except ValueError:
                raise ValueError("expected a UUID") from None
        case "json":
            try:
                json.dumps(value, allow_nan=False)
            except TypeError, ValueError:
                raise ValueError("expected a JSON value") from None
            return value


def format_datetime(moment: datetime.datetime) -> str:
    """Return a date-time in UTC as ISO 8601 text with a `Z`, with milliseconds if it has them."""
    moment = moment.astimezone(datetime.UTC)
    timespec = "milliseconds" if moment.microsecond else "seconds"
    return moment.replace(tzinfo=None).isoformat(timespec=timespec) + "Z"


def link_keys(relation: Relation, value: object) -> list[str]:
    """Return the record keys of a relation value: one key, or a list of keys (`many_to_many`).

    A key can be an integer in YAML, for example `room: 101`. The key of
    the record is the text `101`.
    """
    if value is None:
        return []
    if relation.kind == "many_to_many" and isinstance(value, list):
        return [str(item) for item in cast(list[object], value)]
    return [str(value)]


def is_record_key(value: object) -> bool:
    """Return True if a relation value can be a record key: a text, or an integer."""
    if isinstance(value, bool):
        return False
    return isinstance(value, str | int) and re.fullmatch(RECORD_KEY_PATTERN, str(value)) is not None


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value


def _date(value: object) -> datetime.date:
    # YAML reads a date without quotes as a date.
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("expected a date, for example '2026-01-05'")


def _datetime(value: object) -> datetime.datetime:
    moment: datetime.datetime | None = None
    if isinstance(value, datetime.datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.datetime.fromisoformat(value)
        except ValueError:
            moment = None
    if moment is None:
        raise ValueError("expected a date-time, for example '2026-01-05T09:30:00Z'")
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=datetime.UTC)
