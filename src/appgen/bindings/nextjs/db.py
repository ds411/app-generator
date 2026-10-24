"""The Drizzle schema of the Next.js app: tables, columns, and relations.

Each entity is a Postgres table with a UUID primary key `id`. Each field
is a column, and each `many_to_one` or `one_to_one` relation is a foreign
key column `<relation>_id`. A `many_to_many` relation gets a join table.
The templates of `src/shared/db/schema/` render these values. The seed
of `src/shared/db/seed.ts` fills the tables with the shared mock records.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl.model import AppDefinition, Field, Relation
from appgen.gen.naming import camel, snake

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

    @property
    def pg_imports(self) -> list[str]:
        """The builders to import from `drizzle-orm/pg-core`, sorted."""
        names = {"pgTable", "uuid"}
        names.update(i for c in self.columns for i in c.imports)
        if self.enums:
            names.add("pgEnum")
        if self.join_tables:
            names.add("primaryKey")
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
        for relation_name, relation in entity.relations.items():
            _add_relation(definition, table, entity_name, relation_name, relation)
        tables.append(table)
    return tables


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
class SeedTable:
    """The seed records of a table, as TypeScript object literals."""

    table: Table
    rows: list[str]
    """The rows to insert. An optional foreign key is null here."""
    links: list[str]
    """The optional foreign keys of the rows (`id` and the keys), to set after all inserts."""
    joins: list[SeedJoin]

    @property
    def const(self) -> str:
        """The TypeScript name of the rows, for example `projectSeed`."""
        return self.table.const.removesuffix("Table") + "Seed"

    @property
    def links_const(self) -> str:
        return self.const + "Links"


def seed_tables(definition: AppDefinition, tables: list[Table]) -> list[SeedTable]:
    """Return the seed records of each table, in an order that the required foreign keys permit.

    The records are the mock records of the shared generator
    (`appgen.bindings.shared.mock_data`), so the Next.js seed and the
    React mock data agree. A table comes after the tables that its
    required foreign keys refer to. The optional foreign keys are links:
    the seed sets them after it inserts all rows, so a cycle or a
    reference to the same table is no problem.
    """
    data = mock_data(definition)
    by_entity = {table.entity: table for table in tables}
    result: dict[str, SeedTable] = {}
    for table in tables:
        entity = definition.entities[table.entity]
        rows: list[str] = []
        links: list[str] = []
        joins = [SeedJoin(join, []) for join in table.join_tables]
        for record in data[table.entity]:
            row = [("id", json.dumps(record["id"]))]
            link: list[tuple[str, str]] = []
            for field_name, spec in entity.stored_fields.items():
                row.append((camel(field_name), _ts_value(record.get(field_name), spec)))
            for name, relation in entity.relations.items():
                if relation.kind not in ("many_to_one", "one_to_one"):
                    continue
                if not _stores(definition, table.entity, name, relation):
                    continue
                key, value = f"{camel(name)}Id", record.get(name)
                if relation.required:
                    row.append((key, json.dumps(value)))
                else:
                    row.append((key, "null"))
                    if value is not None:
                        link.append((key, json.dumps(value)))
            rows.append(_ts_object(row))
            if link:
                links.append(_ts_object([("id", json.dumps(record["id"])), *link]))
            for seed_join in joins:
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
        result[table.entity] = SeedTable(table, rows, links, joins)
    return [result[entity] for entity in _insert_order(definition, by_entity)]


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
