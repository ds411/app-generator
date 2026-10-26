"""The test values of the compare rules with totals of the lines (ADR 0034).

The repository checks a compare rule with a total, for example
`sum(lines.debit)` equal to `sum(lines.credit)`, after each create and
update of the record, with the lines in the database. The generated tests
write records with no lines and with up to three lines with the test
samples, so the samples of the fields of these rules become fixed values
that keep the rules: the search tries small numbers, and the minimum and
the maximum of each field.

The tests of an operation with lines also send two lines that keep the
rules, and two lines that break each rule. The search finds them in the
same way. A rule whose values the tests cannot know, for example with a
unique field, gets no such tests.
"""

import itertools
import json
import operator
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import TYPE_CHECKING

from appgen.dsl.expressions import Total, parse_expression
from appgen.dsl.model import AppDefinition, Entity, Field
from appgen.dsl.rules import EntityCompareRule, is_total_operand

if TYPE_CHECKING:
    from appgen.bindings.fastapi.lines import PyLines
    from appgen.bindings.fastapi.model import PyEntity, PyField, PyRule

_OPS: dict[str, Callable[[Decimal, Decimal], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}

_NUMBERS = (1, 0, 2, 5, 10, 100, 1000)
"""The numbers that the search tries first, in this order."""

_MAX_FIELDS = 5
"""The search of the samples gives up above this count of fields: the tests keep the samples."""

_MAX_COLUMNS = 3
"""The search of the lines of a test gives up above this count of fields of the lines."""

_COLUMN_VALUES = 5
"""The count of values of each field of the lines that the search of the lines tries."""

type Lines = dict[str, list[dict[str, Decimal]]]
"""The lines of a record by relation: the values of the fields of the totals."""


@dataclass(slots=True)
class RuleCase:
    """The tests of a compare rule with totals in an operation with lines."""

    rule: PyRule
    kept: list[dict[str, str]]
    """Two lines that keep all rules with totals: the Python code of each value, by field."""
    broken: list[dict[str, str]] | None
    """Two lines that break the rule, and keep the rules that the repository checks before it,
    or None if the search finds none."""

    def item_args(self, values: dict[str, str]) -> str:
        """Return the keyword arguments of the item helper of the test for one line."""
        return "".join(f", {name}={code}" for name, code in values.items())


def _rules(entity: Entity) -> list[EntityCompareRule]:
    return [r for r in entity.rules.values() if isinstance(r, EntityCompareRule) and r.totals]


@cache
def _total(side: str) -> Total:
    total = parse_expression(side)
    assert isinstance(total, Total)
    return total


def _value(side: str, record: dict[str, Decimal | None], lines: Lines) -> Decimal | None:
    """Return the value of a side of a rule: a field of the record, or a total of its lines.

    The count and the sum of no lines are 0, and the other totals are None.
    """
    if not is_total_operand(side):
        return record.get(side)
    total = _total(side)
    rows = lines.get(total.relation, [])
    if total.field is None:
        return Decimal(len(rows))
    numbers = [row[total.field] for row in rows]
    if not numbers:
        return Decimal(0) if total.function == "sum" else None
    match total.function:
        case "sum":
            return sum(numbers, Decimal(0))
        case "avg":
            return sum(numbers, Decimal(0)) / len(numbers)
        case "min":
            return min(numbers)
        case _:
            return max(numbers)


def _holds(rule: EntityCompareRule, record: dict[str, Decimal | None], lines: Lines) -> bool:
    """Return True if a record keeps a rule. An empty value passes, as in `app/core/rules.py`."""
    a, b = _value(rule.field, record, lines), _value(rule.other, record, lines)
    return a is None or b is None or _OPS[rule.op](a, b)


def _candidates(field: Field) -> list[Decimal]:
    """Return the values that a number field permits, of the numbers of the search."""
    values = [Decimal(n) for n in _NUMBERS]
    values += [Decimal(str(v)) for v in (field.min, field.max) if v is not None]
    scale = (field.scale or 0) if field.type == "decimal" else 0
    digits = field.precision - scale if field.type == "decimal" and field.precision else None
    found: list[Decimal] = []
    for value in values:
        exponent = value.as_tuple().exponent
        if (
            (field.min is not None and value < Decimal(str(field.min)))
            or (field.max is not None and value > Decimal(str(field.max)))
            or (isinstance(exponent, int) and exponent < -scale)
            or (digits is not None and abs(value) >= Decimal(10) ** digits)
        ):
            continue
        if value not in found:
            found.append(value)
    return found


def _known(py_field: PyField) -> Decimal | None:
    """Return the value of a fixed test sample of a number field, or None if it varies."""
    try:
        value = json.loads(py_field.sample)
    except ValueError:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _code(field: Field, value: Decimal) -> str:
    """Return a value of a number field as the Python code of its JSON value."""
    if field.type == "integer":
        return str(int(value))
    return json.dumps(str(value))


def _py_field(entities: dict[str, PyEntity], entity: str, name: str) -> PyField:
    return next(f for f in entities[entity].fields if f.name == name)


def fix_rule_samples(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Give the fields of the compare rules with totals fixed test samples that keep the rules.

    A record of the tests has no lines, or one to three lines of one
    relation, with the samples. A unique field and a field with a fixed
    sample, for example from an earlier entity or an example, keep their
    samples.
    """
    for name, entity in definition.entities.items():
        rules = _rules(entity)
        keys: list[tuple[str, str]] = []
        relations: list[str] = []
        for rule in rules:
            for side in (rule.field, rule.other):
                if not is_total_operand(side):
                    keys.append((name, side))
                    continue
                total = _total(side)
                relations.append(total.relation)
                if total.field is not None:
                    keys.append((entity.relations[total.relation].target, total.field))
        keys = list(dict.fromkeys(keys))
        if not rules or len(keys) > _MAX_FIELDS:
            continue
        options: list[list[Decimal]] = []
        for entity_name, field_name in keys:
            field = definition.entities[entity_name].fields[field_name]
            known = _known(_py_field(entities, entity_name, field_name))
            if known is not None:
                options.append([known])
            else:
                options.append([] if field.unique else _candidates(field))
        targets = {r: entity.relations[r].target for r in relations}
        scenarios = [(r, count) for r in targets for count in range(4)]
        for combo in itertools.product(*options):
            values = dict(zip(keys, combo, strict=True))
            record: dict[str, Decimal | None] = {f: v for (e, f), v in values.items() if e == name}
            rows = {r: {f: v for (e, f), v in values.items() if e == t} for r, t in targets.items()}
            if all(
                _holds(rule, record, {r: [rows[r]] * count})
                for rule in rules
                for r, count in scenarios
            ):
                for (entity_name, field_name), value in values.items():
                    field = definition.entities[entity_name].fields[field_name]
                    _py_field(entities, entity_name, field_name).sample = _code(field, value)
                break


def rule_cases(definition: AppDefinition, entity: PyEntity, lines: PyLines) -> list[RuleCase]:
    """Return the tests of the compare rules with totals of the lines of a relation.

    The record has the test samples, and two lines of the relation. The
    search needs the fixed samples of the fields of the record in the rules.
    """
    rules = _rules(definition.entities[entity.name])
    record: dict[str, Decimal | None] = {}
    columns: list[str] = []
    for rule in rules:
        for side in (rule.field, rule.other):
            if not is_total_operand(side):
                known = _known(next(f for f in entity.fields if f.name == side))
                if known is None:
                    return []
                record[side] = known
            elif (total := _total(side)).relation == lines.name and total.field is not None:
                columns.append(total.field)
    columns = list(dict.fromkeys(columns))
    target = definition.entities[lines.target.name]
    options = [_candidates(target.fields[c])[:_COLUMN_VALUES] for c in columns]
    if not rules or len(columns) > _MAX_COLUMNS or not all(options):
        return []
    width = len(columns)
    plans = [
        [
            dict(zip(columns, combo[:width], strict=True)),
            dict(zip(columns, combo[width:], strict=True)),
        ]
        for combo in itertools.product(*options, *options)
    ]

    def holds(rule: EntityCompareRule, plan: list[dict[str, Decimal]]) -> bool:
        return _holds(rule, record, {lines.name: plan})

    def code(plan: list[dict[str, Decimal]]) -> list[dict[str, str]]:
        return [{c: _code(target.fields[c], row[c]) for c in columns} for row in plan]

    # The best plan needs both lines: the first line alone breaks a rule.
    # Else two lines that differ, else any plan.
    kept_plans = [p for p in plans if all(holds(r, p) for r in rules)]
    ranked = sorted(
        kept_plans,
        key=lambda p: (all(holds(r, p[:1]) for r in rules), p[0] == p[1]),
    )
    if not ranked:
        return []
    py_rules = {r.id: r for r in entity.total_rules}
    cases: list[RuleCase] = []
    for index, rule in enumerate(rules):
        if not any(
            is_total_operand(side) and _total(side).relation == lines.name
            for side in (rule.field, rule.other)
        ):
            continue
        broken = next(
            (p for p in plans if not holds(rule, p) and all(holds(r, p) for r in rules[:index])),
            None,
        )
        cases.append(RuleCase(py_rules[rule.id], code(ranked[0]), code(broken) if broken else None))
    return cases


def total_rule_cases(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Give the lines of each entity the tests of the compare rules with totals."""
    for entity in entities.values():
        for lines in entity.lines:
            lines.rule_cases = rule_cases(definition, entity, lines)
