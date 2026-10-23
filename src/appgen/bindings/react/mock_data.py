"""Deterministic mock data for the entities of a definition.

The React app has no back end. The generator writes mock records for each
entity into the app. The records come from a pseudo-random generator with
a fixed seed (the app name and the entity name), so the same definition
always gives the same records. The values suit the field types and
options (enum values, `min`, `max`, `max_length`, simple patterns, and
`unique`), and each relation refers to a record that exists.

An entity can set the number of records with the extension key
`x-mock-count` (default: 12).
"""

import random
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from appgen.dsl.model import AppDefinition, Entity, Field

DEFAULT_COUNT = 12
BASE_DATE = date(2026, 1, 5)
"""The center of the mock dates. A fixed date keeps the output deterministic."""

type Record = dict[str, Any]

_FIRST_NAMES = [
    "Ada", "Alan", "Grace", "Linus", "Margaret", "Dennis", "Barbara", "Ken",
    "Frances", "Edsger", "Radia", "Tim", "Hedy", "John", "Katherine", "Donald",
]  # fmt: skip
_LAST_NAMES = [
    "Lovelace", "Turing", "Hopper", "Torvalds", "Hamilton", "Ritchie", "Liskov",
    "Thompson", "Allen", "Dijkstra", "Perlman", "Berners-Lee", "Lamarr",
    "Backus", "Johnson", "Knuth",
]  # fmt: skip
_ADJECTIVES = [
    "Apollo", "Atlas", "Beacon", "Comet", "Delta", "Echo", "Falcon", "Granite",
    "Harbor", "Juniper", "Meridian", "Nova", "Orbit", "Summit", "Tidal", "Vertex",
]  # fmt: skip
_NOUNS = [
    "Portal", "Migration", "Redesign", "Launch", "Platform", "Dashboard",
    "Pipeline", "Audit", "Rollout", "Integration", "Refactor", "Upgrade",
]  # fmt: skip
_VERBS = [
    "Write", "Review", "Fix", "Test", "Plan", "Design", "Update", "Deploy",
    "Document", "Measure", "Clean up", "Prepare",
]  # fmt: skip
_OBJECTS = [
    "the login page", "the release notes", "the API limits", "the onboarding flow",
    "the search index", "the billing report", "the error messages", "the test data",
    "the user survey", "the backup job", "the style guide", "the sprint plan",
]  # fmt: skip
_SENTENCES = [
    "The team agreed on the scope in the last review.",
    "This item needs a second check before the release.",
    "We moved the date because a supplier was late.",
    "The first draft is ready for comments.",
    "Customers asked for this change in the last survey.",
    "The work depends on the new API version.",
    "Please keep the old behavior until the migration is done.",
    "The tests pass on all supported browsers.",
    "We need a decision from the product owner.",
    "The design follows the new style guide.",
    "Most of the work is done, and two small items are open.",
    "The budget covers the work of two more weeks.",
]


def mock_data(definition: AppDefinition) -> dict[str, list[Record]]:
    """Return the mock records of each entity, by entity name.

    Each record has `id`, one key for each field, and one key for each
    stored relation: the ID of the target (or None) for `many_to_one` and
    `one_to_one`, and a list of IDs for `many_to_many`. The keys are the
    names of the definition; the templates convert them.
    """
    ids: dict[str, list[str]] = {}
    for name, entity in definition.entities.items():
        rng = random.Random(f"{definition.app.name}:{name}:ids")
        ids[name] = [_uuid(rng) for _ in range(_count(entity))]
    data: dict[str, list[Record]] = {}
    for name, entity in definition.entities.items():
        rng = random.Random(f"{definition.app.name}:{name}")
        records: list[Record] = []
        seen: dict[str, set[Any]] = {f: set() for f, field in entity.fields.items() if field.unique}
        for index, record_id in enumerate(ids[name]):
            record: Record = {"id": record_id}
            for field_name, field in entity.fields.items():
                value = _field_value(rng, entity, field_name, field, index, record)
                if field_name in seen:
                    for _ in range(100):
                        if value is None or value not in seen[field_name]:
                            break
                        value = _field_value(rng, entity, field_name, field, index, record)
                    seen[field_name].add(value)
                record[field_name] = value
            for relation_name, relation in entity.relations.items():
                targets = ids[relation.target]
                if relation.kind == "many_to_one":
                    optional = not relation.required and rng.random() < 0.2
                    record[relation_name] = None if optional else rng.choice(targets)
                elif relation.kind == "one_to_one":
                    taken = index < len(targets) and (relation.required or rng.random() < 0.8)
                    record[relation_name] = targets[index] if taken else None
                elif relation.kind == "many_to_many":
                    size = rng.randint(1, min(3, len(targets)))
                    chosen = rng.sample(range(len(targets)), size)
                    record[relation_name] = [targets[i] for i in sorted(chosen)]
            records.append(record)
        data[name] = records
    return data


def _count(entity: Entity) -> int:
    count = entity.extensions.get("x-mock-count", DEFAULT_COUNT)
    return count if isinstance(count, int) and count > 0 else DEFAULT_COUNT


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _field_value(
    rng: random.Random, entity: Entity, name: str, field: Field, index: int, record: Record
) -> Any:
    optional = not field.required and field.default is None and field.type != "boolean"
    if optional and rng.random() < 0.15:
        return None
    value = _typed_value(rng, entity, name, field, index, record)
    if isinstance(value, str) and field.max_length is not None:
        value = value[: field.max_length]
    return value


def _typed_value(
    rng: random.Random, entity: Entity, name: str, field: Field, index: int, record: Record
) -> Any:
    match field.type:
        case "enum":
            return rng.choice(field.values or [""])
        case "boolean":
            return rng.random() < 0.75
        case "integer":
            low, high = (
                int(field.min if field.min is not None else 0),
                int(field.max if field.max is not None else 100),
            )
            return rng.randint(low, max(low, high))
        case "decimal":
            return _decimal(rng, field)
        case "date":
            return _date(rng, name, record)
        case "datetime":
            start = datetime(BASE_DATE.year, BASE_DATE.month, BASE_DATE.day, tzinfo=UTC)
            moment = start + timedelta(minutes=rng.randint(-60 * 24 * 60, 60 * 24 * 60))
            return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        case "uuid":
            return _uuid(rng)
        case "email":
            return _email(rng, record, index)
        case "url":
            return f"https://example.com/{entity.label or 'item'}/{index + 1}".lower()
        case "json":
            return {}
        case "text":
            return _text(rng)
        case _:
            return _string(rng, entity, name, field, index)


def _date(rng: random.Random, name: str, record: Record) -> str:
    """Return a date. A due or end date comes after the dates before it in the record."""
    day = BASE_DATE + timedelta(days=rng.randint(-60, 120))
    if any(word in name for word in ("due", "end", "until")):
        earlier = [v for v in record.values() if isinstance(v, str) and _ISO_DATE.fullmatch(v)]
        if earlier:
            day = date.fromisoformat(max(earlier)) + timedelta(days=rng.randint(7, 90))
    return day.isoformat()


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _decimal(rng: random.Random, field: Field) -> float:
    low = field.min if field.min is not None else 0.0
    high = field.max if field.max is not None else max(low, 0.0) + 100_000.0
    scale = field.scale if field.scale is not None else 2
    return round(rng.uniform(low, high), scale)


def _email(rng: random.Random, record: Record, index: int) -> str:
    name = next((v for k, v in record.items() if k == "name" and isinstance(v, str)), None)
    local = re.sub(r"[^a-z.]", "", (name or f"user {index + 1}").lower().replace(" ", "."))
    return f"{local or 'user'}.{index + 1}@example.com"


def _string(rng: random.Random, entity: Entity, name: str, field: Field, index: int) -> str:
    if field.pattern is not None:
        value = _from_pattern(rng, field.pattern)
        if value is not None:
            return value
    if name == "name" and "email" in entity.fields:
        value = f"{_FIRST_NAMES[index % len(_FIRST_NAMES)]} {rng.choice(_LAST_NAMES)}"
    elif name in ("name", "label"):
        value = f"{_ADJECTIVES[index % len(_ADJECTIVES)]} {rng.choice(_NOUNS)}"
    elif name in ("title", "summary", "subject"):
        value = f"{rng.choice(_VERBS)} {rng.choice(_OBJECTS)}"
    else:
        value = rng.choice(_SENTENCES).split(",")[0].rstrip(".")
    if field.unique:
        value = f"{value} {index + 1}"
    return value


def _text(rng: random.Random) -> str:
    return " ".join(rng.sample(_SENTENCES, rng.randint(1, 3)))


_PART = re.compile(r"\[([^\]]+)\]|(\\d)|([A-Za-z0-9 _-])")
_COUNT = re.compile(r"\{(\d+)(?:,(\d+))?\}|([+*?])")


def _from_pattern(rng: random.Random, pattern: str) -> str | None:
    """Return a string that matches a simple pattern, or None for a pattern that is too complex.

    The supported patterns are a sequence of character classes (`[A-Z]`,
    `[a-z0-9]`, `\\d`) and literal characters, each with an optional count
    (`{n}`, `{m,n}`, `+`, `*`, or `?`), between `^` and `$`.
    """
    body = pattern.removeprefix("^").removesuffix("$")
    parts: list[tuple[str, int, int]] = []
    position = 0
    while position < len(body):
        match = _PART.match(body, position)
        if match is None:
            return None
        chars = _class_chars(match.group(1)) if match.group(1) else None
        if match.group(2):
            chars = "0123456789"
        elif match.group(3):
            chars = match.group(3)
        if not chars:
            return None
        position = match.end()
        low = high = 1
        count = _COUNT.match(body, position)
        if count is not None:
            position = count.end()
            if count.group(1):
                low = int(count.group(1))
                high = int(count.group(2)) if count.group(2) else low
            else:
                low, high = {"+": (1, 3), "*": (0, 3), "?": (0, 1)}[count.group(3)]
        parts.append((chars, low, high))
    for _ in range(100):
        value = "".join(
            "".join(rng.choice(chars) for _ in range(rng.randint(low, high)))
            for chars, low, high in parts
        )
        if re.fullmatch(body, value):
            return value
    return None


def _class_chars(spec: str) -> str:
    chars: list[str] = []
    position = 0
    while position < len(spec):
        if position + 2 < len(spec) and spec[position + 1] == "-":
            start, end = ord(spec[position]), ord(spec[position + 2])
            chars.extend(chr(code) for code in range(start, end + 1))
            position += 3
        else:
            chars.append(spec[position])
            position += 1
    return "".join(chars)
