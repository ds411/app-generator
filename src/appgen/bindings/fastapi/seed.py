"""The seed of the FastAPI app (ADR 0021): the rows of each table as Python literals.

The rows come from the shared generator (`appgen.bindings.shared.mock_data`),
so the FastAPI seed, the Next.js seed, and the React mock data have the
same records with the same IDs. The seed records of the definition come
first in the mock records: they go into `records`, with the element of
each record for its trace. The generated records go into `rows`. A table
comes after the tables that its required foreign keys refer to. The
optional foreign keys are links: the seed sets them after it inserts
all rows, so a cycle or a reference to the same table is no problem.
"""

import base64
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from appgen.bindings.fastapi.pysource import call, import_block, literal, string
from appgen.bindings.shared.mock_data import mock_data, seed_records
from appgen.dsl.model import AppDefinition
from appgen.dsl.storage import SeedFile
from appgen.gen.naming import constant

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyApp, PyEntity, PyField, PyJoinTable

_ROW_INDENT = 4
"""The indent of a row in its list: each row is an item of a module constant."""


@dataclass(frozen=True, slots=True)
class PySeedRecord:
    """A seed record of the definition, as a Python dict literal."""

    element_id: str
    """The element of the record, for example `seed.Room.records.a101`."""
    row: str


@dataclass(slots=True)
class PySeedJoin:
    """The rows of a join table: the links of a `many_to_many` relation."""

    join: PyJoinTable
    owner: str
    """The table of the records in the column `join.left_column`."""
    records: list[str] = field(default_factory=list[str])
    """The rows of the seed records of the definition."""
    rows: list[str] = field(default_factory=list[str])
    """The rows of the generated records."""

    @property
    def const(self) -> str:
        return constant(self.join.name)

    def join_call(self) -> str:
        """Return the `SeedJoin(...)` item of `JOINS` in the seed data module."""
        args = [string(self.join.name), string(self.owner), string(self.join.left_column)]
        if self.records:
            args.append(f"records={self.const}_RECORDS")
        if self.rows:
            args.append(f"rows={self.const}_ROWS")
        return call("", "SeedJoin", args, 4, ",")


@dataclass(slots=True)
class PySeedTable:
    """The seed rows of the table of an entity."""

    entity: PyEntity
    seed_id: str | None = None
    """The seed element of the entity, for example `seed.Room`, if the definition has one."""
    records: list[PySeedRecord] = field(default_factory=list[PySeedRecord])
    record_links: list[str] = field(default_factory=list[str])
    rows: list[str] = field(default_factory=list[str])
    """The generated rows. An optional foreign key is None here."""
    links: list[str] = field(default_factory=list[str])
    """The optional foreign keys of the generated rows (`id` and the keys)."""
    joins: list[PySeedJoin] = field(default_factory=list[PySeedJoin])

    @property
    def const(self) -> str:
        """The prefix of the names of the module constants, for example `ROOM`."""
        return constant(self.entity.table)

    def table_call(self) -> str:
        """Return the `SeedTable(...)` item of `TABLES` in the seed data module."""
        args = [string(self.entity.table)]
        for name, values in (
            ("records", self.records),
            ("record_links", self.record_links),
            ("rows", self.rows),
            ("links", self.links),
        ):
            if values:
                args.append(f"{name}={self.const}_{name.upper()}")
        return call("", "SeedTable", args, 4, ",")


@dataclass(frozen=True, slots=True)
class PySeedFile:
    """The file of a file field of a seed record (ADR 0027), as Base64 text in the code."""

    element_id: str
    """The element of the record, for example `seed.Task.records.board`."""
    key: str
    """The key of the file in the storage, for example `tasks/<id>/screenshot/seed-<hash>`."""
    type: str
    content: str
    """The content in Base64."""

    _CHUNK = 76

    def lines(self) -> list[str]:
        """Return the lines of the content: Python strings that Python joins."""
        return [
            string(self.content[i : i + self._CHUNK])
            for i in range(0, len(self.content), self._CHUNK)
        ] or ['""']


@dataclass(frozen=True, slots=True)
class PySeedChange:
    """A seed record that the generated test changes or deletes before a second seed."""

    table: str
    id: str
    column: str | None = None
    """The text column that the test changes, or None for a record that it deletes."""
    value: str = ""


@dataclass(frozen=True, slots=True)
class PySeed:
    """The seed data module of the app."""

    tables: list[PySeedTable]
    """The tables in the order of the inserts."""
    imports: str
    user_table: str | None
    """The table of the users, with the sign-in with a password: the seed gives them passwords."""
    change: PySeedChange | None = None
    """A seed record with a text field, which the test changes: the second seed keeps it."""
    remove: PySeedChange | None = None
    """A seed record that no record refers to, which the test deletes: the second seed adds it."""
    files: list[PySeedFile] = field(default_factory=list[PySeedFile])
    """The files of the file fields of the seed records (ADR 0027)."""

    @property
    def joins(self) -> list[PySeedJoin]:
        return [j for t in self.tables for j in t.joins]

    @property
    def added(self) -> int:
        """The number of records that the first seed adds."""
        return sum(len(table.records) + len(table.rows) for table in self.tables)

    def counts(self) -> dict[str, int]:
        """Return the number of rows of each table after the seed, for the generated test."""
        result: dict[str, int] = {}
        for table in self.tables:
            result[table.entity.table] = len(table.records) + len(table.rows)
        for join in self.joins:
            result[join.join.name] = len(join.records) + len(join.rows)
        if self.user_table is not None:
            result["credentials"] = result[self.user_table]
        return result


def python_seed(definition: AppDefinition, py: PyApp) -> PySeed:
    """Return the seed data module of an app definition."""
    data = mock_data(definition)
    seeds = seed_records(definition)
    uses: set[str] = set()
    tables: dict[str, PySeedTable] = {}
    files: list[PySeedFile] = []
    for name, entity in py.entities.items():
        seed = definition.seed.get(name)
        keys = list(seed.records) if seed is not None else []
        owners = {join.name: entity.table for join in entity.join_tables}
        table = PySeedTable(
            entity,
            seed_id=seed.id if seed is not None else None,
            joins=[PySeedJoin(join, owners[join.name]) for join in entity.join_tables],
        )
        fixed = len(seeds.get(name, []))
        for index, record in enumerate(data[name]):
            stored: dict[str, dict[str, Any]] = {}
            if index < fixed:
                assert seed is not None
                element_id = f"{seed.id}.records.{keys[index]}"
                for file_name, seed_file in seed.records[keys[index]].files.items():
                    py_file, value = _seed_file(element_id, entity, record, file_name, seed_file)
                    files.append(py_file)
                    stored[file_name] = value
            row, link = _row(entity, record, uses, stored)
            if index < fixed:
                assert seed is not None
                table.records.append(PySeedRecord(f"{seed.id}.records.{keys[index]}", row))
                if link:
                    table.record_links.append(link)
            else:
                table.rows.append(row)
                if link:
                    table.links.append(link)
            for seed_join in table.joins:
                relation = seed_join.join.relation_id.rsplit(".", 1)[1]
                targets = cast(list[str], record.get(relation) or [])
                rows = seed_join.records if index < fixed else seed_join.rows
                for target in targets:
                    uses.add("UUID")
                    rows.append(
                        _dict(
                            [
                                (seed_join.join.left_column, _uuid(record["id"])),
                                (seed_join.join.right_column, _uuid(target)),
                            ]
                        )
                    )
        tables[name] = table
    lines = {"from dataclasses import dataclass, field", "from typing import Any"}
    if "UUID" in uses:
        lines.add("from uuid import UUID")
    if "dt" in uses:
        lines.add("import datetime as dt")
    if "Decimal" in uses:
        lines.add("from decimal import Decimal")
    auth = definition.auth
    user_table = py.entities[auth.user_entity].table if auth and auth.password else None
    change, remove = _test_records(definition, py, data, seeds)
    return PySeed(
        [tables[name] for name in _insert_order(py)],
        import_block(lines),
        user_table,
        change,
        remove,
        files,
    )


def _seed_file(
    element_id: str, entity: PyEntity, record: dict[str, Any], name: str, seed_file: SeedFile
) -> tuple[PySeedFile, dict[str, Any]]:
    """Return the file of a file field of a seed record, and the value of its column.

    The key has a part of the hash of the content, so that a changed file
    gets a new key, as an upload does.
    """
    content = seed_file.content or b""
    key = f"{entity.table}/{record['id']}/{name}/seed-{seed_file.hash.removeprefix('sha256:')[:12]}"
    media_type = seed_file.media_type or "application/octet-stream"
    value = {"key": key, "name": seed_file.name, "size": len(content), "type": media_type}
    encoded = base64.b64encode(content).decode()
    return PySeedFile(element_id, key, media_type, encoded), value


_CHANGED = "Changed by the test"


def _test_records(
    definition: AppDefinition,
    py: PyApp,
    data: dict[str, list[dict[str, Any]]],
    seeds: dict[str, list[dict[str, Any]]],
) -> tuple[PySeedChange | None, PySeedChange | None]:
    """Return the seed record that the test of the seed changes, and the one that it deletes."""
    referred: set[str] = set()
    for records in data.values():
        for record in records:
            for name, value in record.items():
                items = cast(list[object], value) if isinstance(value, list) else [value]
                if name != "id":
                    referred.update(item for item in items if isinstance(item, str))
    change: PySeedChange | None = None
    remove: PySeedChange | None = None
    for name, records in seeds.items():
        entity = definition.entities[name]
        table = py.entities[name].table
        texts = [
            n
            for n, spec in entity.stored_fields.items()
            if spec.type in ("string", "text") and not spec.unique and spec.pattern is None
        ]
        for record in records:
            if change is None and texts:
                size = entity.stored_fields[texts[0]].max_length or len(_CHANGED)
                change = PySeedChange(table, record["id"], texts[0], _CHANGED[:size])
            elif remove is None and record["id"] not in referred:
                remove = PySeedChange(table, record["id"])
    return change, remove


def _row(
    entity: PyEntity,
    record: dict[str, Any],
    uses: set[str],
    files: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, str | None]:
    """Return the row of a record and its link (the optional foreign keys), or None.

    `files` has the value of each file field of a seed record with a file.
    """
    uses.add("UUID")
    row = [("id", _uuid(record["id"]))]
    link: list[tuple[str, str]] = []
    for py_field in entity.fields:
        row.append((py_field.name, _value(py_field, record.get(py_field.name), uses)))
    for py_file in entity.files:
        value = (files or {}).get(py_file.name)
        prefix = f"{string(py_file.name)}: "
        text = literal(value, prefix, _ROW_INDENT + 4, ",")
        row.append((py_file.name, text.removeprefix(prefix).removesuffix(",")))
    for relation in entity.fk_relations:
        assert relation.fk is not None
        value = cast(str | None, record.get(relation.name))
        if relation.required:
            row.append((relation.fk, _uuid(value) if value is not None else "None"))
        else:
            row.append((relation.fk, "None"))
            if value is not None:
                link.append((relation.fk, _uuid(value)))
    if not link:
        return _dict(row), None
    return _dict(row), _dict([row[0], *link])


def _dict(entries: list[tuple[str, str]]) -> str:
    """Return a row as a dict literal with one key on each line, as an item of a list."""
    pad = " " * (_ROW_INDENT + 4)
    inner = "".join(f"{pad}{string(key)}: {value},\n" for key, value in entries)
    return "{\n" + inner + " " * _ROW_INDENT + "}"


def _value(py_field: PyField, value: Any, uses: set[str]) -> str:
    if value is None:
        return "None"
    match py_field.type:
        case "uuid":
            uses.add("UUID")
            return _uuid(value)
        case "date":
            uses.add("dt")
            return f'dt.date.fromisoformat("{value}")'
        case "datetime":
            uses.add("dt")
            return f'dt.datetime.fromisoformat("{value}")'
        case "decimal":
            uses.add("Decimal")
            return f'Decimal("{json.dumps(value)}")'
        case "json":
            prefix = f"{string(py_field.name)}: "
            text = literal(value, prefix, _ROW_INDENT + 4, ",")
            return text.removeprefix(prefix).removesuffix(",")
        case _:
            return literal(value)


def _uuid(value: str) -> str:
    return f'UUID("{value}")'


def _insert_order(py: PyApp) -> list[str]:
    """Return the entities so that each comes after the targets of its required foreign keys."""
    needs = {
        name: {r.target for r in entity.required_parents} for name, entity in py.entities.items()
    }
    order: list[str] = []
    while len(order) < len(needs):
        ready = [e for e in needs if e not in order and needs[e] <= set(order)]
        # A cycle of required foreign keys: keep the order of the definition.
        order.append(ready[0] if ready else next(e for e in needs if e not in order))
    return order
