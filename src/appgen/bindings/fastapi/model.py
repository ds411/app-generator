"""The app definition in the terms of the FastAPI binding.

The binding context gives this model to the templates as `py`. The model
gives each entity, field, relation, and operation the Python names, the
SQLAlchemy types, the Pydantic types, and the HTTP routes that the
templates write. The model reads only the definition, so it is
deterministic.
"""

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from appgen.bindings.fastapi.names import attribute, plural, singular
from appgen.bindings.fastapi.pysource import call, from_import, import_block
from appgen.bindings.fastapi.samples import PatternError, pattern_samples
from appgen.dsl.model import AppDefinition, Entity, Field, Operation, Relation
from appgen.gen.naming import constant, kebab, pascal, snake
from appgen.gen.render import GenerationError

EMBED_KEY = "x-fastapi-embed"
"""The extension key of a relation that the read schema embeds as an object."""
EXAMPLE_KEY = "x-example"
"""The extension key of a field that gives a valid sample value for the tests."""

_INT32 = 2**31 - 1
_ON_DELETE = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}
_ORDERED_TYPES = frozenset({"string", "integer", "decimal", "date", "datetime", "email", "url"})
_FILTER_TYPES = frozenset(
    {"string", "integer", "decimal", "boolean", "date", "uuid", "email", "url", "enum"}
)
# The field types that a test can send and compare with the response as JSON.
_EXACT_TYPES = frozenset({"string", "text", "integer", "boolean", "date", "email", "url", "enum"})
_SAMPLE_COUNT = 5


@dataclass(slots=True)
class PyEnum:
    """A Python enum class for a field of type `enum`."""

    name: str
    """The class name, for example `TaskStatus`."""
    members: list[tuple[str, str]]
    """The member names and their values, for example `("IN_PROGRESS", "in_progress")`."""
    constraint: str
    """The name of the check constraint in the database."""
    length: int
    """The length of the longest value."""


@dataclass(slots=True)
class PyField:
    """A field of an entity, or a param of a custom operation."""

    name: str
    """The name in the definition: the column name and the JSON name."""
    attr: str
    """The Python attribute name."""
    id: str
    type: str
    model_type: str
    """The Python type of the model attribute, without None."""
    schema_type: str
    """The Pydantic type of the schemas, without None."""
    sa_type: str
    """The SQLAlchemy column type, for example `String(120)`."""
    required: bool
    has_default: bool
    default: str
    """The default as a Python expression, or `None`."""
    unique: bool
    constraints: list[tuple[str, str]]
    """The keyword arguments of `pydantic.Field` for the rules of the field."""
    enum: PyEnum | None
    description: str | None
    filterable: bool
    sortable: bool
    exact: bool
    """True if a test can compare the JSON value that it sends with the response."""
    sample: str
    """A Python expression for a valid JSON value. It can use the integer `n`."""

    @property
    def aliased(self) -> bool:
        return self.attr != self.name

    @property
    def nullable(self) -> bool:
        return not self.required

    @property
    def read_type(self) -> str:
        """The type of the field in the read schema, without None."""
        return {"EmailStr": "str", "UrlStr": "str", "AwareDatetime": "dt.datetime"}.get(
            self.schema_type, self.schema_type
        )

    @property
    def mutable_default(self) -> bool:
        return self.type == "json" and self.default[:1] in ("[", "{")

    def declaration(self, mode: str) -> str:
        """Return the declaration of the field in a schema, for example `title: str`.

        The mode is `create` (also for params), `update`, or `read`.
        """
        alias = [f'alias="{self.name}"'] if self.aliased else []
        docs = [(k, v) for k, v in self.constraints if k in ("title", "description")]
        rules = [f"{k}={v}" for k, v in self.constraints if mode != "read" or (k, v) in docs]
        if mode == "read":
            type_ = self.read_type + (" | None" if self.nullable else "")
            return _declare(self.attr, type_, None, [*alias, *rules])
        if mode == "update":
            return _declare(self.attr, f"{self.schema_type} | None", "None", [*alias, *rules])
        if self.required and not self.has_default:
            return _declare(self.attr, self.schema_type, None, [*alias, *rules])
        type_ = self.schema_type if self.required else f"{self.schema_type} | None"
        if self.mutable_default:
            factory = f"lambda: {self.default}"
            return _declare(self.attr, type_, None, [f"default_factory={factory}", *alias, *rules])
        return _declare(self.attr, type_, self.default, [*alias, *rules])


def _declare(attr: str, type_: str, default: str | None, args: list[str]) -> str:
    """Return a field declaration of a Pydantic model, with `Field()` for its rules."""
    if not args:
        return f"{attr}: {type_}" + (f" = {default}" if default is not None else "")
    if default is not None:
        args = [f"default={default}", *args]
    return call(f"{attr}: {type_} = ", "Field", args)


@dataclass(slots=True)
class PyRelation:
    """A relation of an entity."""

    name: str
    attr: str
    id: str
    kind: str
    target: str
    """The name of the target entity."""
    side: str
    """`fk` (the foreign key is on this entity), `back` (it is on the target), or `m2m`."""
    required: bool
    fk: str | None = None
    """The foreign key column, for the `fk` side, for example `project_id`."""
    fk_attr: str | None = None
    on_delete: str | None = None
    unique: bool = False
    back_populates: str | None = None
    """The attribute of the other side, if the definition declares it."""
    remote_fk: str | None = None
    """For the `back` side: the foreign key attribute on the target."""
    secondary: str | None = None
    """For the `m2m` side: the name of the join table."""
    local_column: str | None = None
    remote_column: str | None = None
    ids_field: str | None = None
    """For the `m2m` side: the field of the input schemas with the IDs of the targets."""
    embed: bool = False

    @property
    def many(self) -> bool:
        return self.side == "m2m" or self.kind == "one_to_many"

    @property
    def nullable(self) -> bool:
        return not (self.side == "fk" and self.required)

    def declarations(self, mode: str) -> list[str]:
        """Return the declarations of the relation in a schema.

        The mode is `create`, `update`, or `read`. The input schemas have
        the ID of the target, or the IDs of the targets. The read schema
        also has the target object, if the relation is embedded.
        """
        lines: list[str] = []
        if self.side == "fk":
            assert self.fk_attr is not None
            if mode == "update":
                lines.append(f"{self.fk_attr}: UUID | None = None")
            elif self.required:
                lines.append(f"{self.fk_attr}: UUID")
            else:
                lines.append(f"{self.fk_attr}: UUID | None" + (" = None" if mode != "read" else ""))
        elif self.side == "m2m":
            lines.append(
                {
                    "create": f"{self.ids_field}: list[UUID] = Field(default_factory=list[UUID])",
                    "update": f"{self.ids_field}: list[UUID] | None = None",
                    "read": f"{self.ids_field}: list[UUID]",
                }[mode]
            )
        if mode == "read" and self.embed:
            target = f"{self.target}Read"
            if self.many:
                lines.append(f"{self.attr}: list[{target}]")
            else:
                lines.append(f"{self.attr}: {target}" + (" | None" if self.nullable else ""))
        return lines


@dataclass(slots=True)
class PyJoinTable:
    """A join table of a many-to-many relation."""

    name: str
    relation_id: str
    left_table: str
    left_column: str
    right_table: str
    right_column: str


@dataclass(slots=True)
class PyOperation:
    """An operation, as an endpoint of the REST API."""

    name: str
    id: str
    kind: str
    entity: str
    method: str
    path: str
    """The path under the prefix of the router of the slice, for example `/{id}`."""
    status: int
    errors: list[int]
    """The status codes of the errors that the endpoint can return."""
    params: list[PyField]
    returns: str | None
    """The entity that the operation returns, or None."""
    description: str | None
    module: str
    """The module of the operation in its slice, for example `create_task`."""

    @property
    def custom(self) -> bool:
        return self.kind == "custom"

    @property
    def params_class(self) -> str:
        return pascal(self.name) + "Params"

    @property
    def has_id(self) -> bool:
        return "{id}" in self.path


@dataclass(slots=True)
class PyEntity:
    """An entity, as a vertical slice of the app."""

    name: str
    id: str
    snake: str
    slice: str
    """The name of the slice folder and of the table, for example `tasks`."""
    path: str
    """The URL prefix of the slice, for example `/tasks`."""
    label: str
    plural_label: str
    description: str | None
    fields: list[PyField]
    relations: list[PyRelation] = field(default_factory=list[PyRelation])
    operations: list[PyOperation] = field(default_factory=list[PyOperation])
    join_tables: list[PyJoinTable] = field(default_factory=list[PyJoinTable])
    app_entities: dict[str, PyEntity] = field(default_factory=dict[str, "PyEntity"], repr=False)
    """All entities of the app, to find the targets of the relations."""

    @property
    def table(self) -> str:
        return self.slice

    @property
    def enums(self) -> list[PyEnum]:
        return [f.enum for f in self.fields if f.enum is not None]

    @property
    def fk_relations(self) -> list[PyRelation]:
        return [r for r in self.relations if r.side == "fk"]

    @property
    def m2m_relations(self) -> list[PyRelation]:
        return [r for r in self.relations if r.side == "m2m"]

    @property
    def embedded(self) -> list[PyRelation]:
        return [r for r in self.relations if r.embed]

    @property
    def read_relations(self) -> list[PyRelation]:
        """The relations that the read schema shows: the foreign keys, the IDs, or the objects."""
        return [r for r in self.relations if r.side in ("fk", "m2m") or r.embed]

    @property
    def input_relations(self) -> list[PyRelation]:
        """The relations that the input schemas set: the foreign keys and the IDs."""
        return [r for r in self.relations if r.side in ("fk", "m2m")]

    @property
    def not_null(self) -> list[str]:
        """The attributes that an update cannot set to null."""
        names = [f.attr for f in self.fields if f.required]
        return names + [r.fk_attr for r in self.fk_relations if r.required and r.fk_attr]

    def reject_null_call(self) -> str:
        """Return the statement of the update schema that rejects null for required fields."""
        return call("return ", "reject_null", ["self", *(f'"{n}"' for n in self.not_null)], 8)

    def schema_imports(self) -> str:
        """Return the import block of the schemas module of the slice."""
        types = {f.schema_type for f in self.fields} | {f.read_type for f in self.fields}
        lines: set[str] = set()
        if any(t.startswith("dt.") for t in types):
            lines.add("import datetime as dt")
        if "Decimal" in types:
            lines.add("from decimal import Decimal")
        lines.add("from uuid import UUID")
        declarations = [f.declaration(m) for f in self.fields for m in ("create", "update", "read")]
        declarations += [
            d
            for r in self.relations
            for m in ("create", "update", "read")
            for d in r.declarations(m)
        ]
        pydantic = {"Field"} if any("Field(" in d for d in declarations) else set[str]()
        for name in ("AwareDatetime", "EmailStr", "JsonValue"):
            if name in types:
                pydantic.add(name)
        if self.not_null:
            pydantic.add("model_validator")
            lines.add("from typing import Self")
        if pydantic:
            lines.add(from_import("pydantic", pydantic))
        core = {"InputModel", "ReadModel"}
        if self.not_null:
            core.add("reject_null")
        lines.add(from_import("app.core.schemas", core))
        if "UrlStr" in types:
            lines.add("from app.core.types import UrlStr")
        if self.enums:
            lines.add(from_import(f"app.features.{self.slice}.enums", {e.name for e in self.enums}))
        for rel in self.embedded:
            target = self.app_entities[rel.target]
            if target.name != self.name:
                lines.add(f"from app.features.{target.slice}.schemas import {target.name}Read")
        return import_block(lines)


@dataclass(slots=True)
class PyApp:
    """The whole app definition in the terms of the binding."""

    name: str
    package: str
    """The name of the app in snake case, for example the database name."""
    title: str
    description: str | None
    entities: dict[str, PyEntity]
    operations: dict[str, PyOperation]

    def entity(self, name: str) -> PyEntity:
        return self.entities[name]

    def entity_order(self) -> list[PyEntity]:
        """The entities in source order."""
        return list(self.entities.values())

    @property
    def join_tables(self) -> list[PyJoinTable]:
        return [t for e in self.entities.values() for t in e.join_tables]

    @property
    def custom_operations(self) -> list[PyOperation]:
        return [o for o in self.operations.values() if o.custom]


def python_app(definition: AppDefinition) -> PyApp:
    """Return the model of the binding for an app definition.

    Raise GenerationError if two names of an entity give the same Python
    name, or if embedded relations form a cycle.
    """
    entities = {name: _entity(name, entity) for name, entity in definition.entities.items()}
    for py_entity in entities.values():
        py_entity.app_entities = entities
    for name, entity in definition.entities.items():
        _relations(definition, entities, name, entity)
    _check_embed_cycles(entities)
    operations: dict[str, PyOperation] = {}
    for name, operation in definition.operations.items():
        py_operation = _operation(name, operation, entities)
        operations[name] = py_operation
        entities[operation.entity].operations.append(py_operation)
    for entity in entities.values():
        _place_routes(entity)
        _check_names(entity)
    return PyApp(
        name=definition.app.name,
        package=snake(definition.app.name),
        title=definition.app.title,
        description=definition.app.description,
        entities=entities,
        operations=operations,
    )


def _entity(name: str, entity: Entity) -> PyEntity:
    slice_name = snake(entity.plural_label) if entity.plural_label else plural(name)
    label = entity.label or " ".join(snake(name).split("_")).capitalize()
    return PyEntity(
        name=name,
        id=entity.id,
        snake=snake(name),
        slice=slice_name,
        path="/" + kebab(slice_name),
        label=label,
        plural_label=entity.plural_label or " ".join(slice_name.split("_")).capitalize(),
        description=entity.description,
        fields=[
            _field(field_name, f, f"{name}{pascal(field_name)}", slice_name)
            for field_name, f in entity.fields.items()
        ],
    )


def _field(name: str, f: Field, enum_name: str, table: str) -> PyField:
    enum = None
    if f.type == "enum":
        values = f.values or []
        enum = PyEnum(
            name=enum_name,
            members=[(constant(v), v) for v in values],
            constraint=f"ck_{table}_{name}",
            length=max((len(v) for v in values), default=1),
        )
    model_type, schema_type, sa_type = _types(f, enum)
    return PyField(
        name=name,
        attr=attribute(name),
        id=f.id,
        type=f.type,
        model_type=model_type,
        schema_type=schema_type,
        sa_type=sa_type,
        required=f.required,
        has_default=f.default is not None,
        default=_default(f, enum),
        unique=f.unique,
        constraints=_constraints(f),
        enum=enum,
        description=f.description,
        filterable=f.type in _FILTER_TYPES,
        sortable=f.type in _ORDERED_TYPES or f.type in ("boolean", "enum", "uuid"),
        exact=f.type in _EXACT_TYPES,
        sample=_sample(f, enum),
    )


def _types(f: Field, enum: PyEnum | None) -> tuple[str, str, str]:
    """Return the model type, the schema type, and the SQLAlchemy type of a field."""
    match f.type:
        case "string" | "email" | "url":
            length = f"String({f.max_length})" if f.max_length else "String"
            schema = {"string": "str", "email": "EmailStr", "url": "UrlStr"}[f.type]
            return "str", schema, length
        case "text":
            return "str", "str", "Text"
        case "integer":
            big = any(abs(v) > _INT32 for v in (f.min, f.max) if v is not None)
            return "int", "int", "BigInteger" if big else "Integer"
        case "decimal":
            numeric = f"Numeric({f.precision}, {f.scale or 0})" if f.precision else "Numeric"
            return "Decimal", "Decimal", numeric
        case "boolean":
            return "bool", "bool", "Boolean"
        case "date":
            return "dt.date", "dt.date", "Date"
        case "datetime":
            return "dt.datetime", "AwareDatetime", "DateTime(timezone=True)"
        case "uuid":
            return "UUID", "UUID", "Uuid"
        case "enum":
            assert enum is not None
            return enum.name, enum.name, f"enum_type({enum.name}, {enum.constraint!r})"
        case _:
            return "Any", "JsonValue", "JSONB"


def _default(f: Field, enum: PyEnum | None) -> str:
    value = f.default
    if value is None:
        return "None"
    match f.type:
        case "enum":
            assert enum is not None
            return f"{enum.name}.{constant(str(value))}"
        case "decimal":
            return f'Decimal("{value}")'
        case "date":
            return f'dt.date.fromisoformat("{value}")'
        case "datetime":
            return f'dt.datetime.fromisoformat("{value}")'
        case "uuid":
            return f'UUID("{value}")'
        case "integer":
            return str(int(value))  # pyright: ignore[reportArgumentType]
        case "boolean":
            return "True" if value else "False"
        case "json":
            return _python_literal(value)
        case _:
            return json.dumps(value, ensure_ascii=False)


def _python_literal(value: Any) -> str:
    """Return a JSON value as a Python literal, with the quotes of the Ruff formatter."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_python_literal(v) for v in value) + "]"  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, dict):
        items = (f"{_python_literal(k)}: {_python_literal(v)}" for k, v in value.items())  # pyright: ignore[reportUnknownVariableType]
        return "{" + ", ".join(items) + "}"
    return repr(value)


def _constraints(f: Field) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if f.type in ("string", "text", "email", "url"):
        if f.min_length is not None and f.type != "email":
            out.append(("min_length", str(f.min_length)))
        if f.max_length is not None and f.type not in ("email",):
            out.append(("max_length", str(f.max_length)))
        if f.pattern is not None and f.type == "string":
            out.append(("pattern", json.dumps(f.pattern)))
    if f.type in ("integer", "decimal"):
        for key, value in (("ge", f.min), ("le", f.max)):
            if value is not None:
                out.append((key, _number(value, f.type)))
        if f.type == "decimal" and f.precision is not None:
            out.append(("max_digits", str(f.precision)))
            out.append(("decimal_places", str(f.scale or 0)))
    if f.label:
        out.append(("title", json.dumps(f.label, ensure_ascii=False)))
    if f.description:
        out.append(("description", json.dumps(f.description, ensure_ascii=False)))
    return out


def _number(value: float, type_: str) -> str:
    if type_ == "integer":
        return str(int(value))
    return f'Decimal("{Decimal(str(value)).normalize():f}")'


def _sample(f: Field, enum: PyEnum | None) -> str:
    """Return a Python expression for a valid JSON value of a field, for the tests.

    The expression uses the integer `n`, so that each record of a test can
    get a different value for a unique field.
    """
    if EXAMPLE_KEY in f.extensions:
        return _python_literal(f.extensions[EXAMPLE_KEY])
    match f.type:
        case "string" | "text":
            if f.pattern is not None:
                return _pattern_sample(f)
            return _text_sample(f)
        case "email":
            return 'f"user{n}@example.com"'
        case "url":
            return 'f"https://example.com/{n}"'
        case "integer":
            low, span = _int_range(f.min, f.max, None)
            return f"{low} + n % {span}" if span > 1 else str(low)
        case "decimal":
            digits = (f.precision - (f.scale or 0)) if f.precision else None
            low, span = _int_range(f.min, f.max, digits)
            return f"str({low} + n % {span})" if span > 1 else f'"{low}"'
        case "boolean":
            return "n % 2 == 0"
        case "date":
            return 'f"2026-01-{1 + n % 28:02d}"'
        case "datetime":
            return 'f"2026-01-01T{n % 24:02d}:00:00Z"'
        case "uuid":
            return 'f"00000000-0000-4000-8000-{n:012d}"'
        case "enum":
            assert enum is not None
            values = [v for _, v in enum.members]
            return f"{json.dumps(values)}[n % {len(values)}]"
        case _:
            return '{"n": n}'


def _text_sample(f: Field) -> str:
    word = f.id.rsplit(".", 1)[-1].replace("_", "-")
    budget = (f.max_length or 60) - 4
    base = word[: max(budget, 1)]
    if f.min_length is not None and len(base) + 1 < f.min_length:
        base = base.ljust(f.min_length - 1, "x")
    if f.max_length is not None and f.max_length < 5:
        return f"str(n % {10 ** (f.max_length)})"
    return f'f"{base}{{n}}"'


def _pattern_sample(f: Field) -> str:
    assert f.pattern is not None
    try:
        samples = pattern_samples(f.pattern, _SAMPLE_COUNT, f.min_length or 0, f.max_length)
    except PatternError as error:
        raise GenerationError(
            f"The field '{f.id}' needs a sample value for the tests: {error} "
            f"Give one with the key '{EXAMPLE_KEY}'."
        ) from None
    if len(samples) == 1:
        return json.dumps(samples[0])
    return f"{json.dumps(samples)}[n % {len(samples)}]"


def _int_range(low: float | None, high: float | None, digits: int | None) -> tuple[int, int]:
    """Return the first integer and the count of integers that a field permits, up to 1000."""
    first = math.ceil(low) if low is not None else 0
    last = math.floor(high) if high is not None else first + 999
    if digits is not None:
        last = min(last, 10**digits - 1)
    if high is not None and low is None and first > last:
        first = last
    return first, max(1, min(last - first + 1, 1000))


def _relations(
    definition: AppDefinition, entities: dict[str, PyEntity], name: str, entity: Entity
) -> None:
    py_entity = entities[name]
    for rel_name, relation in entity.relations.items():
        target = entities[relation.target]
        rel = PyRelation(
            name=rel_name,
            attr=attribute(rel_name),
            id=relation.id,
            kind=relation.kind,
            target=relation.target,
            side="fk",
            required=relation.required,
            back_populates=relation.inverse,
            embed=bool(relation.extensions.get(EMBED_KEY, False)),
        )
        if relation.kind == "one_to_many" or (
            relation.kind == "one_to_one" and not _owns_one_to_one(definition, name, relation)
        ):
            assert relation.inverse is not None or relation.kind == "one_to_one"
            rel.side = "back"
            rel.remote_fk = f"{relation.inverse}_id" if relation.inverse else None
        elif relation.kind == "many_to_many":
            rel.side = "m2m"
            rel.ids_field = singular(rel_name) + "_ids"
            _join_table(definition, entities, py_entity, target, rel_name, relation, rel)
        else:
            rel.fk = f"{rel_name}_id"
            rel.fk_attr = attribute(rel.fk)
            rel.on_delete = _ON_DELETE.get(relation.on_delete or "")
            rel.unique = relation.kind == "one_to_one"
        py_entity.relations.append(rel)


def _owns_one_to_one(definition: AppDefinition, name: str, relation: Relation) -> bool:
    """Return true if this side of a one-to-one relation has the foreign key.

    Without an inverse, this side has it (ADR 0002). With an inverse, the
    side that sets `required` or `on_delete` has it. If both or none set
    them, the side that comes first in the definition has it.
    """
    if relation.inverse is None:
        return True
    other = definition.entities[relation.target].relations[relation.inverse]
    mine = relation.required or relation.on_delete is not None
    theirs = other.required or other.on_delete is not None
    if mine != theirs:
        return mine
    order = list(definition.entities)
    if name != relation.target:
        return order.index(name) < order.index(relation.target)
    names = list(definition.entities[name].relations)
    return names.index(other.id.rsplit(".", 1)[-1]) > names.index(relation.id.rsplit(".", 1)[-1])


def _join_table(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    owner: PyEntity,
    target: PyEntity,
    rel_name: str,
    relation: Relation,
    rel: PyRelation,
) -> None:
    """Find or make the join table of a many-to-many relation.

    A pair of relations that name each other as inverse shares one table.
    The side that comes first in the definition owns the table.
    """
    if relation.inverse is not None:
        order = [(e, r) for e, ent in definition.entities.items() for r in ent.relations]
        this, other = (owner.name, rel_name), (relation.target, relation.inverse)
        if order.index(other) < order.index(this):
            table = next(
                t
                for t in entities[relation.target].join_tables
                if t.relation_id == f"{target.id}.relations.{relation.inverse}"
            )
            rel.secondary = table.name
            rel.local_column, rel.remote_column = table.right_column, table.left_column
            return
    left = f"{owner.snake}_id"
    right = f"{target.snake}_id" if target.name != owner.name else f"{singular(rel_name)}_id"
    table = PyJoinTable(
        name=f"{owner.slice}_{rel_name}",
        relation_id=relation.id,
        left_table=owner.table,
        left_column=left,
        right_table=target.table,
        right_column=right,
    )
    owner.join_tables.append(table)
    rel.secondary = table.name
    rel.local_column, rel.remote_column = left, right


def _check_embed_cycles(entities: dict[str, PyEntity]) -> None:
    def visit(name: str, path: list[str]) -> None:
        for rel in entities[name].embedded:
            if rel.target in path:
                chain = " -> ".join([*path, rel.target])
                raise GenerationError(
                    f"The embedded relations form a cycle: {chain}. "
                    f"Remove '{EMBED_KEY}' from one of them."
                )
            visit(rel.target, [*path, rel.target])

    for name in entities:
        visit(name, [name])


def _operation(name: str, operation: Operation, entities: dict[str, PyEntity]) -> PyOperation:
    entity = entities[operation.entity]
    returns = operation.returns if operation.returns != "none" else None
    status = {"create": 201, "delete": 204}.get(operation.kind, 200)
    if operation.kind == "custom" and returns is None:
        status = 204
    errors = {
        "create": [409, 422],
        "read": [404, 422],
        "update": [404, 409, 422],
        "delete": [404, 409, 422],
        "list": [422],
        "custom": [404, 409, 422, 501],
    }[operation.kind]
    return PyOperation(
        name=name,
        id=operation.id,
        kind=operation.kind,
        entity=entity.name,
        method={"create": "post", "read": "get", "update": "patch", "delete": "delete"}.get(
            operation.kind, "get" if operation.kind == "list" else "post"
        ),
        path="",
        status=status,
        errors=errors,
        params=[
            _field(p_name, p, f"{pascal(name)}{pascal(p_name)}", f"{entity.slice}_{name}")
            for p_name, p in operation.params.items()
        ],
        returns=returns,
        description=operation.description,
        module=f"{name}_gen" if operation.kind == "custom" else name,
    )


def _place_routes(entity: PyEntity) -> None:
    """Give each operation of an entity its path, and sort the routes.

    The first operation of each CRUD kind gets the usual REST path. A
    custom operation, and a second operation of a kind, get a path with
    the operation name. The routes with a fixed path come before the
    routes with an ID, so that a fixed path never reads as an ID.
    """
    seen: set[str] = set()
    for op in entity.operations:
        base = "/{id}" if op.kind in ("read", "update", "delete", "custom") else ""
        if op.kind != "custom" and op.kind not in seen:
            op.path = base
        else:
            op.path = f"{base}/{kebab(op.name)}"
        seen.add(op.kind)
    entity.operations.sort(key=lambda op: op.has_id)


def _check_names(entity: PyEntity) -> None:
    names: dict[str, str] = {"id": "the primary key"}

    def claim(name: str, owner: str) -> None:
        if name in names:
            raise GenerationError(
                f"In the entity '{entity.name}', {owner} and {names[name]} "
                f"both give the Python name '{name}'."
            )
        names[name] = owner

    for f in entity.fields:
        claim(f.attr, f"the field '{f.name}'")
    for rel in entity.relations:
        claim(rel.attr, f"the relation '{rel.name}'")
        if rel.fk_attr:
            claim(rel.fk_attr, f"the foreign key of the relation '{rel.name}'")
        if rel.ids_field:
            claim(rel.ids_field, f"the IDs of the relation '{rel.name}'")


def binding_context(definition: AppDefinition) -> dict[str, Any]:
    """Return the values that the binding adds to the context of all templates."""
    return {"py": python_app(definition)}
