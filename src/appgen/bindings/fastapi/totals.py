"""The totals of the relations in the computed fields of the FastAPI app (ADR 0034).

A total, for example `sum(lines.amount)` or `count(votes)`, is a column
property of the model with a correlated subquery (`app/core/totals.py`),
so that each query of the model reads the total of each record: the
reads, the lists, and the embedded records. `app/models.py` adds the
column property after it imports all models, because the subquery needs
the model of the related records. The model declares the attribute for
pyright. The property of the computed field reads the column properties.

When the expression of a computed field has only totals, numbers, the
stored number fields of the record, `+`, `-`, and `*`, it has an SQL
form. The list endpoint then sorts by the field, and filters it with the
parameters `<field>_min` and `<field>_max`.

A compare rule with a total, for example `sum(lines.debit)` equal to
`sum(lines.credit)`, reads the column property of the total too. A total
that only the rules use is a deferred column property: the queries do not
read it, and `check_totals` of the repository reads it again after a
change.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import JsonValue

from appgen.bindings.fastapi.dashboards import FilterBuilder, FilterValues, TestValue, passes
from appgen.bindings.fastapi.pysource import LINE_LENGTH, from_import, import_block
from appgen.bindings.fastapi.queries import Call, Expr, render, resolve_path
from appgen.dsl.expressions import (
    Binary,
    Expression,
    FieldRef,
    Negate,
    Number,
    Total,
    expression_totals,
    parse_expression,
)
from appgen.dsl.expressions import Call as FunctionCall
from appgen.dsl.model import AppDefinition
from appgen.dsl.model import Field as DslField
from appgen.dsl.rules import EntityCompareRule
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyComputed, PyEntity, PyField, PyRelation

_TODAY = dt.date(2026, 6, 15)
"""The date of the filter values of the tests. A filter of a total has no `$today`."""


@dataclass(slots=True)
class _Conditions:
    """The target of a `FilterBuilder` for the filter of a total: the conditions of the filter."""

    id: str
    entity: PyEntity
    joins: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    where: list[Expr] = field(default_factory=list[Expr])
    today: bool = False
    now: bool = False


@dataclass(slots=True)
class PyTotal:
    """A total of the records of a relation: a column property of the model."""

    attr: str
    """The attribute of the model, for example `sum_lines_amount`."""
    function: str
    """`count`, `sum`, `avg`, `min`, or `max`."""
    entity: PyEntity
    relation: PyRelation
    target: PyEntity
    number: PyField | None
    """The number field of the related records. None for `count`."""
    source: str
    """The class of the related records in the subquery, or its alias for a relation of the
    entity to itself."""
    conditions: list[Expr]
    """The join of the related records to the record, and the conditions of the filter."""
    via: str | None = None
    """For a many-to-many relation: the join table."""
    ids: list[str] = field(default_factory=list[str])
    """The computed fields and the rules that use the total, for the traces."""
    deferred: bool = False
    """True if only the rules use the total: the queries do not read it."""

    @property
    def type(self) -> str:
        """The Python type of the value: `int`, or `Decimal`."""
        if self.function == "count":
            return "int"
        assert self.number is not None
        return "int" if self.number.type == "integer" and self.function != "avg" else "Decimal"

    @property
    def nullable(self) -> bool:
        """True if the total of no records is None: `avg`, `min`, and `max`."""
        return self.function not in ("count", "sum")

    def declaration(self) -> str:
        """Return the declaration of the attribute in the model, for pyright."""
        return f"{self.attr}: Mapped[{self.type}{' | None' if self.nullable else ''}]"

    def assignment(self) -> str:
        """Return the statement of `app/models.py` that adds the column property."""
        value = f"{self.source}.{self.number.attr}" if self.number is not None else "None"
        args: list[Expr] = [f'"{self.function}"', self.source, value, *self.conditions]
        if self.via is not None:
            args.append(f"via={self.via}")
        inner = Call("totals.total", tuple(args))
        options: tuple[Expr, ...] = ("deferred=True",) if self.deferred else ()
        return render(
            Call("column_property", (inner, *options)), 0, f"{self.entity.name}.{self.attr} = "
        )


def entity_totals(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    entity_name: str,
    field_name: str,
    expression: Expression,
) -> dict[str, PyTotal]:
    """Add the totals of a computed field to its entity, and return them by their text.

    Two computed fields share a total without a filter. Raise
    GenerationError if the attribute of a total is the name of a member of
    the entity.
    """
    py_entity = entities[entity_name]
    dsl_entity = definition.entities[entity_name]
    computed = dsl_entity.fields[field_name]
    found: dict[str, PyTotal] = {}
    for total in expression_totals(expression):
        text = str(total)
        if text in found:
            continue
        parts = [total.function, total.relation, *([total.field] if total.field else [])]
        attr = "_".join([field_name, *parts] if computed.filter else parts)
        if attr in dsl_entity.fields or attr in dsl_entity.relations:
            raise GenerationError(
                f"The total '{text}' of the computed field '{entity_name}.{field_name}' needs "
                f"the attribute '{attr}' in the FastAPI app, but the entity has a member "
                f"'{attr}'. Rename the member."
            )
        existing = next((t for t in py_entity.totals if t.attr == attr), None)
        if existing is None:
            existing = _total(definition, entities, py_entity, total, attr, computed)
            py_entity.totals.append(existing)
        existing.deferred = False
        if computed.id not in existing.ids:
            existing.ids.append(computed.id)
        found[text] = existing
    return found


def rule_totals(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    entity_name: str,
    rule: EntityCompareRule,
) -> dict[str, PyTotal]:
    """Add the totals of a compare rule to its entity, and return them by the sides of the rule.

    A rule shares the total of a computed field without a filter. A new
    total is deferred. Raise GenerationError if the attribute of a total is
    the name of a member of the entity.
    """
    py_entity = entities[entity_name]
    dsl_entity = definition.entities[entity_name]
    found: dict[str, PyTotal] = {}
    for side in rule.totals:
        total = parse_expression(side)
        assert isinstance(total, Total)
        attr = "_".join([total.function, total.relation, *([total.field] if total.field else [])])
        if attr in dsl_entity.fields or attr in dsl_entity.relations:
            raise GenerationError(
                f"The total '{total}' of the rule '{rule.id}' needs the attribute '{attr}' in "
                f"the FastAPI app, but the entity has a member '{attr}'. Rename the member."
            )
        existing = next((t for t in py_entity.totals if t.attr == attr), None)
        if existing is None:
            existing = _total(definition, entities, py_entity, total, attr, None)
            existing.deferred = True
            py_entity.totals.append(existing)
        if rule.id not in existing.ids:
            existing.ids.append(rule.id)
        found[side] = existing
    return found


def _total(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    entity: PyEntity,
    total: Total,
    attr: str,
    computed: DslField | None,
) -> PyTotal:
    relation = next(r for r in entity.relations if r.name == total.relation)
    target = entities[relation.target]
    source = f"{entity.snake}_{relation.attr}" if target.name == entity.name else target.name
    py_field = None
    if total.field is not None:
        py_field = next(f for f in target.fields if f.name == total.field)
    via = None
    if relation.side == "m2m":
        via = relation.secondary
        conditions: list[Expr] = [
            f"{via}.c.{relation.local_column} == {entity.name}.id",
            f"{via}.c.{relation.remote_column} == {source}.id",
        ]
    else:
        remote = next(r for r in target.relations if r.name == relation.back_populates)
        conditions = [f"{source}.{remote.fk_attr} == {entity.name}.id"]
    if computed is not None and computed.filter:
        builder_target = _Conditions(computed.id, target)
        builder = FilterBuilder(definition, builder_target, "total", source=source)
        for path, condition in computed.filter.items():
            builder.filter(path, condition)
        conditions += builder_target.where
    return PyTotal(
        attr, total.function, entity, relation, target, py_field, source, conditions, via
    )


def computed_sql(
    entity: PyEntity, expression: Expression, totals: dict[str, PyTotal]
) -> str | None:
    """Return the SQL form of a computed field with totals, as SQLAlchemy code, or None.

    The SQL form has the totals, numbers, the stored number fields of the
    record, `+`, `-`, `*`, and the negative. A division, a field of a
    related record, and the time functions have no SQL form here.
    """
    if not totals:
        return None
    found = _sql(entity, expression, totals)
    return found[0] if found is not None else None


_PRECEDENCE = {"+": 1, "-": 1, "*": 2}
_ATOM = 3


def _sql(
    entity: PyEntity, expression: Expression, totals: dict[str, PyTotal]
) -> tuple[str, int] | None:
    """Return the code of an expression and its precedence, or None without an SQL form."""
    match expression:
        case Number(value):
            return f'Decimal("{value}")', _ATOM
        case Total():
            return f"{entity.name}.{totals[str(expression)].attr}", _ATOM
        case FieldRef(path):
            f = next((f for f in entity.fields if f.name == path), None)
            if f is None or f.type not in ("integer", "decimal"):
                return None
            return f"{entity.name}.{f.attr}", _ATOM
        case Binary(op, left, right) if op in _PRECEDENCE:
            a = _sql(entity, left, totals)
            b = _sql(entity, right, totals)
            if a is None or b is None:
                return None
            precedence = _PRECEDENCE[op]
            left_code = a[0] if a[1] >= precedence else f"({a[0]})"
            right_code = b[0] if b[1] > precedence else f"({b[0]})"
            return f"{left_code} {op} {right_code}", precedence
        case Negate(operand):
            inner = _sql(entity, operand, totals)
            if inner is None:
                return None
            return f"-{inner[0]}" if inner[1] == _ATOM else f"-({inner[0]})", _ATOM
        case _:
            return None


def models_head(entities: list[PyEntity]) -> str:
    """Return the imports of `app/models.py` from the standard library and SQLAlchemy."""
    totals = [t for e in entities for t in e.totals]
    orm = {"configure_mappers"}
    lines: set[str] = set()
    if totals:
        orm.add("column_property")
        code = "\n".join(t.assignment() for t in totals)
        if any(t.source != t.target.name for t in totals):
            orm.add("aliased")
        if "Decimal(" in code:
            lines.add("from decimal import Decimal")
        if "dt." in code:
            lines.add("import datetime as dt")
        if "UUID(" in code:
            lines.add("from uuid import UUID")
        sql = {n for n in ("and_", "false", "not_", "or_", "true") if f"{n}(" in code}
        if sql:
            lines.add(from_import("sqlalchemy", sql))
    lines.add(from_import("sqlalchemy.orm", orm))
    return import_block(lines)


def models_imports(
    entities: list[PyEntity], first: list[tuple[list[str], str]]
) -> list[tuple[list[str], str]]:
    """Return the imports of `app/models.py` from the app: the traces and the line of each.

    `first` are the imports from `app.core` with their traces. Each model
    import has the trace of its entity. The totals add `app.core.totals`,
    the join tables, and the enums of their filters, without a trace.
    """
    totals = [t for e in entities for t in e.totals]
    code = "\n".join(t.assignment() for t in totals)
    found: list[tuple[str, list[str], set[str]]] = []
    if totals:
        found.append(("app.core", [], {"totals"}))
    for ids, line in first:
        module, _, names = line.removeprefix("from ").partition(" import ")
        found.append((module, ids, {n.strip() for n in names.split(",")}))
    for e in entities:
        names = {e.name} | {t.via for t in totals if t.via in {j.name for j in e.join_tables}}
        found.append((f"app.features.{e.slice}.models", [e.id], {n for n in names if n}))
        enums = {f.enum.name for f in e.fields if f.enum is not None and f"{f.enum.name}." in code}
        if enums:
            found.append((f"app.features.{e.slice}.enums", [], enums))
    found.sort(key=lambda item: item[0])
    return [(ids, from_import(module, names)) for module, ids, names in found]


def models_code(entities: list[PyEntity]) -> list[tuple[list[str], str]]:
    """Return the statements of `app/models.py` that add the totals: the traces and the code.

    A relation of an entity to itself needs an alias of the model in the subquery.
    """
    found: list[tuple[list[str], str]] = []
    aliases = sorted(
        {(t.source, t.target.name) for e in entities for t in e.totals if t.source != t.target.name}
    )
    if aliases:
        found.append(([], "\n".join(f"{alias} = aliased({target})" for alias, target in aliases)))
    found += [(t.ids, t.assignment()) for e in entities for t in e.totals]
    return found


def merge_imports(lines: set[str]) -> str:
    """Return an import block, with the `from` imports of one module in one line."""
    by_module: dict[str, set[str]] = {}
    other: set[str] = set()
    for line in lines:
        if line.startswith("from ") and "(" not in line:
            module, _, names = line.removeprefix("from ").partition(" import ")
            by_module.setdefault(module, set()).update(n.strip() for n in names.split(","))
        else:
            other.add(line)
    other |= {from_import(module, names) for module, names in by_module.items()}
    return import_block(other)


# The generated tests: three records with none, one, and all of the related records.


@dataclass(slots=True)
class RelatedSet:
    """The related records of the generated tests of the totals, through one relation."""

    relation: PyRelation
    target: PyEntity
    records: list[dict[str, str]]
    """The attributes and the Python values of each related record."""
    values: list[dict[str, object]]
    """The values of each related record, for the expected totals."""

    @property
    def constant(self) -> str:
        """The name of the list of the values in the test module, for example `LINES`."""
        return self.relation.attr.upper()

    @property
    def fk(self) -> str | None:
        """For a one-to-many relation: the foreign key attribute of the related records."""
        if self.relation.side == "m2m":
            return None
        inverse = next(r for r in self.target.relations if r.name == self.relation.back_populates)
        return inverse.fk_attr

    def record_lines(self) -> list[str]:
        """Return the lines of the values of the related records in the test module."""
        lines: list[str] = []
        for record in self.records:
            items = [f'"{attr}": {code}' for attr, code in record.items()]
            line = "    {" + ", ".join(items) + "},"
            if len(line) <= LINE_LENGTH:
                lines.append(line)
            else:
                lines += ["    {", *(f"        {item}," for item in items), "    },"]
        return lines


@dataclass(slots=True)
class TotalsCheck:
    """A computed field in the generated tests: its values in the three records."""

    name: str
    id: str
    values: list[object]
    """The value of each record: an int, a Decimal, or None."""
    sql: bool

    @property
    def json_values(self) -> str:
        """The values of the three records as JSON, in Python code."""
        return "[" + ", ".join(_json(v) for v in self.values) + "]"

    @property
    def python_values(self) -> str:
        return "[" + ", ".join(_python(v) for v in self.values) + "]"

    def bound(self) -> str | None:
        """The value of the second record as a query parameter, or None if it is empty."""
        value = self.values[1]
        return None if value is None else str(value)

    def selected(self, end: str) -> list[int]:
        """The indexes of the records that `_min` or `_max` with the bound selects."""
        bound = self.values[1]
        assert isinstance(bound, int | Decimal)
        return [
            i
            for i, v in enumerate(self.values)
            if isinstance(v, int | Decimal) and (v >= bound if end == "min" else v <= bound)
        ]


@dataclass(slots=True)
class TotalsTest:
    """The generated tests of the totals of an entity."""

    entity: PyEntity
    values: dict[str, str]
    """The values of the stored fields of the expressions, for the three records."""
    sets: list[RelatedSet]
    checks: list[TotalsCheck]
    read_path: str | None
    """The URL of the read endpoint of a record (an f-string), or None: the test lists it."""
    list_path: str | None
    """The URL of the list endpoint, or None: no tests of the sort and the filters."""

    @property
    def sql_checks(self) -> list[TotalsCheck]:
        return [c for c in self.checks if c.sql]

    @property
    def bound_checks(self) -> list[TotalsCheck]:
        return [c for c in self.sql_checks if c.bound() is not None]

    def make_args(self) -> str:
        """The arguments of the factory of the records, after `session`."""
        args = [f"{attr}={code}" for attr, code in self.values.items()]
        args += [
            f"{s.relation.ids_field}=[r.id for r in {s.relation.attr}[:count]]"
            for s in self.sets
            if s.relation.side == "m2m"
        ]
        return "".join(f", {a}" for a in args)

    def imports(self) -> str:
        """Return the import block of the test module."""
        code = "\n".join(
            [
                *self.values.values(),
                *(v for s in self.sets for r in s.records for v in r.values()),
                *(c.python_values for c in self.checks),
            ]
        )
        lines = {
            "from typing import Any",
            "import pytest",
            "from httpx import AsyncClient",
            "from sqlalchemy.ext.asyncio import AsyncSession",
        }
        entity = self.entity
        factories = {f"make_{entity.snake}", *(f"make_{s.target.snake}" for s in self.sets)}
        lines.add(from_import("tests.factories", factories))
        lines.add(f"from app.features.{entity.slice}.models import {entity.name}")
        if self.sql_checks and self.list_path is not None:
            lines.add("from tests.ordering import expected_order")
        if "Decimal(" in code:
            lines.add("from decimal import Decimal")
        if "dt." in code:
            lines.add("import datetime as dt")
        for e in [entity, *(s.target for s in self.sets)]:
            for enum in (f.enum for f in e.fields if f.enum is not None):
                if enum.name + "." in code:
                    lines.add(f"from app.features.{e.slice}.enums import {enum.name}")
        return merge_imports(lines)


def totals_test(definition: AppDefinition, entity: PyEntity) -> TotalsTest | None:
    """Return the generated tests of the totals of an entity, or None if it has none.

    A test checks a computed field whose expression has totals, numbers,
    and the stored number fields of the record. The records get known
    values of these fields, and the related records get known values of
    the fields of the totals and of their filters.
    """
    if not entity.totals:
        return None
    dsl_entity = definition.entities[entity.name]
    values: dict[str, str] = {}
    known: dict[str, Decimal] = {}
    candidates: list[PyComputed] = []
    for c in entity.computed:
        dsl = dsl_entity.fields[c.name]
        if not c.totals or not _testable(c, dsl):
            continue
        ok = True
        for path in c.paths:
            f = next(f for f in entity.fields if f.name == path)
            value = _known_value(dsl_entity.fields[path])
            if value is None:
                ok = False
                break
            known[path] = value
            values[f.attr] = str(int(value)) if f.type == "integer" else f'Decimal("{value}")'
        if ok:
            candidates.append(c)
    uses: dict[str, list[tuple[PyTotal, DslField]]] = {}
    for c in candidates:
        for t in c.totals.values():
            uses.setdefault(t.relation.name, []).append((t, dsl_entity.fields[c.name]))
    sets: dict[str, RelatedSet] = {}
    for relation_name, used in uses.items():
        found = _related_set(definition, used)
        if found is not None:
            sets[relation_name] = found
    checks: list[TotalsCheck] = []
    for c in candidates:
        if any(t.relation.name not in sets for t in c.totals.values()):
            continue
        dsl = dsl_entity.fields[c.name]
        results = [_expected(definition, c, dsl, known, sets, index) for index in range(3)]
        checks.append(TotalsCheck(c.name, c.id, results, c.sql is not None))
    if not checks:
        return None
    used_relations = {t.relation.name for c in candidates for t in c.totals.values()}
    ordered = [s for name, s in sets.items() if name in used_relations]
    read = next((o for o in entity.operations if o.kind == "read" and o.path == "/{id}"), None)
    listing = next((o for o in entity.operations if o.kind == "list" and o.path == ""), None)
    if read is None and listing is None:
        return None
    return TotalsTest(
        entity=entity,
        values=values,
        sets=ordered,
        checks=checks,
        read_path=entity.path + "/{record.id}" if read is not None else None,
        list_path=entity.path if listing is not None else None,
    )


def _testable(c: PyComputed, dsl: DslField) -> bool:
    """Return True if a test can know the values of a computed field."""
    if dsl.type == "decimal" and dsl.scale is None and "/" in c.source:
        return False
    return c.testable


def _known_value(f: DslField) -> Decimal | None:
    """Return a value of a number field for the tests: 1, else its minimum or maximum."""
    for candidate in (Decimal(1), _decimal(f.min), _decimal(f.max)):
        if candidate is not None and _in_range(f, candidate):
            scale = f.scale if f.type == "decimal" and f.scale is not None else 0
            return candidate.quantize(Decimal(1).scaleb(-scale)) if scale else candidate
    return None


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _in_range(f: DslField, value: Decimal) -> bool:
    return (f.min is None or value >= Decimal(str(f.min))) and (
        f.max is None or value <= Decimal(str(f.max))
    )


def _related_set(
    definition: AppDefinition, used: list[tuple[PyTotal, DslField]]
) -> RelatedSet | None:
    """Return the related records of one relation, or None if a test cannot know them.

    The records have known values of the fields of the totals, and values
    of the fields of the filters that pass and fail each filter.
    """
    relation, target = used[0][0].relation, used[0][0].target
    dsl_target = definition.entities[target.name]
    filters = FilterValues(definition, target, _TODAY)
    columns: dict[str, list[TestValue]] = {}
    for _, computed in used:
        for path, condition in (computed.filter or {}).items():
            f = filters.direct_field(path)
            if f is None or f.unique:
                return None
            conditions: dict[str, JsonValue] = (
                condition
                if isinstance(condition, dict)
                else {"in" if isinstance(condition, list) else "eq": condition}
            )
            planned = filters.values(f, conditions)
            if planned is None or not planned[0] or not planned[1]:
                return None
            # A passing value first, so that the record with one related record counts it.
            values = [planned[0][0], *planned[1][:1], *planned[0][1:2]]
            known = columns.setdefault(f.attr, [])
            known += [v for v in values if v.code not in {k.code for k in known}]
    count = max([3, *(len(v) for v in columns.values())])
    for total, _ in used:
        f = total.number
        if f is None or f.attr in columns:
            continue
        numbers = _numbers(dsl_target.fields[f.name], count)
        if numbers is None or f.unique:
            return None
        columns[f.attr] = [TestValue(_number_code(f, n), n) for n in numbers]
    records = [{a: v[i % len(v)].code for a, v in columns.items()} for i in range(count)]
    values = [{a: v[i % len(v)].value for a, v in columns.items()} for i in range(count)]
    return RelatedSet(relation, target, records, values)


def _numbers(f: DslField, count: int) -> list[Decimal] | None:
    """Return the values of a number field of the related records: they differ when they can."""
    scale = f.scale if f.type == "decimal" and f.scale is not None else 0
    low = Decimal(str(f.min)) if f.min is not None else Decimal(1)
    steps = [Decimal(12), Decimal(5), Decimal(30), Decimal(2), Decimal(7)]
    fraction = Decimal("0.25") if scale >= 2 else Decimal(0)
    found: list[Decimal] = []
    for index in range(count):
        value = low + steps[index % len(steps)] + fraction * (index % 3)
        if not _in_range(f, value):
            value = low + index
        if not _in_range(f, value):
            value = low
        if not _in_range(f, value):
            return None
        found.append(value.quantize(Decimal(1).scaleb(-scale)) if scale else value)
    return found


def _number_code(f: PyField, value: Decimal) -> str:
    return str(int(value)) if f.type == "integer" else f'Decimal("{value}")'


def _expected(
    definition: AppDefinition,
    c: PyComputed,
    dsl: DslField,
    known: dict[str, Decimal],
    sets: dict[str, RelatedSet],
    index: int,
) -> object:
    """Return the value of a computed field in the record of an index (0, 1, or 2).

    The record 0 has no related records, the record 1 the first one, and
    the record 2 all of them. The semantics are the ones of `app/core/compute.py`.
    """
    assert c.expression is not None

    def total(t: Total) -> Decimal | None:
        py_total = c.totals[str(t)]
        found = sets[t.relation]
        rows = found.values[: (0, 1, len(found.values))[index]]
        for path, condition in (dsl.filter or {}).items():
            f = resolve_path(py_total.target, path).field
            assert f is not None
            conditions: dict[str, JsonValue] = (
                condition
                if isinstance(condition, dict)
                else {"in" if isinstance(condition, list) else "eq": condition}
            )
            filters = FilterValues(definition, py_total.target, _TODAY)
            rows = [
                r
                for r in rows
                if all(
                    passes(r[f.attr], op, filters.operand(f, operand))
                    for op, operand in conditions.items()
                )
            ]
        if t.function == "count":
            return Decimal(len(rows))
        assert py_total.number is not None
        numbers = [Decimal(str(r[py_total.number.attr])) for r in rows]
        if not numbers:
            return Decimal(0) if t.function == "sum" else None
        match t.function:
            case "sum":
                return sum(numbers, Decimal(0))
            case "avg":
                return sum(numbers, Decimal(0)) / len(numbers)
            case "min":
                return min(numbers)
            case _:
                return max(numbers)

    def value(expression: Expression) -> Decimal | None:
        match expression:
            case Number(text):
                return Decimal(text)
            case FieldRef(path):
                return known[path]
            case Total():
                return total(expression)
            case Binary(op, left, right):
                a, b = value(left), value(right)
                if a is None or b is None:
                    return None
                match op:
                    case "+":
                        return a + b
                    case "-":
                        return a - b
                    case "*":
                        return a * b
                    case _:
                        return None if b == 0 else a / b
            case Negate(operand):
                inner = value(operand)
                return None if inner is None else -inner
            case FunctionCall():
                raise AssertionError("A testable computed field has no time function.")

    result = value(c.expression)
    if result is None:
        return None
    if dsl.type == "integer":
        return int(result.to_integral_value())
    if dsl.scale is not None:
        return result.quantize(Decimal(1).scaleb(-dsl.scale))
    return result


def _json(value: object) -> str:
    """Return a value of a computed field in a JSON response, as Python code."""
    if value is None:
        return "None"
    if isinstance(value, Decimal):
        return f'"{value}"'
    return str(value)


def _python(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, Decimal):
        return f'Decimal("{value}")'
    return str(value)
