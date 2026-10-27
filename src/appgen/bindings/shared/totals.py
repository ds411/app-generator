"""The totals of the relations in the computed fields, for the front ends (ADR 0034).

A record of the Next.js app and of the React app with mock data has a key
for each distinct total of its computed fields, for example
`sumLinesAmount`: the Next.js repository reads it in a subquery, and the
mock store adds the related mock records. The views compute the field from
the key, as from the other values of the record. The React app with the
FastAPI app reads the value of each computed field with totals from the API
instead. The names of the totals are the names of the column properties of
the FastAPI app.

A compare rule can compare a total of the lines of a record, for example
`sum(lines.debit)`: the Next.js repository reads the totals of the rules
after a change, and checks the rules.
"""

from dataclasses import dataclass, field

from pydantic import JsonValue

from appgen.dsl.auth import ME, has_me
from appgen.dsl.expressions import Total, expression_totals, parse_expression
from appgen.dsl.model import AppDefinition, Field
from appgen.dsl.rules import EntityCompareRule, is_total_operand
from appgen.dsl.ui.dashboards import RecordFilter
from appgen.gen.naming import camel
from appgen.gen.render import GenerationError


def total_name(field_name: str, computed: Field, total: Total) -> str:
    """Return the name of a total in snake case, for example `sum_lines_amount`.

    The name of a total with the filter of its field starts with the name
    of the field, because the filter is part of the total.
    """
    parts = [total.function, total.relation, *([total.field] if total.field else [])]
    return "_".join([field_name, *parts] if computed.filter else parts)


def total_key(field_name: str, computed: Field, total: Total) -> str:
    """Return the key of a total in the records, for example `sumLinesAmount`."""
    return camel(total_name(field_name, computed, total))


@dataclass(slots=True)
class TsTotal:
    """A total of the records of a relation: a key of the records of the entity."""

    key: str
    """The key in the records, for example `sumLinesAmount`."""
    function: str
    """`count`, `sum`, `avg`, `min`, or `max`."""
    relation: str
    """The `one_to_many` or `many_to_many` relation."""
    many_to_many: bool
    target: str
    """The entity of the related records."""
    inverse: str | None
    """The `many_to_one` relation of the related records to the record, for `one_to_many`."""
    number: str | None
    """The number field of the related records. None for `count`."""
    filter: RecordFilter | None
    """The filter of the related records: the filter of the computed field."""
    ids: list[str] = field(default_factory=list[str])
    """The computed fields that use the total, for the traces."""
    relations: frozenset[str] = frozenset()
    """The relations of the related records in the filter: a filter of `$me` (ADR 0034)."""

    @property
    def me(self) -> bool:
        """True if the filter has `$me`: the total counts the records of the signed-in user."""
        return has_me(self.filter)

    def conditions(self) -> list[tuple[str, str, JsonValue]]:
        """Return the conditions of the filter: the key of a member, an operator, and a value.

        A value gives `eq`, and a list of values gives `in`. The key of a
        relation is its foreign key, for example `studentId`. A list of
        only `$me` is the one value `$me`.
        """
        found: list[tuple[str, str, JsonValue]] = []
        for path, condition in (self.filter or {}).items():
            key = camel(path) + "Id" if path in self.relations else camel(path)
            items = condition.items() if isinstance(condition, dict) else [("eq", condition)]
            for op, operand in items:
                if isinstance(operand, list) and operand and all(v == ME for v in operand):
                    op, operand = {"eq": "eq", "in": "eq", "ne": "ne"}.get(op, "ne"), ME
                elif op == "eq" and isinstance(operand, list):
                    op = "in"
                found.append((key, op, operand))
        return found


def entity_totals(definition: AppDefinition, entity_name: str) -> list[TsTotal]:
    """Return the distinct totals of the computed fields of an entity, in source order.

    Raise GenerationError if the name of a total is the name of a member of
    the entity, as the FastAPI binding does.
    """
    entity = definition.entities[entity_name]
    found: dict[str, TsTotal] = {}
    for name, spec in entity.fields.items():
        if spec.computed is None:
            continue
        for total in expression_totals(parse_expression(spec.computed)):
            snake = total_name(name, spec, total)
            if snake in entity.fields or snake in entity.relations:
                raise GenerationError(
                    f"The total '{total}' of the computed field '{entity_name}.{name}' needs "
                    f"the key '{camel(snake)}' in the records, but the entity has a member "
                    f"'{snake}'. Rename the member."
                )
            key = camel(snake)
            if key not in found:
                relation = entity.relations[total.relation]
                found[key] = TsTotal(
                    key=key,
                    function=total.function,
                    relation=total.relation,
                    many_to_many=relation.kind == "many_to_many",
                    target=relation.target,
                    inverse=relation.inverse,
                    number=total.field,
                    filter=spec.filter,
                    relations=frozenset(
                        p
                        for p in spec.filter or {}
                        if p in definition.entities[relation.target].relations
                    ),
                )
            if spec.id not in found[key].ids:
                found[key].ids.append(spec.id)
    return list(found.values())


def rule_totals(definition: AppDefinition, entity_name: str) -> list[TsTotal]:
    """Return the distinct totals of the compare rules of an entity, in source order.

    A total of a rule has no filter, so its key is the key of the same
    total of a computed field without a filter, for example
    `sumLinesDebit`. Raise GenerationError if the name of a total is the
    name of a member of the entity.
    """
    entity = definition.entities[entity_name]
    found: dict[str, TsTotal] = {}
    for rule in entity.rules.values():
        if not isinstance(rule, EntityCompareRule):
            continue
        for side in rule.totals:
            key = rule_side_key(side)
            assert key is not None
            total = parse_expression(side)
            assert isinstance(total, Total)
            snake = "_".join(
                [total.function, total.relation, *([total.field] if total.field else [])]
            )
            if snake in entity.fields or snake in entity.relations:
                raise GenerationError(
                    f"The total '{total}' of the rule '{rule.id}' needs the key '{key}' in the "
                    f"records, but the entity has a member '{snake}'. Rename the member."
                )
            if key not in found:
                relation = entity.relations[total.relation]
                found[key] = TsTotal(
                    key=key,
                    function=total.function,
                    relation=total.relation,
                    many_to_many=False,
                    target=relation.target,
                    inverse=relation.inverse,
                    number=total.field,
                    filter=None,
                )
            if rule.id not in found[key].ids:
                found[key].ids.append(rule.id)
    return list(found.values())


def rule_side_key(side: str) -> str | None:
    """Return the key of the total of a side of a compare rule, or None for a field."""
    if not is_total_operand(side):
        return None
    total = parse_expression(side)
    assert isinstance(total, Total)
    parts = [total.function, total.relation, *([total.field] if total.field else [])]
    return camel("_".join(parts))


def has_totals(definition: AppDefinition, entity_name: str, field_name: str) -> bool:
    """Return True if a field is a computed field with totals."""
    spec = definition.entities[entity_name].fields[field_name]
    return spec.computed is not None and any(
        True for _ in expression_totals(parse_expression(spec.computed))
    )


@dataclass(frozen=True, slots=True)
class TotalKey:
    """A key of the records with a total, or with the value of a computed field with totals."""

    key: str
    ids: tuple[str, ...]
    """The computed fields of the key, for the traces."""


def total_keys(definition: AppDefinition, entity_name: str, *, api: bool) -> list[TotalKey]:
    """Return the keys of the totals in the records of an entity, in source order.

    With `api` (the React app with the FastAPI app), the key of each
    computed field with totals: the API sends its value. Else the key of
    each distinct total.
    """
    if api:
        entity = definition.entities[entity_name]
        return [
            TotalKey(camel(name), (spec.id,))
            for name, spec in entity.computed_fields.items()
            if has_totals(definition, entity_name, name)
        ]
    return [TotalKey(t.key, tuple(t.ids)) for t in entity_totals(definition, entity_name)]
