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

`file` names a local data file with more records: YAML, JSON, or CSV.
The loader reads it before the model, and adds its records to `records`
(`read_seed_files`). The source map of each record of a file points to
the file, so that each diagnostic gives the path of the file and the
line of the record.
"""

import csv
import datetime
import difflib
import hashlib
import io
import json
import math
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast
from urllib.parse import urlparse

import pydantic
from pydantic import ConfigDict, PrivateAttr, StringConstraints

from appgen.dsl.diagnostics import DefinitionError, Diagnostic, Location
from appgen.dsl.element import Element, Text
from appgen.dsl.source import DataPath, SourceMap, read_yaml
from appgen.dsl.storage import SeedFile

if TYPE_CHECKING:
    from appgen.dsl.model import Field, Relation

RECORD_KEY_PATTERN = r"^[A-Za-z0-9_]+$"
SEED_NAMESPACE = uuid.UUID("97298d18-e518-4f95-9016-d8efd1b8eab0")
"""The namespace of the UUIDs of the seed records. Do not change it: it gives the IDs."""

type RecordKey = Annotated[str, StringConstraints(pattern=RECORD_KEY_PATTERN)]
"""The key of a seed record. It is a segment of an element ID, so it has only letters, digits,
and `_`."""

DATA_FILE_SUFFIXES = (".yaml", ".yml", ".json", ".csv")
CSV_KEY_COLUMN = "key"
CSV_LIST_SEPARATOR = ";"
"""The separator of the keys in a `many_to_many` cell of a CSV file."""

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_INTEGER = re.compile(r"^[+-]?[0-9]+$")
_DECIMAL = re.compile(r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$")


class SeedRecord(Element):
    """A seed record: the values of its fields and relations, by name."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, Any] = pydantic.Field(init=False)  # pyright: ignore[reportIncompatibleVariableOverride]

    _files: dict[str, SeedFile] = PrivateAttr(default_factory=dict[str, SeedFile])

    @property
    def files(self) -> dict[str, SeedFile]:
        """The file of each file field with a value, by field name (ADR 0027).

        The loader reads the files from the folder of the definition.
        """
        return dict(self._files)

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
    file: Text | None = None
    """A local data file with more records, from the folder of the definition: YAML, JSON, or
    CSV."""
    mock: Annotated[int, pydantic.Field(ge=0)] = 0
    """The number of generated records in addition to the seed records."""

    _file_hash: str | None = PrivateAttr(default=None)

    @property
    def file_hash(self) -> str | None:
        """The SHA-256 hash of the data file, as the output manifest records it, or None."""
        return self._file_hash


def record_id(app: str, entity: str, key: str) -> str:
    """Return the ID of a seed record: a UUID (version 5) from the app, the entity, and the key."""
    return str(uuid.uuid5(SEED_NAMESPACE, f"{app}:{entity}:{key}"))


def normal_value(field: Field, value: object) -> Any:
    """Return a value of a field in its normal form. Raise ValueError if it does not suit the type.

    A date is `YYYY-MM-DD`. A date-time is in UTC, for example
    `2026-01-05T09:30:00Z`: a date-time without an offset is in UTC. A
    UUID is in small letters. A file is the path of a local file (ADR
    0027). None stays None. The function does not check the options of
    the field (`min`, `max_length`, and so on), or the file of a path.
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
        case "file" | "image":
            text = _string(value)
            if not text.strip():
                raise ValueError("expected the path of a file, for example 'files/logo.png'")
            return text


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


def read_seed_files(
    data: object, source_map: SourceMap, base_dir: Path
) -> tuple[list[Diagnostic], dict[str, str]]:
    """Add the records of the data files to the `records` of each seed, before the model.

    The function points the source map of each record of a file to its
    place in the file. Return the diagnostics of the files, and the hash
    of each file by entity name.
    """
    diagnostics: list[Diagnostic] = []
    hashes: dict[str, str] = {}
    sections = cast(dict[str, object], data) if isinstance(data, dict) else {}
    seed = sections.get("seed")
    if not isinstance(seed, dict):
        return diagnostics, hashes
    for name, value in cast(dict[str, object], seed).items():
        if not isinstance(value, dict):
            continue
        entity_seed = cast(dict[str, object], value)
        file = entity_seed.get("file")
        if not isinstance(file, str) or not file:
            continue  # The model reports a value of the wrong type.
        prefix: DataPath = ("seed", name, "records")
        reader = _DataFile(file, source_map.value(("seed", name, "file")), f"seed.{name}")
        try:
            records, file_map, content = reader.read(base_dir, _members(sections, name))
        except DefinitionError as error:
            diagnostics += error.diagnostics
            continue
        hashes[name] = "sha256:" + hashlib.sha256(content).hexdigest()
        inline = entity_seed.setdefault("records", {})
        if not isinstance(inline, dict):
            continue
        inline = cast(dict[str, object], inline)
        for key, record in records.items():
            location = file_map.element((key,))
            if key in inline:
                diagnostics.append(
                    Diagnostic(
                        code="duplicate-key",
                        message=f"The record '{key}' is in 'records' and in the file '{file}'.",
                        location=location,
                        element_id=f"seed.{name}.records.{key}",
                        hint=f"The other record is at {source_map.element((*prefix, key))}.",
                    )
                )
                continue
            inline[key] = record
            for places, file_places in (
                (source_map.keys, file_map.keys),
                (source_map.values, file_map.values),
            ):
                for path, place in file_places.items():
                    if path[:1] == (key,):
                        places[(*prefix, *path)] = place
    return diagnostics, hashes


type _Members = dict[str, tuple[str, str]] | None
"""The fields and the relations of an entity: the kind (`field` or `relation`), and the type of
the field or the kind of the relation, by name. None for an entity that does not exist."""


def _members(sections: dict[str, object], name: str) -> _Members:
    """Return the members of an entity from the plain data, or None if it does not exist."""
    entities = sections.get("entities")
    entity = cast(dict[str, object], entities).get(name) if isinstance(entities, dict) else None
    if not isinstance(entity, dict):
        return None
    members: dict[str, tuple[str, str]] = {}
    for key, kind, attribute in (("fields", "field", "type"), ("relations", "relation", "kind")):
        items = cast(dict[str, object], entity).get(key)
        if not isinstance(items, dict):
            continue
        for member, spec in cast(dict[str, object], items).items():
            if isinstance(spec, dict):
                members[member] = (kind, str(cast(dict[str, object], spec).get(attribute)))
    return members


class _DataFile:
    """The reader of one data file of a seed."""

    def __init__(self, file: str, location: Location, element_id: str) -> None:
        self.file = file
        self.location = location
        self.element_id = element_id

    def read(self, base_dir: Path, members: _Members) -> tuple[dict[str, object], SourceMap, bytes]:
        """Return the records of the file, their source map, and the content of the file."""
        if "://" in self.file:
            raise self._error("The data file must be a local file, not a URL.")
        path = base_dir / self.file
        if path.suffix.lower() not in DATA_FILE_SUFFIXES:
            raise self._error(
                f"The data file '{self.file}' must be a .yaml, .yml, .json, or .csv file."
            )
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            raise self._error(f"The data file '{self.file}' does not exist.") from None
        except OSError as error:
            raise self._error(f"Cannot read the data file: {error.strerror or error}.") from None
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise self._error(f"The data file '{self.file}' is not UTF-8 text.") from None
        if path.suffix.lower() == ".csv":
            records, source = _CsvReader(str(path), self.element_id, members).read(text)
        else:
            records, source = self._mapping(text, str(path))
        return records, source, content

    def _mapping(self, text: str, file: str) -> tuple[dict[str, object], SourceMap]:
        source = SourceMap(file=file, root=Location(file, 1, 1))
        try:
            document = read_yaml(text, file)
            data, source = document.data, document.source_map
        except DefinitionError:
            if not file.lower().endswith(".json"):
                raise
            try:
                data = json.loads(text)
            except ValueError as error:
                raise DefinitionError(
                    [
                        Diagnostic(
                            code="invalid-data-file",
                            message=f"The data file is not valid JSON: {error}.",
                            location=source.root,
                            element_id=self.element_id,
                        )
                    ]
                ) from None
        if not isinstance(data, dict):
            raise DefinitionError(
                [
                    Diagnostic(
                        code="invalid-data-file",
                        message="The data file must be a mapping from a record key to a record.",
                        location=source.root,
                        element_id=self.element_id,
                    )
                ]
            )
        return cast(dict[str, object], data), source

    def _error(self, message: str) -> DefinitionError:
        return DefinitionError(
            [
                Diagnostic(
                    code="invalid-data-file",
                    message=message,
                    location=self.location,
                    element_id=self.element_id,
                    hint="Give the path of a file, from the folder of the definition.",
                )
            ]
        )


class _CsvReader:
    """Read the rows of a CSV file as records, and convert each cell to the type of its field."""

    def __init__(self, file: str, element_id: str, members: _Members) -> None:
        self.file = file
        self.element_id = element_id
        self.members = members
        self.source = SourceMap(file=file, root=Location(file, 1, 1))
        self.diagnostics: list[Diagnostic] = []

    def read(self, text: str) -> tuple[dict[str, object], SourceMap]:
        rows = self._rows(text)
        if not rows:
            raise DefinitionError([self._diagnostic("The CSV file has no header.", 1)])
        header_line, header = rows[0]
        columns = self._columns(header, header_line)
        records: dict[str, object] = {}
        for line, row in rows[1:]:
            key, record = self._record(columns, row, line)
            if key is None:
                continue
            location = Location(self.file, line, 1)
            if key in records:
                self.diagnostics.append(
                    Diagnostic(
                        code="duplicate-key",
                        message=f"The key '{key}' occurs more than one time in the file.",
                        location=location,
                        element_id=f"{self.element_id}.records.{key}",
                        hint=f"The first occurrence is at {self.source.keys[(key,)]}.",
                    )
                )
                continue
            records[key] = record
            self.source.keys[(key,)] = self.source.values[(key,)] = location
            for column in record:
                self.source.keys[(key, column)] = self.source.values[(key, column)] = location
        if self.diagnostics:
            raise DefinitionError(self.diagnostics)
        return records, self.source

    def _rows(self, text: str) -> list[tuple[int, list[str]]]:
        """Return the rows that are not empty, with the line where each row starts."""
        reader = csv.reader(io.StringIO(text, newline=""))
        rows: list[tuple[int, list[str]]] = []
        end = 0
        try:
            for row in reader:
                start, end = end + 1, reader.line_num
                if any(cell.strip() for cell in row):
                    rows.append((start, row))
        except csv.Error as error:
            raise DefinitionError(
                [self._diagnostic(f"The CSV file is not valid: {error}.", reader.line_num)]
            ) from None
        return rows

    def _columns(self, header: list[str], line: int) -> list[str]:
        columns = [cell.strip() for cell in header]
        known = self.members
        seen: set[str] = set()
        for column in columns:
            if not column:
                self.diagnostics.append(
                    self._diagnostic("A column of the header has no name.", line)
                )
            elif column in seen:
                self.diagnostics.append(
                    Diagnostic(
                        code="duplicate-key",
                        message=f"The column '{column}' occurs more than one time in the header.",
                        location=Location(self.file, line, 1),
                        element_id=self.element_id,
                    )
                )
            elif column != CSV_KEY_COLUMN and known is not None and column not in known:
                matches = difflib.get_close_matches(column, list(known), n=1)
                self.diagnostics.append(
                    Diagnostic(
                        code="unknown-key",
                        message=f"The entity has no field or relation '{column}' (a column of "
                        "the header).",
                        location=Location(self.file, line, 1),
                        element_id=self.element_id,
                        hint=f"Did you mean '{matches[0]}'?" if matches else None,
                    )
                )
            seen.add(column)
        if CSV_KEY_COLUMN not in columns:
            self.diagnostics.append(
                self._diagnostic(f"The header has no column '{CSV_KEY_COLUMN}'.", line)
            )
        if self.diagnostics:
            raise DefinitionError(self.diagnostics)
        return columns

    def _record(
        self, columns: list[str], row: list[str], line: int
    ) -> tuple[str | None, dict[str, object]]:
        if len(row) > len(columns):
            self.diagnostics.append(
                self._diagnostic(
                    f"The row has {len(row)} cells, but the header has {len(columns)} columns.",
                    line,
                )
            )
            return None, {}
        cells = dict(zip(columns, row, strict=False))
        key = cells.get(CSV_KEY_COLUMN, "").strip()
        if not key:
            self.diagnostics.append(
                Diagnostic(
                    code="missing-key",
                    message=f"The row has no value in the column '{CSV_KEY_COLUMN}'.",
                    location=Location(self.file, line, 1),
                    element_id=self.element_id,
                )
            )
            return None, {}
        record: dict[str, object] = {}
        for column, cell in cells.items():
            if column == CSV_KEY_COLUMN or not cell.strip():
                continue
            member = self.members.get(column) if self.members is not None else None
            try:
                record[column] = _cell_value(cell, member)
            except ValueError as error:
                self.diagnostics.append(
                    Diagnostic(
                        code="invalid-value",
                        message=f"The cell {cell!r} of the column '{column}' is not valid: "
                        f"{error}.",
                        location=Location(self.file, line, 1),
                        element_id=f"{self.element_id}.records.{key}",
                    )
                )
        return key, record

    def _diagnostic(self, message: str, line: int) -> Diagnostic:
        return Diagnostic(
            code="invalid-data-file",
            message=message,
            location=Location(self.file, line, 1),
            element_id=self.element_id,
        )


def _cell_value(cell: str, member: tuple[str, str] | None) -> object:
    """Convert the text of a CSV cell to the type of its field, or to the keys of a relation."""
    if member is None:
        return cell
    kind, type_ = member
    text = cell.strip()
    if kind == "relation":
        if type_ == "many_to_many":
            return [part.strip() for part in text.split(CSV_LIST_SEPARATOR) if part.strip()]
        return text
    match type_:
        case "integer":
            if not _INTEGER.fullmatch(text):
                raise ValueError("expected an integer")
            return int(text)
        case "decimal":
            if not _DECIMAL.fullmatch(text):
                raise ValueError("expected a number")
            return float(text)
        case "boolean":
            if text.lower() not in ("true", "false"):
                raise ValueError("expected true or false")
            return text.lower() == "true"
        case "json":
            try:
                return cast(object, json.loads(text))
            except ValueError:
                raise ValueError("expected JSON text") from None
        case "date" | "datetime" | "uuid" | "enum" | "file" | "image":
            return text
        case _:
            return cell
