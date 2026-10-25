"""The Drizzle schema of the Next.js app: tables, columns, and relations.

Each entity is a Postgres table with a UUID primary key `id`. Each field
is a column, and each `many_to_one` or `one_to_one` relation is a foreign
key column `<relation>_id`. A `many_to_many` relation gets a join table.
A translatable field also has the `jsonb` column `<field>_translations`
with its values in the other languages (ADR 0026), as in the FastAPI app.
The templates of `src/shared/db/schema/` render these values. The seed
of `src/shared/db/seed.ts` fills the tables with the shared mock records.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from appgen.bindings.shared.auth import PathStep
from appgen.bindings.shared.mock_data import mock_data, seed_records
from appgen.bindings.shared.typescript import translations_key
from appgen.dsl.model import AppDefinition, Entity, Field, Relation
from appgen.dsl.rules import EntityUniqueRule
from appgen.gen.naming import camel, snake
from appgen.gen.render import GenerationError

_ON_DELETE = {"restrict": "restrict", "cascade": "cascade", "set_null": "set null"}


@dataclass(frozen=True, slots=True)
class Column:
    """A column of a table, as Drizzle code."""

    key: str
    """The TypeScript key, for example `dueDate`."""
    builder: str
    """The Drizzle column builder, for example `date("due_date", { mode: "string" }).notNull()`."""
    element_id: str
    imports: tuple[str, ...]
    """The builders that the column imports from `drizzle-orm/pg-core`."""


@dataclass(frozen=True, slots=True)
class UniqueRule:
    """A unique rule of an entity: a unique constraint of its table."""

    element_id: str
    name: str
    """The name of the constraint, for example `uq_room_floor_name`."""
    keys: tuple[str, ...]
    """The TypeScript keys of the columns."""

    @property
    def columns(self) -> str:
        """The columns of the constraint, of the table callback `t`, for example `t.a, t.b`."""
        return ", ".join(f"t.{key}" for key in self.keys)


@dataclass(frozen=True, slots=True)
class Enum:
    """A Postgres enum type of an `enum` field."""

    const: str
    """The TypeScript name, for example `projectStatusEnum`."""
    name: str
    """The Postgres name, for example `project_status`."""
    values: tuple[str, ...]
    element_id: str


@dataclass(frozen=True, slots=True)
class RelationRef:
    """A relation for the Drizzle relational queries (`relations()`)."""

    key: str
    """The TypeScript key, for example `project`."""
    kind: str
    """`one` or `many`."""
    target_table: str
    """The table const of the target, for example `projectTable`, or of a join table."""
    target_module: str
    """The schema module of the target, for example `project`."""
    fields: str | None
    """For `one` with the foreign key on this table: the column key, for example `projectId`."""
    relation_name: str
    element_id: str


@dataclass(slots=True)
class JoinTable:
    """The join table of a `many_to_many` relation."""

    const: str
    name: str
    left_key: str
    """The column key of this entity, for example `projectId`."""
    left_column: str
    right_key: str
    """The column key of the target entity, for example `personId`."""
    right_column: str
    target_table: str
    target_module: str
    relation_name: str
    element_id: str
    inverse_relation_name: str | None = None
    """The `relationName` of the inverse relation on the target, if it has one."""

    @property
    def left_relation(self) -> str:
        """The key of the relation to this entity, for example `project`."""
        return self.left_key.removesuffix("Id")

    @property
    def right_relation(self) -> str:
        """The key of the relation to the target entity, for example `person`."""
        return self.right_key.removesuffix("Id")


@dataclass(frozen=True, slots=True)
class ListRef:
    """A `many_to_many` relation as a list of IDs in a record, for the data access."""

    key: str
    """The key of the list in the record, for example `members`."""
    join_const: str
    join_module: str
    owner_key: str
    """The key of the join table column with the ID of the record."""
    target_key: str
    """The key of the join table column with the ID of the target."""
    element_id: str


@dataclass(frozen=True, slots=True)
class InverseOne:
    """A `one_to_one` relation whose foreign key is on the target table."""

    key: str
    """The key of the ID in the record, for example `ownerId`."""
    target_table: str
    foreign_key: str
    """The key of the foreign key column of the target, for example `profileId`."""
    element_id: str


@dataclass(slots=True)
class Table:
    """The Drizzle table of an entity."""

    entity: str
    element_id: str
    module: str
    """The schema module, for example `project` for `src/shared/db/schema/project.ts`."""
    const: str
    """The TypeScript name, for example `projectTable`."""
    name: str
    """The Postgres name, for example `project`."""
    columns: list[Column] = field(default_factory=list[Column])
    enums: list[Enum] = field(default_factory=list[Enum])
    relations: list[RelationRef] = field(default_factory=list[RelationRef])
    join_tables: list[JoinTable] = field(default_factory=list[JoinTable])
    lists: list[ListRef] = field(default_factory=list[ListRef])
    """The `many_to_many` relations of the record, for the data access."""
    inverse_ones: list[InverseOne] = field(default_factory=list[InverseOne])
    """The `one_to_one` relations whose foreign key is on the target, for the data access."""
    unique_rules: list[UniqueRule] = field(default_factory=list[UniqueRule])
    """The unique rules of the entity: unique constraints over more than one column."""

    @property
    def pg_imports(self) -> list[str]:
        """The builders to import from `drizzle-orm/pg-core`, sorted."""
        names = {"pgTable", "uuid"}
        names.update(i for c in self.columns for i in c.imports)
        if self.enums:
            names.add("pgEnum")
        if self.join_tables:
            names.add("primaryKey")
        if self.unique_rules:
            names.add("unique")
        return sorted(names, key=lambda name: name.removeprefix("type "))

    @property
    def relation_helpers(self) -> str:
        """The helpers of the `relations()` callback of the table, for example `one, many`."""
        kinds = {r.kind for r in self.relations}
        return ", ".join(k for k in ("one", "many") if k in kinds)

    @property
    def related_modules(self) -> list[tuple[str, str]]:
        """The tables of other modules that this module imports: (module, const), sorted."""
        found = {(r.target_module, r.target_table) for r in self.relations}
        found.update((j.target_module, j.target_table) for j in self.join_tables)
        return sorted(m for m in found if m[0] != self.module)


def table_const(entity: str) -> str:
    return f"{camel(entity)}Table"


def module_name(entity: str) -> str:
    return snake(entity).replace("_", "-")


def column_builder(name: str, spec: Field) -> tuple[str, tuple[str, ...], str | None]:
    """Return the Drizzle builder of a field, its imports, and the enum const if any."""
    column = snake(name)
    enum_const: str | None = None
    match spec.type:
        case "string" | "email" | "url":
            if spec.max_length:
                code, imports = (
                    f'varchar("{column}", {{ length: {spec.max_length} }})',
                    ("varchar",),
                )
            else:
                code, imports = f'text("{column}")', ("text",)
        case "text":
            code, imports = f'text("{column}")', ("text",)
        case "integer":
            code, imports = f'integer("{column}")', ("integer",)
        case "decimal":
            options = [
                f"{key}: {value}"
                for key, value in (("precision", spec.precision), ("scale", spec.scale))
                if value is not None
            ]
            options.append('mode: "number"')
            code, imports = f'numeric("{column}", {{ {", ".join(options)} }})', ("numeric",)
        case "boolean":
            code, imports = f'boolean("{column}")', ("boolean",)
        case "date":
            code, imports = f'date("{column}", {{ mode: "string" }})', ("date",)
        case "datetime":
            code = f'timestamp("{column}", {{ withTimezone: true, mode: "date" }})'
            imports = ("timestamp",)
        case "uuid":
            code, imports = f'uuid("{column}")', ("uuid",)
        case "enum":
            enum_const = "<enum>"
            code, imports = f'<enum>("{column}")', ()
        case "json":
            code, imports = f'jsonb("{column}")', ("jsonb",)
    if spec.required:
        code += ".notNull()"
    if spec.unique:
        code += ".unique()"
    if spec.default is not None:
        value = json.dumps(spec.default)
        code += f".default(new Date({value}))" if spec.type == "datetime" else f".default({value})"
    return code, imports, enum_const


def build_tables(definition: AppDefinition) -> list[Table]:
    """Return the Drizzle tables of a definition, in the order of the entities."""
    tables: list[Table] = []
    for entity_name, entity in definition.entities.items():
        table = Table(
            entity=entity_name,
            element_id=entity.id,
            module=module_name(entity_name),
            const=table_const(entity_name),
            name=snake(entity_name),
        )
        for field_name, spec in entity.stored_fields.items():
            code, imports, enum_const = column_builder(field_name, spec)
            if enum_const is not None:
                const = f"{camel(entity_name)}{field_name[0].upper()}{camel(field_name)[1:]}Enum"
                table.enums.append(
                    Enum(
                        const,
                        f"{table.name}_{snake(field_name)}",
                        tuple(spec.values or ()),
                        spec.id,
                    )
                )
                code = code.replace("<enum>", const)
            table.columns.append(Column(camel(field_name), code, spec.id, imports))
            if spec.translatable:
                code = f'jsonb("{snake(field_name)}_translations").$type<Record<string, string>>()'
                table.columns.append(
                    Column(translations_key(field_name), code, spec.id, ("jsonb",))
                )
        for relation_name, relation in entity.relations.items():
            _add_relation(definition, table, entity_name, relation_name, relation)
        for rule_name, rule in entity.rules.items():
            if isinstance(rule, EntityUniqueRule):
                keys = tuple(rule_key(table, entity, m) for m in rule.fields)
                table.unique_rules.append(UniqueRule(rule.id, f"uq_{table.name}_{rule_name}", keys))
        tables.append(table)
    return tables


def record_key(entity: Entity, member: str) -> str:
    """Return the key of a field or a single relation of a rule in a record: `dueDate`, `roomId`."""
    return camel(member) if member in entity.fields else f"{camel(member)}Id"


def record_keys(entity: Entity, members: list[str]) -> list[str]:
    """Return the keys of the fields and the single relations of a rule in a record."""
    return [record_key(entity, m) for m in members]


def rule_key(table: Table, entity: Entity, member: str) -> str:
    """Return the TypeScript key of the column of a field or a relation of a rule."""
    key = record_key(entity, member)
    if key not in {c.key for c in table.columns}:
        raise GenerationError(
            f"The rule of '{table.entity}' uses '{member}', which has no column in its table."
        )
    return key


def _inverse(definition: AppDefinition, relation: Relation) -> tuple[str, Relation] | None:
    """Return the inverse relation of a relation, if it has one of the same kind."""
    if relation.inverse is None:
        return None
    inverse = definition.entities[relation.target].relations.get(relation.inverse)
    if inverse is None or inverse.kind != relation.kind:
        return None
    return relation.inverse, inverse


def _stores(definition: AppDefinition, entity_name: str, name: str, relation: Relation) -> bool:
    """Return True if this side of a `one_to_one` or `many_to_many` relation stores it.

    A relation and its inverse are stored once: as the foreign key of the
    required side of a `one_to_one` relation, else on the side that comes
    first in the definition.
    """
    found = _inverse(definition, relation)
    if found is None:
        return True
    inverse_name, inverse = found
    if relation.kind == "one_to_one" and relation.required != inverse.required:
        return relation.required
    entities = list(definition.entities)

    def position(entity: str, relation_name: str) -> tuple[int, int]:
        return entities.index(entity), list(definition.entities[entity].relations).index(
            relation_name
        )

    return position(entity_name, name) <= position(relation.target, inverse_name)


def _join_table(entity_name: str, name: str, relation: Relation) -> JoinTable:
    """Return the join table of a `many_to_many` relation, on the side that stores it."""
    target = relation.target
    return JoinTable(
        const=f"{camel(entity_name)}{name[0].upper()}{camel(name)[1:]}Table",
        name=f"{snake(entity_name)}_{snake(name)}",
        left_key=f"{camel(entity_name)}Id",
        left_column=f"{snake(entity_name)}_id",
        right_key=f"{camel(target)}Id" if target != entity_name else f"related{target}Id",
        right_column=f"{snake(target)}_id"
        if target != entity_name
        else f"related_{snake(target)}_id",
        target_table=table_const(target),
        target_module=module_name(target),
        relation_name=f"{entity_name}.{name}",
        element_id=relation.id,
    )


def _add_relation(
    definition: AppDefinition, table: Table, entity_name: str, name: str, relation: Relation
) -> None:
    """Add the column, the join table, and the relational query entry of a relation.

    Both sides of a relation use the same `relationName`: the ID of the
    side that stores it, without `entities.` (`Task.project`).
    """
    target = relation.target
    stores = _stores(definition, entity_name, name, relation)
    found = _inverse(definition, relation)
    if relation.kind in ("many_to_one", "one_to_one") and stores:
        key = f"{camel(name)}Id"
        code = f'uuid("{snake(name)}_id")'
        if relation.required:
            code += ".notNull()"
        if relation.kind == "one_to_one":
            code += ".unique()"
        on_delete = _ON_DELETE[
            relation.on_delete or ("cascade" if relation.required else "set_null")
        ]
        # The return type stops the TypeScript error of a table that refers to itself.
        code += (
            f".references((): AnyPgColumn => {table_const(target)}.id,"
            f' {{ onDelete: "{on_delete}" }})'
        )
        table.columns.append(Column(key, code, relation.id, ("type AnyPgColumn",)))
        table.relations.append(
            RelationRef(
                camel(name),
                "one",
                table_const(target),
                module_name(target),
                key,
                f"{entity_name}.{name}",
                relation.id,
            )
        )
    elif relation.kind == "one_to_one" and found is not None:
        # The target stores the foreign key of this relation.
        inverse_name = found[0]
        table.relations.append(
            RelationRef(
                camel(name),
                "one",
                table_const(target),
                module_name(target),
                None,
                f"{target}.{inverse_name}",
                relation.id,
            )
        )
        table.inverse_ones.append(
            InverseOne(
                f"{camel(name)}Id", table_const(target), f"{camel(inverse_name)}Id", relation.id
            )
        )
    elif relation.kind == "one_to_many":
        inverse = relation.inverse or ""
        table.relations.append(
            RelationRef(
                camel(name),
                "many",
                table_const(target),
                module_name(target),
                None,
                f"{target}.{inverse}",
                relation.id,
            )
        )
    elif stores:
        join = _join_table(entity_name, name, relation)
        if found is not None:
            join.inverse_relation_name = f"{target}.{found[0]}"
        table.join_tables.append(join)
        table.relations.append(
            RelationRef(
                camel(name),
                "many",
                join.const,
                table.module,
                None,
                join.relation_name,
                relation.id,
            )
        )
        table.lists.append(
            ListRef(
                camel(name), join.const, table.module, join.left_key, join.right_key, relation.id
            )
        )
    else:
        # The target stores the join table of this relation and its inverse.
        assert found is not None
        join = _join_table(target, found[0], found[1])
        table.relations.append(
            RelationRef(
                camel(name),
                "many",
                join.const,
                module_name(target),
                None,
                f"{entity_name}.{name}",
                relation.id,
            )
        )
        table.lists.append(
            ListRef(
                camel(name),
                join.const,
                module_name(target),
                join.right_key,
                join.left_key,
                relation.id,
            )
        )


@dataclass(frozen=True, slots=True)
class SeedJoin:
    """The seed rows of a join table."""

    join: JoinTable
    rows: list[str]
    """The rows as TypeScript object literals."""


@dataclass(frozen=True, slots=True)
class SeedRecord:
    """A seed record of the definition (ADR 0021), as a TypeScript object literal."""

    element_id: str
    """The element of the record, for example `seed.Room.records.a101`."""
    row: str


@dataclass(frozen=True, slots=True)
class SeedTable:
    """The seed records of a table, as TypeScript object literals.

    `records`, `record_links`, and `record_joins` are the seed records of
    the definition. `rows`, `links`, and `joins` are the generated
    records, which go only into empty tables.
    """

    table: Table
    rows: list[str]
    """The rows to insert. An optional foreign key is null here."""
    links: list[str]
    """The optional foreign keys of the rows (`id` and the keys), to set after all inserts."""
    joins: list[SeedJoin]
    seed_id: str | None = None
    """The seed element of the entity, for example `seed.Room`, if the definition has one."""
    records: list[SeedRecord] = field(default_factory=list[SeedRecord])
    record_links: list[str] = field(default_factory=list[str])
    record_joins: list[SeedJoin] = field(default_factory=list[SeedJoin])

    @property
    def const(self) -> str:
        """The TypeScript name of the rows, for example `projectSeed`."""
        return self.table.const.removesuffix("Table") + "Seed"

    @property
    def links_const(self) -> str:
        return self.const + "Links"

    @property
    def records_const(self) -> str:
        """The TypeScript name of the seed records of the definition, for example `roomRecords`."""
        return self.table.const.removesuffix("Table") + "Records"

    @property
    def record_links_const(self) -> str:
        return self.records_const.removesuffix("Records") + "RecordLinks"


def seed_tables(definition: AppDefinition, tables: list[Table]) -> list[SeedTable]:
    """Return the seed records of each table, in an order that the required foreign keys permit.

    The records are the mock records of the shared generator
    (`appgen.bindings.shared.mock_data`), so the Next.js seed and the
    React mock data agree. The seed records of the definition come first
    in the mock records: they go into `records`, with the element of each
    record for its trace. A table comes after the tables that its
    required foreign keys refer to. The optional foreign keys are links:
    the seed sets them after it inserts all rows, so a cycle or a
    reference to the same table is no problem.
    """
    data = mock_data(definition)
    seeds = seed_records(definition)
    by_entity = {table.entity: table for table in tables}
    result: dict[str, SeedTable] = {}
    for table in tables:
        entity = definition.entities[table.entity]
        seed = definition.seed.get(table.entity)
        keys = list(seed.records) if seed is not None else []
        generated = _SeedRows(definition, table)
        fixed = _SeedRows(definition, table)
        for index, record in enumerate(data[table.entity]):
            (fixed if index < len(seeds.get(table.entity, [])) else generated).add(entity, record)
        result[table.entity] = SeedTable(
            table,
            generated.rows,
            generated.links,
            generated.joins,
            seed_id=seed.id if seed is not None else None,
            records=[
                SeedRecord(f"{seed.id}.records.{key}", row)
                for key, row in zip(keys, fixed.rows, strict=True)
                if seed is not None
            ],
            record_links=fixed.links,
            record_joins=fixed.joins,
        )
    return [result[entity] for entity in _insert_order(definition, by_entity)]


class _SeedRows:
    """The rows, the links, and the join rows of some records of a table."""

    def __init__(self, definition: AppDefinition, table: Table) -> None:
        self.definition = definition
        self.table = table
        self.rows: list[str] = []
        self.links: list[str] = []
        self.joins = [SeedJoin(join, []) for join in table.join_tables]

    def add(self, entity: Entity, record: dict[str, Any]) -> None:
        row = [("id", json.dumps(record["id"]))]
        link: list[tuple[str, str]] = []
        for field_name, spec in entity.stored_fields.items():
            row.append((camel(field_name), _ts_value(record.get(field_name), spec)))
            if spec.translatable:
                values = record.get(f"{field_name}_translations")
                row.append((translations_key(field_name), json.dumps(values, ensure_ascii=False)))
        for name, relation in entity.relations.items():
            if relation.kind not in ("many_to_one", "one_to_one"):
                continue
            if not _stores(self.definition, self.table.entity, name, relation):
                continue
            key, value = f"{camel(name)}Id", record.get(name)
            if relation.required:
                row.append((key, json.dumps(value)))
            else:
                row.append((key, "null"))
                if value is not None:
                    link.append((key, json.dumps(value)))
        self.rows.append(_ts_object(row))
        if link:
            self.links.append(_ts_object([("id", json.dumps(record["id"])), *link]))
        for seed_join in self.joins:
            name = seed_join.join.relation_name.split(".", 1)[1]
            targets: list[str] = record.get(name) or []
            for target in targets:
                seed_join.rows.append(
                    _ts_object(
                        [
                            (seed_join.join.left_key, json.dumps(record["id"])),
                            (seed_join.join.right_key, json.dumps(target)),
                        ]
                    )
                )


def _insert_order(definition: AppDefinition, tables: dict[str, Table]) -> list[str]:
    """Return the entities so that each comes after the targets of its required foreign keys."""
    needs = {
        entity: {
            relation.target
            for name, relation in definition.entities[entity].relations.items()
            if relation.kind in ("many_to_one", "one_to_one")
            and relation.required
            and relation.target != entity
            and _stores(definition, entity, name, relation)
        }
        for entity in tables
    }
    order: list[str] = []
    while len(order) < len(tables):
        ready = [e for e in tables if e not in order and needs[e] <= set(order)]
        # A cycle of required foreign keys: keep the order of the definition.
        order.append(ready[0] if ready else next(e for e in tables if e not in order))
    return order


def _ts_value(value: Any, spec: Field) -> str:
    if value is not None and spec.type == "datetime":
        return f"new Date({json.dumps(value)})"
    return json.dumps(value, ensure_ascii=False)


def _ts_object(entries: list[tuple[str, str]]) -> str:
    return "{ " + ", ".join(f"{key}: {value}" for key, value in entries) + " }"


@dataclass(frozen=True, slots=True)
class _Call:
    """A call of a TypeScript function or method, for example `eq(a, b)`."""

    name: str
    args: list[_Code]


@dataclass(frozen=True, slots=True)
class _Chain:
    """A chain of method calls, for example `getDb().select(...).from(...)`."""

    base: str
    calls: list[_Call]


type _Code = str | _Call | _Chain

_LINE_LENGTH = 110


def _inline(code: _Code) -> str:
    if isinstance(code, str):
        return code
    if isinstance(code, _Chain):
        return code.base + "".join(f".{_inline(call)}" for call in code.calls)
    return f"{code.name}({', '.join(_inline(arg) for arg in code.args)})"


def _format(code: _Code, indent: int) -> str:
    """Return an expression on one line if it fits, else with one part on each line."""
    one = _inline(code)
    if isinstance(code, str) or indent + len(one) <= _LINE_LENGTH:
        return one
    pad = " " * indent
    if isinstance(code, _Chain):
        lines = [code.base]
        for call in code.calls:
            lines.append(f"{pad}  .{_format(call, indent + 2)}")
        return "\n".join(lines)
    body = "".join(f"{pad}  {_format(arg, indent + 2)},\n" for arg in code.args)
    return f"{code.name}(\n{body}{pad})"


@dataclass(frozen=True, slots=True)
class OwnerCondition:
    """The Drizzle condition of the records of a user through an owner path (ADR 0025)."""

    code: str
    """The expression, of the parameter `user`."""
    operators: list[str]
    """The names to import from `drizzle-orm`, sorted."""
    tables: list[str]
    """The tables to import from `@/shared/db`, sorted."""


def belongs_to(steps: Sequence[PathStep], tables: dict[str, Table], indent: int) -> OwnerCondition:
    """Return the Drizzle condition of the records of `user` through an owner path (ADR 0025).

    A many-to-one step compares its foreign key with the IDs of the next
    entity, and a many-to-many step finds the IDs in its join table. The
    last step compares with `user`. Each inner step is a subquery.
    """
    operators: set[str] = set()
    used: set[str] = set()

    def ids(index: int) -> _Code:
        """The subquery of the IDs of the records of step `index` that belong to the user."""
        step, table = steps[index], tables[steps[index].entity]
        if step.many:
            join = next(item for item in table.lists if item.element_id == step.element_id)
            used.add(join.join_const)
            return _Chain(
                "getDb()",
                [
                    _Call("select", [f"{{ id: {join.join_const}.{join.owner_key} }}"]),
                    _Call("from", [join.join_const]),
                    _Call("where", [target(index, f"{join.join_const}.{join.target_key}")]),
                ],
            )
        used.add(table.const)
        return _Chain(
            "getDb()",
            [
                _Call("select", [f"{{ id: {table.const}.id }}"]),
                _Call("from", [table.const]),
                _Call("where", [condition(index)]),
            ],
        )

    def target(index: int, column: str) -> _Code:
        """The condition of a column with the ID of the target of step `index`."""
        if index == len(steps) - 1:
            operators.add("eq")
            return _Call("eq", [column, "user"])
        operators.add("inArray")
        return _Call("inArray", [column, ids(index + 1)])

    def condition(index: int) -> _Code:
        """The condition of the records of the entity of step `index`."""
        step, table = steps[index], tables[steps[index].entity]
        used.add(table.const)
        if step.many:
            operators.add("inArray")
            return _Call("inArray", [f"{table.const}.id", ids(index)])
        column = next(c for c in table.columns if c.element_id == step.element_id)
        return target(index, f"{table.const}.{column.key}")

    code = _format(condition(0), indent)
    return OwnerCondition(code, sorted(operators), sorted(used))
