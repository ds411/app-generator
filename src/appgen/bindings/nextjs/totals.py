"""The totals of the relations in the computed fields of the Next.js app (ADR 0034).

The repository of an entity with totals reads the totals of its records
with one more query, with a correlated subquery for each total (`total`
in `src/shared/db/repository.ts`): the lists, the reads, and the results
of the changes. The query names the table of the records `record`, so
that the subquery of a relation of the entity to itself tells the record
from its related records. The views compute the fields from the totals.
"""

import re
from dataclasses import dataclass, field

from appgen.bindings.nextjs.db import Table, TsCall, TsCode, format_ts
from appgen.bindings.nextjs.jobs import FilterBuilder, TsFilter
from appgen.bindings.shared.totals import TsTotal, entity_totals
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel

_OPERATORS = (
    *("and", "eq", "gt", "gte", "inArray", "isNotNull", "isNull"),
    *("lt", "lte", "ne", "notInArray", "or"),
)
"""The functions of `drizzle-orm` that the subquery of a total can call."""


@dataclass(slots=True)
class TsTotalQuery:
    """The subquery of a total: a key of the `totals` option of the repository."""

    key: str
    code: str
    """The entry of the key, for example `sumLinesAmount: total("sum", ...),`."""
    ids: list[str]
    """The computed fields that use the total, for the traces."""


@dataclass(slots=True)
class RepositoryTotals:
    """The totals of an entity in its repository, with what their code imports."""

    totals: list[TsTotalQuery] = field(default_factory=list[TsTotalQuery])
    operators: list[str] = field(default_factory=list[str])
    """The functions of `drizzle-orm`."""
    tables: list[str] = field(default_factory=list[str])
    """The tables of `@/shared/db`."""


def repository_totals(
    definition: AppDefinition, tables: dict[str, Table]
) -> dict[str, RepositoryTotals]:
    """Return the totals of each entity with totals, by entity name."""
    found: dict[str, RepositoryTotals] = {}
    for name in definition.entities:
        totals = entity_totals(definition, name)
        if not totals:
            continue
        result = RepositoryTotals()
        used: set[str] = set()
        for total in totals:
            filter_ = TsFilter()
            code = _code(definition, tables, name, total, filter_)
            entry = format_ts(code, 4, f"{total.key}: ", ",")
            result.totals.append(TsTotalQuery(total.key, entry, total.ids))
            used |= filter_.tables
            used.add(tables[total.target].const)
        text = "\n".join(t.code for t in result.totals)
        result.operators = [n for n in _OPERATORS if re.search(rf"\b{n}\(", text)]
        result.tables = sorted(used)
        found[name] = result
    return found


def _code(
    definition: AppDefinition,
    tables: dict[str, Table],
    entity: str,
    total: TsTotal,
    filter_: TsFilter,
) -> TsCode:
    """Return the call of `total` for a total: the function, the tables, the value, and the
    conditions."""
    builder = FilterBuilder(definition, tables, total.ids[0], filter_)
    target = tables[total.target].const
    value = f"{target}.{camel(total.number)}" if total.number is not None else "null"
    conditions: list[TsCode]
    if total.many_to_many:
        relation = definition.entities[entity].relations[total.relation]
        join = next(item for item in tables[entity].lists if item.element_id == relation.id)
        filter_.tables.add(join.join_const)
        source = f"[{target}, {join.join_const}]"
        conditions = [
            TsCall("eq", [f"{join.join_const}.{join.owner_key}", "record.id"]),
            TsCall("eq", [f"{join.join_const}.{join.target_key}", f"{target}.id"]),
        ]
    else:
        assert total.inverse is not None
        column = builder.column_of_relation(total.target, total.inverse)
        assert column is not None
        source = target
        conditions = [TsCall("eq", [f"{target}.{column}", "record.id"])]
    for path, condition in (total.filter or {}).items():
        conditions.append(builder.filter(total.target, path, condition))
    return TsCall("total", [f'"{total.function}"', source, value, *conditions])
