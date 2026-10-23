"""The Drizzle schema of the Next.js app: tables, columns, and relations.

Each entity is a Postgres table with a UUID primary key `id`. Each field
is a column, and each `many_to_one` or `one_to_one` relation is a foreign
key column `<relation>_id`. A `many_to_many` relation gets a join table.
The templates of `src/shared/db/schema/` render these values.
"""

import json
from dataclasses import dataclass, field

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


@dataclass(frozen=True, slots=True)
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

    @property
    def left_relation(self) -> str:
        """The key of the relation to this entity, for example `project`."""
        return self.left_key.removesuffix("Id")

    @property
    def right_relation(self) -> str:
        """The key of the relation to the target entity, for example `person`."""
        return self.right_key.removesuffix("Id")


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

    @property
    def pg_imports(self) -> list[str]:
        """The builders to import from `drizzle-orm/pg-core`, sorted."""
        names = {"pgTable", "uuid"}
        names.update(i for c in self.columns for i in c.imports)
        if self.enums:
            names.add("pgEnum")
        if self.join_tables:
            names.add("primaryKey")
        return sorted(names)

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
        code += f".default({json.dumps(spec.default)})"
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
        for field_name, spec in entity.fields.items():
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
            _add_relation(table, entity_name, relation_name, relation)
        tables.append(table)
    return tables


def _add_relation(table: Table, entity_name: str, name: str, relation: Relation) -> None:
    """Add the column, the join table, and the relational query entry of a relation.

    Both sides of a relation use the same `relationName`: the ID of the
    side with the foreign key, without `entities.` (`Task.project`).
    """
    target = relation.target
    if relation.kind in ("many_to_one", "one_to_one"):
        key = f"{camel(name)}Id"
        code = f'uuid("{snake(name)}_id")'
        if relation.required:
            code += ".notNull()"
        if relation.kind == "one_to_one":
            code += ".unique()"
        on_delete = _ON_DELETE[
            relation.on_delete or ("cascade" if relation.required else "set_null")
        ]
        code += f'.references(() => {table_const(target)}.id, {{ onDelete: "{on_delete}" }})'
        table.columns.append(Column(key, code, relation.id, ()))
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
    else:
        join = JoinTable(
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
        table.join_tables.append(join)
        table.relations.append(
            RelationRef(
                camel(name),
                "many",
                join.const,
                table.module,
                None,
                f"{entity_name}.{name}",
                relation.id,
            )
        )
