"""The ranges of the related records of the available filters in the Next.js app (ADR 0047).

The repository of an entity with available filters has a query for each
relation and rule (`<entity>RangeQueries`): the ID of the record, the
start, and the end of each related record. The server action
`list<Entity>RangesAction` runs one with the access of the list of the
entity, and the views keep the records without a range in the picked days.
The queries read all related records: a record rule of the related entity
does not hide a booking from the filter.
"""

from dataclasses import dataclass, field

from appgen.bindings.nextjs.db import Table, record_key
from appgen.bindings.shared.available import AvailableRule, available_rules
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel


@dataclass(slots=True)
class TsRangeQuery:
    """The query of the ranges of one relation and rule: an entry of `<entity>RangeQueries`."""

    rule: AvailableRule
    lines: list[str]
    """The statements of the query, without an indent."""


@dataclass(slots=True)
class RepositoryRanges:
    """The range queries of an entity in its repository, with what their code imports."""

    queries: list[TsRangeQuery] = field(default_factory=list[TsRangeQuery])
    tables: list[str] = field(default_factory=list[str])
    """The tables of `@/shared/db`."""
    operators: list[str] = field(default_factory=list[str])
    """The functions of `drizzle-orm`."""

    @property
    def keys(self) -> str:
        """The TypeScript type of the keys, for example `"bookings.no_double_booking"`."""
        return " | ".join(f'"{q.rule.key}"' for q in self.queries)


def repository_ranges(
    definition: AppDefinition, tables: dict[str, Table]
) -> dict[str, RepositoryRanges]:
    """Return the range queries of each entity with available filters, by entity name."""
    found: dict[str, RepositoryRanges] = {}
    for entity, rules in available_rules(definition).items():
        result = RepositoryRanges()
        used: set[str] = set()
        for rule in rules:
            target = tables[rule.target].const
            used.add(target)
            spec = definition.entities[rule.target]
            ends = [
                _value(rule, key, spec.fields[name].required)
                for key, name in (("start", rule.start), ("end", rule.end))
            ]
            if rule.many_to_many:
                relation = definition.entities[entity].relations[rule.relation]
                join = next(i for i in tables[entity].lists if i.element_id == relation.id)
                used.add(join.join_const)
                owner, required = f"{join.join_const}.{join.owner_key}", True
                source = [
                    f".from({join.join_const})",
                    f".innerJoin({target}, eq({join.join_const}.{join.target_key}, {target}.id));",
                ]
                result.operators.append("eq")
            else:
                assert rule.inverse is not None
                owner = f"{target}.{record_key(spec, rule.inverse)}"
                required = spec.relations[rule.inverse].required
                source = [f".from({target});"]
            columns = (
                f"id: {owner}, start: {target}.{camel(rule.start)}, end: {target}.{camel(rule.end)}"
            )
            lines = ["const rows = await getDb()", f"  .select({{ {columns} }})"]
            lines += [f"  {line}" for line in source]
            entry = f"[row.id, {ends[0]}, {ends[1]}]"
            if required:
                lines.append(f"return rows.map((row): OwnerRange => {entry});")
            else:
                # A related record without a record has no owner.
                kept = f"(row.id === null ? [] : [{entry}])"
                lines.append(f"return rows.flatMap((row): OwnerRange[] => {kept});")
            result.queries.append(TsRangeQuery(rule, lines))
        result.tables = sorted(used)
        result.operators = sorted(set(result.operators))
        found[entity] = result
    return found


def _value(rule: AvailableRule, key: str, required: bool) -> str:
    """Return the text of the start or the end of a row: a date is a text, a date-time a `Date`."""
    if rule.dates:
        return f"row.{key}"
    return f"row.{key}.toISOString()" if required else f"row.{key}?.toISOString() ?? null"
