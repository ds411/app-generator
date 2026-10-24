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
from dataclasses import field as dataclass_field
from decimal import Decimal
from typing import Any, cast

from appgen.bindings.fastapi.integrations import mocks_imports, python_apis
from appgen.bindings.fastapi.names import attribute, plural, singular
from appgen.bindings.fastapi.pysource import call, from_import, import_block
from appgen.bindings.fastapi.queries import PyListQuery, list_query
from appgen.bindings.fastapi.samples import PatternError, pattern_samples
from appgen.dsl.expressions import (
    Binary,
    Call,
    Expression,
    FieldRef,
    Negate,
    Number,
    parse_expression,
)
from appgen.dsl.model import AppDefinition, Entity, Field, Operation, Relation
from appgen.dsl.rules import EntityCompareRule, EntityUniqueRule
from appgen.gen.naming import constant, kebab, pascal, snake
from appgen.gen.render import GenerationError

EMBED_KEY = "x-fastapi-embed"
"""The extension key of a relation that the read schema embeds as an object."""
EXAMPLE_KEY = "x-example"
"""The extension key of a field that gives a valid sample value for the tests."""
PATH_KEY = "x-fastapi-path"
"""The extension key of an entity that sets the URL prefix of its router."""
TABLE_KEY = "x-fastapi-table"
"""The extension key of an entity or a many-to-many relation that sets its table name."""
COLUMN_KEY = "x-fastapi-column"
"""The extension key of a relation that sets the name of its foreign key column."""
RATE_LIMIT_STORE_KEY = "x-fastapi-rate-limit-store"
"""The extension key of the app that selects the store of the rate limit: `memory` or `redis`."""
DEPLOY_KEY = "x-fastapi-deploy"
"""The extension key of the app that selects the deployment targets: one target or a list."""
DEPLOY_TARGETS = ("kubernetes", "knative")
"""The deployment targets, in the order of the README. `kubernetes` is the default."""

_INT32 = 2**31 - 1
_ON_DELETE = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}
_ORDERED_TYPES = frozenset({"string", "integer", "decimal", "date", "datetime", "email", "url"})
_FILTER_TYPES = frozenset(
    {"string", "integer", "decimal", "boolean", "date", "uuid", "email", "url", "enum"}
)
# The field types that a test can send and compare with the response as JSON.
_EXACT_TYPES = frozenset({"string", "text", "integer", "boolean", "date", "email", "url", "enum"})
_SAMPLE_COUNT = 5
_COMPUTE_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "div"}
"""The functions of `app/core/compute.py` for the operators of the expressions."""


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

    def column(self) -> str:
        """Return the declaration of the model attribute, for example `title: Mapped[str] = ...`."""
        type_ = self.model_type + (" | None" if self.nullable else "")
        args = [f'"{self.name}"'] if self.aliased else []
        args.append(self.sa_type)
        if self.unique:
            args.append("unique=True")
        return call(f"{self.attr}: Mapped[{type_}] = ", "mapped_column", args)

    def migration_column(self) -> str:
        """Return the `sa.Column` of the field in the migration."""
        args = [f'"{self.name}"', self.migration_type(), f"nullable={not self.required}"]
        one_line = call("", "sa.Column", args, 8, ",")
        if "\n" in one_line:
            args[1] = self.migration_type(12)
        return call("", "sa.Column", args, 8, ",")

    def migration_type(self, indent: int | None = None) -> str:
        """Return the SQLAlchemy type of the column in the migration, without the app classes.

        With an indent, a long enum type has one argument on each line.
        """
        if self.enum is not None:
            args = [f'"{v}"' for _, v in self.enum.members]
            args += [
                f'name="{self.enum.constraint}"',
                "native_enum=False",
                "create_constraint=True",
                f"length={self.enum.length}",
            ]
            if indent is None:
                return f"sa.Enum({', '.join(args)})"
            return call("", "sa.Enum", args, indent)
        if self.sa_type in _MIGRATION_TYPES:
            return _MIGRATION_TYPES[self.sa_type]
        if "(" in self.sa_type:
            return "sa." + self.sa_type
        return f"sa.{self.sa_type}()"

    def filter_declaration(self) -> str:
        """Return the declaration of the field in the query of a list endpoint."""
        type_ = self.read_type + " | None"
        if self.aliased:
            return _declare(self.attr, type_, "None", [f'alias="{self.name}"'])
        return f"{self.attr}: {type_} = None"

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
    computed: bool = False
    """True if a computed field reads the target: the model loads it with the record."""

    @property
    def many(self) -> bool:
        return self.side == "m2m" or self.kind == "one_to_many"

    @property
    def nullable(self) -> bool:
        return not (self.side == "fk" and self.required)

    @property
    def lazy(self) -> str:
        """The loading strategy: the read schema needs the many-to-many and embedded targets."""
        return "selectin" if self.side == "m2m" or self.embed or self.computed else "raise"

    def model_lines(self, entity: PyEntity) -> list[str]:
        """Return the declarations of the relation in the model of its entity."""
        target = self.target
        lines: list[str] = []
        args: list[str] = []
        if self.back_populates:
            args.append(f'back_populates="{self.back_populates}"')
        if self.side == "fk":
            assert self.fk and self.fk_attr
            nullable = " | None" if not self.required else ""
            key = [f'ForeignKey("{entity.app_entities[target].table}.id"']
            if self.on_delete:
                key[0] += f', ondelete="{self.on_delete}"'
            key[0] += ")"
            key.append("unique=True" if self.unique else "index=True")
            column = [f'"{self.fk}"', *key] if self.fk_attr != self.fk else key
            lines.append(
                call(f"{self.fk_attr}: Mapped[UUID{nullable}] = ", "mapped_column", column)
            )
            args.append(f"foreign_keys=[{self.fk_attr}]")
            if target == entity.name:
                args.append(f'remote_side="{target}.id"')
            args.append(f'lazy="{self.lazy}"')
            lines.append(call(f"{self.attr}: Mapped[{target}{nullable}] = ", "relationship", args))
        elif self.side == "back":
            other = entity.app_entities[target]
            remote = next(r for r in other.relations if r.name == self.back_populates)
            args.append(f'foreign_keys="{target}.{remote.fk_attr}"')
            args += [f'lazy="{self.lazy}"', "passive_deletes=True"]
            if self.many:
                type_ = f"list[{target}]"
            else:
                type_ = f"{target} | None"
                args.append("uselist=False")
            lines.append(call(f"{self.attr}: Mapped[{type_}] = ", "relationship", args))
        else:
            other = entity.app_entities[target]
            args = [
                f'secondary="{self.secondary}"',
                f'primaryjoin="{entity.name}.id == {self.secondary}.c.{self.local_column}"',
                f'secondaryjoin="{other.name}.id == {self.secondary}.c.{self.remote_column}"',
                *args,
                f'lazy="{self.lazy}"',
                "passive_deletes=True",
            ]
            lines.append(call(f"{self.attr}: Mapped[list[{target}]] = ", "relationship", args))
        return lines

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
class PyComputed:
    """A computed field: a property of the model, and a field of the read schema."""

    name: str
    attr: str
    id: str
    type: str
    """The Python type without `| None`: `int` or `Decimal`."""
    lines: list[str]
    """The statements of the body of the property, of `self`."""
    source: str
    """The expression in the definition."""

    def property_lines(self) -> list[str]:
        """Return the lines of the property of the model."""
        return [
            "@property",
            f"def {self.attr}(self) -> {self.type} | None:",
            f'    """The computed field `{self.name}`: {self.source}."""',
            *(f"    {line}" for line in self.lines),
        ]


@dataclass(slots=True)
class PyRule:
    """A rule of an entity: a compare, a unique, or a `no_overlap` rule."""

    name: str
    id: str
    kind: str
    message: str
    field: str = ""
    """compare: the attribute of the field."""
    op: str = ""
    other: str = ""
    columns: list[str] = dataclass_field(default_factory=list[str])
    """unique: the columns of the table."""
    constraint: str = ""
    """unique: the name of the constraint."""
    start: str = ""
    end: str = ""
    scope: list[str] = dataclass_field(default_factory=list[str])
    """no_overlap: the attributes of the scope fields and foreign keys."""

    def unique_constraint(self, prefix: str) -> str:
        """Return the `UniqueConstraint` of a unique rule. The migration uses `prefix="sa."`."""
        args = [*(f'"{c}"' for c in self.columns), f'name="{self.constraint}"']
        return f"{prefix}UniqueConstraint({', '.join(args)})"

    def check_lines(self) -> list[str]:
        """Return the statements of `check_rules` that check a compare or a `no_overlap` rule."""
        message = json.dumps(self.message)
        if self.kind == "compare":
            test = f'not compare(record.{self.field}, "{self.op}", record.{self.other})'
            status = 422
        else:
            scope = "[" + ", ".join(f'"{s}"' for s in self.scope) + "]"
            test = f'await overlaps(session, record, "{self.start}", "{self.end}", {scope})'
            status = 409
        return [f"if {test}:", f"    raise ProblemError({status}, {message})"]


@dataclass(slots=True)
class PyWorkflow:
    """A workflow on an enum field: the allowed changes of the field."""

    name: str
    id: str
    attr: str
    """The attribute of the field."""
    field: str
    """The name of the field in the API."""
    initial: str | None
    message: str | None
    transitions: list[tuple[str, str, str]]
    """The allowed changes: the value before, the value after, and the transition ID."""
    states: list[str]
    """The values of the field."""
    start: str
    """The state of the records of the tests: the initial state, or the first state of a change."""
    entity: str = ""
    """The name of the entity in snake case, for the factories of the tests."""

    @property
    def allowed_case(self) -> tuple[str, str] | None:
        """An allowed change from the start state, for the tests."""
        return next(((b, a) for b, a, _ in self.transitions if b == self.start), None)

    @property
    def forbidden_case(self) -> tuple[str, str] | None:
        """A change from the start state that no transition allows, for the tests."""
        allowed = {(b, a) for b, a, _ in self.transitions}
        return next(
            (
                (self.start, s)
                for s in self.states
                if s != self.start and (self.start, s) not in allowed
            ),
            None,
        )

    @property
    def other_state(self) -> str | None:
        """A state that is not the initial state, for the tests of a new record."""
        if self.initial is None:
            return None
        return next((s for s in self.states if s != self.initial), None)

    @property
    def constant(self) -> str:
        """The name of the module constant with the allowed changes."""
        return f"{self.name.upper()}_TRANSITIONS"

    def check_lines(self) -> list[str]:
        """Return the statements of `check_workflows` for the workflow."""
        args = [
            f'"{self.field}"',
            f'None if before is None else before["{self.attr}"]',
            f"record.{self.attr}",
            self.constant,
            "created=before is None",
            f"initial={json.dumps(self.initial) if self.initial is not None else 'None'}",
        ]
        if self.message is not None:
            args.append(f"message={json.dumps(self.message)}")
        return ["check_transition(", *(f"    {arg}," for arg in args), ")"]


@dataclass(slots=True)
class PyJoinTable:
    """A join table of a many-to-many relation."""

    name: str
    relation_id: str
    left_table: str
    left_column: str
    right_table: str
    right_column: str

    def model_columns(self) -> list[str]:
        """Return the `Column` lines of the join table in the model module."""
        return [
            call(
                "",
                "Column",
                [
                    f'"{column}"',
                    "Uuid()",
                    f'ForeignKey("{table}.id", ondelete="CASCADE")',
                    "primary_key=True",
                ],
                4,
                ",",
            )
            for column, table in (
                (self.left_column, self.left_table),
                (self.right_column, self.right_table),
            )
        ]

    def migration_lines(self) -> list[str]:
        """Return the arguments of `op.create_table` for the join table, after its name."""
        lines = [
            call("", "sa.Column", [f'"{c}"', "sa.Uuid()", "nullable=False"], 8, ",")
            for c in (self.left_column, self.right_column)
        ]
        for column, table in (
            (self.left_column, self.left_table),
            (self.right_column, self.right_table),
        ):
            lines.append(
                call(
                    "",
                    "sa.ForeignKeyConstraint",
                    [
                        f'["{column}"]',
                        f'["{table}.id"]',
                        f'name="fk_{self.name}_{column}_{table}"',
                        'ondelete="CASCADE"',
                    ],
                    8,
                    ",",
                )
            )
        lines.append(
            call(
                "",
                "sa.PrimaryKeyConstraint",
                [f'"{self.left_column}"', f'"{self.right_column}"', f'name="pk_{self.name}"'],
                8,
                ",",
            )
        )
        return lines


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
    slice: str
    """The slice of the entity of the operation."""
    protected: bool = False
    """True if the operation needs a signed-in user (the `auth` section)."""
    apis: list[str] = dataclass_field(default_factory=list[str])
    """The names of the third-party APIs that a custom operation calls."""
    owner_action: str | None = None
    """`read` or `change`, if an owner rule of a role can apply to the operation (ADR 0018)."""

    @property
    def custom(self) -> bool:
        return self.kind == "custom"

    @property
    def params_class(self) -> str:
        return pascal(self.name) + "Params"

    @property
    def has_id(self) -> bool:
        return "{id}" in self.path

    @property
    def summary(self) -> str:
        return self.name.replace("_", " ").capitalize()

    @property
    def returns_class(self) -> str | None:
        return f"{self.returns}Read" if self.returns else None

    def decorator(self) -> str:
        """Return the route decorator of the endpoint."""
        args = [f'"{self.path}"', f"status_code={self.status}"]
        args.append(f"responses=problem_responses({', '.join(str(e) for e in self.errors)})")
        args.append(f'summary="{self.summary}"')
        args.append(f'operation_id="{self.name}"')
        return call("@router.", self.method, args, 0)


@dataclass(slots=True)
class PyEntity:
    """An entity, as a vertical slice of the app."""

    name: str
    id: str
    snake: str
    slice: str
    """The name of the slice folder, for example `tasks`."""
    table: str
    """The name of the table, the slice unless `x-fastapi-table` sets it."""
    path: str
    """The URL prefix of the slice, for example `/tasks`."""
    label: str
    plural_label: str
    description: str | None
    fields: list[PyField]
    relations: list[PyRelation] = field(default_factory=list[PyRelation])
    operations: list[PyOperation] = field(default_factory=list[PyOperation])
    join_tables: list[PyJoinTable] = field(default_factory=list[PyJoinTable])
    computed: list[PyComputed] = field(default_factory=list[PyComputed])
    rules: list[PyRule] = field(default_factory=list[PyRule])
    workflows: list[PyWorkflow] = field(default_factory=list[PyWorkflow])
    guard: str = "current_user"
    """The dependency of the protected operations: `current_user`, or `check_access` with roles."""
    query: PyListQuery = field(default_factory=PyListQuery)
    """The filters and the sort keys of the list endpoints, from the fields and the views."""
    sign_up_fields: list[PyField] | None = None
    """The fields of the sign-up form, if the entity holds the users and `auth.sign_up` is set."""
    owner: PyRelation | None = None
    """The relation to the user entity of the owner rules of the entity, if a role has one."""

    @property
    def guard_module(self) -> str:
        return "access" if self.guard == "check_access" else "auth"

    app_entities: dict[str, PyEntity] = field(default_factory=dict[str, "PyEntity"], repr=False)
    """All entities of the app, to find the targets of the relations."""

    @property
    def params(self) -> list[PyField]:
        """The params of the custom operations of the entity."""
        return [p for op in self.operations if op.custom for p in op.params]

    @property
    def enum_fields(self) -> list[PyField]:
        """The fields and the params of type `enum`."""
        return [f for f in [*self.fields, *self.params] if f.enum is not None]

    @property
    def enums(self) -> list[PyEnum]:
        return [f.enum for f in self.enum_fields if f.enum is not None]

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
    def filters(self) -> list[PyField]:
        """The fields that a list endpoint can filter by equality."""
        return [f for f in self.fields if f.filterable]

    @property
    def sortable(self) -> list[PyField]:
        return [f for f in self.fields if f.sortable]

    @property
    def custom_operations(self) -> list[PyOperation]:
        return [o for o in self.operations if o.custom]

    @property
    def required_parents(self) -> list[PyRelation]:
        """The foreign keys that a test factory fills with a new record of the target."""
        return [r for r in self.fk_relations if r.required and r.target != self.name]

    @property
    def optional_fks(self) -> list[PyRelation]:
        """The foreign keys that a test factory leaves empty."""
        return [r for r in self.fk_relations if r not in self.required_parents]

    @property
    def exact_fields(self) -> list[PyField]:
        """The fields with JSON values that a test can compare with the response."""
        return [f for f in self.fields if f.exact]

    @property
    def has_unique_input(self) -> bool:
        """True if two records with the same input break a unique constraint."""
        return (
            any(f.unique for f in self.fields)
            or any(r.unique for r in self.fk_relations)
            or bool(self.unique_rules)
        )

    @property
    def unique_rules(self) -> list[PyRule]:
        return [r for r in self.rules if r.kind == "unique"]

    @property
    def check_rules(self) -> list[PyRule]:
        """The rules that the repository checks before it stores a record."""
        return [r for r in self.rules if r.kind != "unique"]

    def target(self, rel: PyRelation) -> PyEntity:
        return self.app_entities[rel.target]

    def repository_imports(self) -> str:
        """Return the import block of the repository module of the slice."""
        lines: set[str] = {
            "from typing import Any",
            "from uuid import UUID, uuid4",
            "from sqlalchemy.ext.asyncio import AsyncSession",
            "from app.core.errors import ProblemError",
            f"from app.features.{self.slice}.models import {self.name}",
            from_import(
                f"app.features.{self.slice}.schemas", {f"{self.name}Create", f"{self.name}Update"}
            ),
            f"from app.features.{self.slice}.validation_ext import validate",
        }
        core = {"commit"}
        if self.fk_relations:
            core.add("ensure_exists")
        if self.m2m_relations:
            core.add("load_all")
        lines.add(from_import("app.core.db", core))
        if self.workflows:
            lines.add("from app.core.workflows import check_transition")
        if self.owner is not None:
            lines.add("from sqlalchemy import Select")
        checks = {r.kind for r in self.check_rules}
        if checks:
            names = {"compare"} if "compare" in checks else set[str]()
            names |= {"overlaps"} if "no_overlap" in checks else set[str]()
            lines.add(from_import("app.core.rules", names))
        for rel in self.input_relations:
            target = self.target(rel)
            if target.name != self.name:
                lines.add(f"from app.features.{target.slice}.models import {target.name}")
        return import_block(lines)

    def list_imports(self, op: PyOperation | None = None) -> str:
        """Return the import block of a list operation of the entity."""
        query = self.query
        params = query.params
        types = {p.type.removeprefix("list[").removesuffix("]") for p in params}
        declarations = [p.declaration() for p in params]
        code = "\n".join([*(line for p in params for line in p.where_lines()), *declarations])
        code += "\n".join(k.entry() for k in query.sort_keys)
        pagination = {"Page", "PageQuery", "sort_order"}
        pagination |= {
            n for n in ("contains", "day_start", "lookup", "search_words") if n + "(" in code
        }
        owner = op is not None and op.owner_action is not None
        lines = {
            # Without sort keys, `SORTABLE` is an empty dict with a type.
            "from typing import Annotated" + ("" if query.sort_keys else ", Any"),
            "from fastapi import APIRouter, Depends, Query"
            if owner
            else "from fastapi import APIRouter, Query",
            "from pydantic import ConfigDict"
            + (", Field" if any("Field(" in d for d in declarations) else ""),
            "from sqlalchemy import func, " + ("or_, " if query.search else "") + "select",
            "from app.core.db import SessionDep",
            "from app.core.errors import problem_responses",
            from_import("app.core.pagination", pagination),
            f"from app.features.{self.slice}.schemas import {self.name}Read",
        }
        classes = {self.name} | {e.name for e in query.entities()}
        if query.aliases:
            # `aliased()` prepares the mappers: all models must be imported first.
            lines.add("from sqlalchemy.orm import aliased")
            lines.add(from_import("app.models", classes))
        else:
            for entity in [self, *query.entities()]:
                lines.add(f"from app.features.{entity.slice}.models import {entity.name}")
        if any(t.startswith("dt.") for t in types):
            lines.add("import datetime as dt")
        if "Decimal" in types:
            lines.add("from decimal import Decimal")
        if "UUID" in types or owner:
            lines.add("from uuid import UUID")
        enums: dict[str, set[str]] = {}
        for p in params:
            f = p.path.field
            if f is not None and f.enum is not None and f.enum.name in types:
                enums.setdefault(p.path.entity.slice, set()).add(f.enum.name)
        for slice_name, names in enums.items():
            lines.add(from_import(f"app.features.{slice_name}.enums", names))
        if owner:
            lines |= {
                "from app.core.access import owner_of",
                f"from app.features.{self.slice} import repository",
            }
        return import_block(lines)

    def router_imports(self) -> str:
        """Return the import block of the router module of the slice."""
        lines = {"from fastapi import APIRouter"}
        if any(o.protected for o in self.operations):
            lines |= {
                "from fastapi import APIRouter, Depends",
                f"from app.core.{self.guard_module} import {self.guard}",
            }
            lines.discard("from fastapi import APIRouter")
        if self.operations:
            lines.add(
                from_import(f"app.features.{self.slice}", {o.module for o in self.operations})
            )
        return import_block(lines)

    @property
    def not_null(self) -> list[str]:
        """The attributes that an update cannot set to null."""
        names = [f.attr for f in self.fields if f.required]
        return names + [r.fk_attr for r in self.fk_relations if r.required and r.fk_attr]

    def model_imports(self) -> str:
        """Return the import block of the models module of the slice."""
        types = {f.model_type for f in self.fields} | {c.type for c in self.computed}
        sa_types = {f.sa_type.split("(")[0] for f in self.fields if not f.enum}
        lines: set[str] = set()
        if any(t.startswith("dt.") for t in types):
            lines.add("import datetime as dt")
        if "Decimal" in types:
            lines.add("from decimal import Decimal")
        targets = {r.target for r in self.relations if r.target != self.name}
        typing = {"TYPE_CHECKING"} if targets else set[str]()
        if "Any" in types:
            typing.add("Any")
        if typing:
            lines.add(from_import("typing", typing))
        if self.fk_relations or self.m2m_relations or "UUID" in types:
            lines.add("from uuid import UUID")
        sqlalchemy = sa_types - set(_MIGRATION_TYPES)
        if self.fk_relations:
            sqlalchemy.add("ForeignKey")
        if self.join_tables:
            sqlalchemy |= {"Column", "ForeignKey", "Table", "Uuid"}
        if self.unique_rules:
            sqlalchemy.add("UniqueConstraint")
        if sqlalchemy:
            lines.add(from_import("sqlalchemy", sqlalchemy))
        orm = {"Mapped", "mapped_column"}
        if self.relations:
            orm.add("relationship")
        lines.add(from_import("sqlalchemy.orm", orm))
        core = {"Record"} | ({"Base"} if self.join_tables else set[str]())
        core |= sa_types & set(_MIGRATION_TYPES)
        field_enums = {f.enum.name for f in self.fields if f.enum is not None}
        core |= {"enum_type"} if field_enums else set[str]()
        lines.add(from_import("app.core.db", core))
        if self.computed:
            lines.add("from app.core import compute")
        if field_enums:
            lines.add(from_import(f"app.features.{self.slice}.enums", field_enums))
        block = import_block(lines)
        if targets:
            checks = sorted(
                f"    from app.features.{self.app_entities[t].slice}.models import {t}"
                for t in targets
            )
            block += "\n\nif TYPE_CHECKING:\n" + "\n".join(checks)
        return block

    @property
    def fk_columns(self) -> list[tuple[PyRelation, str]]:
        """The foreign key columns of the table, with their `sa.Column` in the migration."""
        return [
            (
                r,
                call(
                    "",
                    "sa.Column",
                    [f'"{r.fk}"', "sa.Uuid()", f"nullable={not r.required}"],
                    8,
                    ",",
                ),
            )
            for r in self.fk_relations
        ]

    def reject_null_call(self) -> str:
        """Return the statement of the update schema that rejects null for required fields."""
        return call("return ", "reject_null", ["self", *(f'"{n}"' for n in self.not_null)], 8)

    def schema_imports(self) -> str:
        """Return the import block of the schemas module of the slice."""
        types = {f.schema_type for f in [*self.fields, *self.params]}
        types |= {f.read_type for f in self.fields} | {c.type for c in self.computed}
        lines: set[str] = set()
        if any(t.startswith("dt.") for t in types):
            lines.add("import datetime as dt")
        if "Decimal" in types:
            lines.add("from decimal import Decimal")
        lines.add("from uuid import UUID")
        declarations = [f.declaration(m) for f in self.fields for m in ("create", "update", "read")]
        declarations += [p.declaration("create") for p in self.params]
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
        if self.sign_up_fields is not None:
            # The password of the sign-up schema has a minimum length.
            pydantic.add("Field")
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


@dataclass(frozen=True, slots=True)
class PyProvider:
    """An OpenID Connect provider of the sign-in (ADR 0020), with the names of its settings."""

    name: str
    id: str
    title: str
    issuer: str
    client_id_env: str
    client_secret_env: str
    scope: str
    """The scopes, separated by spaces."""
    username_claim: str
    create_users: bool
    default_role: str | None
    """With `create_users` and `access`: the role of a new user."""
    claims: list[tuple[PyField, str]]
    """With `create_users`: the fields of a new user, and the claims that give their values."""


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
    redis: bool = False
    """True if the rate limit can count in Redis (`RATE_LIMIT_STORE_URL`), for all replicas."""
    deploy: tuple[str, ...] = ("kubernetes",)
    """The deployment targets, each with its folder `deploy/<target>/`."""
    providers: list[PyProvider] = field(default_factory=list[PyProvider])

    def entity(self, name: str) -> PyEntity:
        return self.entities[name]

    def entity_order(self) -> list[PyEntity]:
        """The entities in source order."""
        return list(self.entities.values())

    @property
    def join_tables(self) -> list[PyJoinTable]:
        return [t for e in self.entities.values() for t in e.join_tables]

    @property
    def openapi_schemas(self) -> list[tuple[str, str]]:
        """The schemas that the endpoints use, with the ID of their element, in a fixed order."""
        found: dict[str, str] = {}
        for op in self.operations.values():
            entity = self.entities[op.entity]
            if op.kind in ("create", "read", "update", "list"):
                found[f"{entity.name}Read"] = entity.id
            if op.kind in ("create", "update"):
                found[f"{entity.name}{op.kind.capitalize()}"] = entity.id
            if op.custom and op.params:
                found[op.params_class] = op.id
            if op.returns:
                found[f"{op.returns}Read"] = self.entities[op.returns].id
        return sorted(found.items())

    def imports(self, lines: list[str]) -> str:
        """Return import lines in the groups and the order of the Ruff import sorter."""
        return import_block(set(lines))

    def from_import(self, module: str, names: list[str]) -> str:
        """Return a `from` import with the names in the order of the Ruff import sorter."""
        return from_import(module, set(names))

    def call(self, prefix: str, func: str, args: list[str], indent: int = 4) -> str:
        """Return a call on one line if it fits, else with one argument on each line."""
        return call(prefix, func, args, indent)

    def foreign_key_name(self, entity: PyEntity, rel: PyRelation) -> str:
        return f"fk_{entity.table}_{rel.fk}_{self.entities[rel.target].table}"

    def foreign_key_call(self, entity: PyEntity, rel: PyRelation) -> str:
        """Return the statement that adds a foreign key in the migration.

        The statement uses the batch mode of Alembic, because SQLite cannot
        add a constraint to a table. SQLite copies the table instead.
        """
        args = [
            f'"{self.foreign_key_name(entity, rel)}"',
            f'"{self.entities[rel.target].table}"',
            f'["{rel.fk}"]',
            '["id"]',
        ]
        if rel.on_delete:
            args.append(f'ondelete="{rel.on_delete}"')
        create = call("", "batch.create_foreign_key", args, 8)
        return f'with op.batch_alter_table("{entity.table}") as batch:\n        {create}'

    def drop_foreign_key_call(self, entity: PyEntity, rel: PyRelation) -> str:
        """Return the statement that drops a foreign key in the migration, in batch mode."""
        name = self.foreign_key_name(entity, rel)
        drop = call("", "batch.drop_constraint", [f'"{name}"', 'type_="foreignkey"'], 8)
        return f'with op.batch_alter_table("{entity.table}") as batch:\n        {drop}'

    @property
    def custom_operations(self) -> list[PyOperation]:
        return [o for o in self.operations.values() if o.custom]


def python_app(definition: AppDefinition) -> PyApp:
    """Return the model of the binding for an app definition.

    Raise GenerationError if two names of an entity give the same Python
    name, if two tables or URL prefixes have the same name, or if embedded
    relations form a cycle.
    """
    entities = {name: _entity(name, entity) for name, entity in definition.entities.items()}
    for py_entity in entities.values():
        py_entity.app_entities = entities
    for name, entity in definition.entities.items():
        _relations(definition, entities, name, entity)
    _computed(definition, entities)
    _rules(definition, entities)
    _workflows(definition, entities)
    _check_extensions(definition, entities)
    _check_embed_cycles(entities)
    auth = definition.auth
    operations: dict[str, PyOperation] = {}
    for name, operation in definition.operations.items():
        py_operation = _operation(name, operation, entities)
        py_operation.protected = auth is not None and name not in auth.public_operations
        operations[name] = py_operation
        entities[operation.entity].operations.append(py_operation)
    if auth is not None and auth.sign_up is not None:
        users = entities[auth.user_entity]
        by_name = {f.name: f for f in users.fields}
        users.sign_up_fields = [by_name[name] for name in auth.sign_up.fields]
    _owner_rules(definition, entities)
    for entity in entities.values():
        if definition.access is not None:
            entity.guard = "check_access"
        _place_routes(entity)
        _check_names(entity)
        entity.query = list_query(definition, entity)
    return PyApp(
        name=definition.app.name,
        package=snake(definition.app.name),
        title=definition.app.title,
        description=definition.app.description,
        entities=entities,
        operations=operations,
        redis=definition.app.extensions.get(RATE_LIMIT_STORE_KEY) == "redis",
        deploy=_deploy_targets(definition.app.extensions.get(DEPLOY_KEY)),
        providers=_providers(definition, entities),
    )


def _providers(definition: AppDefinition, entities: dict[str, PyEntity]) -> list[PyProvider]:
    """Return the OpenID Connect providers of the sign-in, in source order."""
    auth = definition.auth
    if auth is None:
        return []
    users = definition.entities[auth.user_entity]
    fields = {f.name: f for f in entities[auth.user_entity].fields}
    role = definition.access.role_field if definition.access is not None else None
    found: list[PyProvider] = []
    for name, provider in auth.providers.items():
        default_role = provider.default_role
        if default_role is None and role is not None and provider.create_users:
            value = users.fields[role].default
            default_role = str(value) if value is not None else None
        found.append(
            PyProvider(
                name=name,
                id=provider.id,
                title=provider.title or name.replace("_", " ").capitalize(),
                issuer=provider.issuer,
                client_id_env=provider.client_id_env,
                client_secret_env=provider.client_secret_env,
                scope=" ".join(provider.scopes),
                username_claim=provider.username_claim,
                create_users=provider.create_users,
                default_role=default_role,
                claims=[(fields[f], claim) for f, claim in provider.claims.items()],
            )
        )
    return found


def _owner_rules(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Give each entity with an owner rule its owner relation, and its operations their action."""
    if definition.access is None:
        return
    for role in definition.access.roles.values():
        for name, rule in role.records.items():
            entity = entities[name]
            entity.owner = next(r for r in entity.relations if r.name == rule.owner)
    for entity in entities.values():
        if entity.owner is None:
            continue
        for op in entity.operations:
            if op.protected:
                op.owner_action = "read" if op.kind in ("list", "read") else "change"


def _deploy_targets(value: object) -> tuple[str, ...]:
    """Return the targets of the deploy key in a fixed order (the key schema checks the names)."""
    if value is None:
        return ("kubernetes",)
    names = {value} if isinstance(value, str) else set(cast(list[str], value))
    return tuple(target for target in DEPLOY_TARGETS if target in names)


def _entity(name: str, entity: Entity) -> PyEntity:
    slice_name = snake(entity.plural_label) if entity.plural_label else plural(name)
    label = entity.label or " ".join(snake(name).split("_")).capitalize()
    table = str(entity.extensions.get(TABLE_KEY, slice_name))
    return PyEntity(
        name=name,
        id=entity.id,
        snake=snake(name),
        slice=slice_name,
        table=table,
        path=str(entity.extensions.get(PATH_KEY, "/" + kebab(slice_name))),
        label=label,
        plural_label=entity.plural_label or " ".join(slice_name.split("_")).capitalize(),
        description=entity.description,
        fields=[
            _field(field_name, f, f"{name}{pascal(field_name)}", table)
            for field_name, f in entity.stored_fields.items()
        ],
    )


def _computed(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Add the computed fields to the entities, and load the relations that they read."""
    for name, entity in definition.entities.items():
        for field_name, f in entity.computed_fields.items():
            assert f.computed is not None
            lines: list[str] = []
            result = _render_computed(entities, name, parse_expression(f.computed), lines)
            if f.type == "integer":
                result, type_ = f"compute.to_int({result})", "int"
            else:
                result = f"compute.round_to({result}, {f.scale})" if f.scale is not None else result
                type_ = "Decimal"
            entities[name].computed.append(
                PyComputed(
                    name=field_name,
                    attr=attribute(field_name),
                    id=f.id,
                    type=type_,
                    lines=[*lines, f"return {result}"],
                    source=f.computed,
                )
            )


def _rules(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Add the rules to the entities, with the Python names of their fields."""
    for name, entity in definition.entities.items():
        py_entity = entities[name]
        fields = {f.name: (f.attr, f.name) for f in py_entity.fields}
        fields |= {r.name: (str(r.fk_attr), str(r.fk)) for r in py_entity.fk_relations}

        def attr(member: str, fields: dict[str, tuple[str, str]] = fields) -> str:
            return fields[member][0]

        def column(member: str, fields: dict[str, tuple[str, str]] = fields) -> str:
            return fields[member][1]

        for rule_name, rule in entity.rules.items():
            py_rule = PyRule(name=rule_name, id=rule.id, kind=rule.kind, message="")
            if isinstance(rule, EntityCompareRule):
                py_rule.field, py_rule.other = attr(rule.field), attr(rule.other)
                py_rule.op, py_rule.message = rule.op, rule.message
                later = {"gt": rule.field, "gte": rule.field, "lt": rule.other, "lte": rule.other}
                if rule.op in later:
                    _later_sample(next(f for f in py_entity.fields if f.name == later[rule.op]))
            elif isinstance(rule, EntityUniqueRule):
                py_rule.columns = [column(m) for m in rule.fields]
                py_rule.constraint = f"uq_{py_entity.table}_{rule_name}"
                py_rule.message = rule.message or ""
            else:
                py_rule.start, py_rule.end = attr(rule.start), attr(rule.end)
                py_rule.scope = [attr(m) for m in rule.scope]
                py_rule.message = rule.message
            py_entity.rules.append(py_rule)


def _workflows(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Add the workflows to the entities.

    The test sample of the field is the initial state, or else the first
    state that a transition leaves, so that the tests create valid records.
    """
    for name, workflow in definition.workflows.items():
        py_entity = entities[workflow.entity]
        py_field = next(f for f in py_entity.fields if f.name == workflow.field)
        transitions = [
            (before, t.to, t.id) for t in workflow.transitions.values() for before in t.from_
        ]
        start = workflow.initial or transitions[0][0]
        py_field.sample = json.dumps(start)
        py_entity.workflows.append(
            PyWorkflow(
                name=name,
                id=workflow.id,
                attr=py_field.attr,
                field=py_field.name,
                initial=workflow.initial,
                message=workflow.message,
                transitions=transitions,
                states=[v for _, v in py_field.enum.members] if py_field.enum else [],
                start=start,
                entity=py_entity.snake,
            )
        )


def _later_sample(f: PyField) -> None:
    """Make the test sample of a date or a date-time field later than the samples of others.

    The other samples of the same `n` start at 00:00 (date-time) or in
    January (date), so that a compare rule `gt` holds in the tests.
    """
    if f.type == "datetime":
        f.sample = f.sample.replace(":00:00Z", ":30:00Z")
    elif f.type == "date":
        f.sample = f.sample.replace("2026-01-", "2026-02-")


def _render_computed(
    entities: dict[str, PyEntity], entity: str, expression: Expression, lines: list[str]
) -> str:
    """Add the statements of an expression to `lines`, and return the name of its value.

    Each statement computes one part of the expression in a local variable,
    so that the lines stay short.
    """

    def assign(code: str) -> str:
        var = f"v{len(lines) + 1}"
        lines.append(f"{var} = {code}")
        return var

    match expression:
        case Number(value):
            return f'Decimal("{value}")'
        case FieldRef(path):
            return assign(f"compute.num({_computed_path(entities, entity, path)})")
        case Call(function, args):
            values = [
                _computed_path(entities, entity, a.path) for a in args if isinstance(a, FieldRef)
            ]
            return assign(f"compute.{function}({', '.join(values)})")
        case Binary(op, left, right):
            a = _render_computed(entities, entity, left, lines)
            b = _render_computed(entities, entity, right, lines)
            return assign(f"compute.{_COMPUTE_OPS[op]}({a}, {b})")
        case Negate(operand):
            return assign(f"compute.neg({_render_computed(entities, entity, operand, lines)})")


def _computed_path(entities: dict[str, PyEntity], entity: str, path: str) -> str:
    """Return the Python expression of a field path of a computed field, of `self`."""
    current = entities[entity]
    attrs: list[str] = []
    segments = path.split(".")
    for segment in segments[:-1]:
        rel = next(r for r in current.relations if r.name == segment)
        rel.computed = True
        attrs.append(rel.attr)
        current = entities[rel.target]
    attrs.append(next(x.attr for x in current.fields if x.name == segments[-1]))
    return "compute.get(self, " + ", ".join(f'"{a}"' for a in attrs) + ")"


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


_MIGRATION_TYPES = {
    "JSON_TYPE": 'sa.JSON().with_variant(postgresql.JSONB(), "postgresql")',
    "Timestamp": "sa.DateTime(timezone=True)",
}
"""The column types of `app.core.db`, and their SQLAlchemy types in the migration.

The app types work on Postgres and on SQLite (the local database).
"""


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
            return "dt.datetime", "AwareDatetime", "Timestamp"
        case "uuid":
            return "UUID", "UUID", "Uuid"
        case "enum":
            assert enum is not None
            return enum.name, enum.name, f'enum_type({enum.name}, "{enum.constraint}")'
        case _:
            return "Any", "JsonValue", "JSON_TYPE"


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
            rel.fk_attr = attribute(f"{rel_name}_id")
            rel.fk = str(relation.extensions.get(COLUMN_KEY, f"{rel_name}_id"))
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
        name=_join_table_name(definition, owner, rel_name, relation),
        relation_id=relation.id,
        left_table=owner.table,
        left_column=left,
        right_table=target.table,
        right_column=right,
    )
    owner.join_tables.append(table)
    rel.secondary = table.name
    rel.local_column, rel.remote_column = left, right


def _join_table_name(
    definition: AppDefinition, owner: PyEntity, rel_name: str, relation: Relation
) -> str:
    """Return the name of a join table: `x-fastapi-table` of one of the two sides, or a default."""
    names = {relation.extensions.get(TABLE_KEY)}
    if relation.inverse is not None:
        other = definition.entities[relation.target].relations[relation.inverse]
        names.add(other.extensions.get(TABLE_KEY))
    names.discard(None)
    if len(names) > 1:
        raise GenerationError(
            f"The relation '{relation.id}' and its inverse set different values of "
            f"'{TABLE_KEY}'. Set the same value on the two sides, or on one side only."
        )
    return str(names.pop()) if names else f"{owner.slice}_{rel_name}"


def _check_extensions(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Raise GenerationError for a naming key on a relation that does not use it,
    or for two tables or two URL prefixes with the same name."""
    for name, entity in definition.entities.items():
        for rel in entities[name].relations:
            relation = entity.relations[rel.name]
            if COLUMN_KEY in relation.extensions and rel.side != "fk":
                raise GenerationError(
                    f"The relation '{relation.id}' has no foreign key column, so "
                    f"'{COLUMN_KEY}' has no effect. Set it on the other side of the relation."
                )
            if TABLE_KEY in relation.extensions and rel.side != "m2m":
                raise GenerationError(
                    f"The relation '{relation.id}' has no join table, so '{TABLE_KEY}' "
                    "has no effect. Use it on a many-to-many relation or on an entity."
                )
    tables: dict[str, str] = {}
    paths: dict[str, str] = {}
    for e in entities.values():
        for table, owner in [(e.table, e.id), *((t.name, t.relation_id) for t in e.join_tables)]:
            if table in tables:
                raise GenerationError(
                    f"'{tables[table]}' and '{owner}' both use the table name '{table}'. "
                    f"Set another name with '{TABLE_KEY}'."
                )
            tables[table] = owner
        if e.path in paths:
            raise GenerationError(
                f"'{paths[e.path]}' and '{e.id}' both use the URL prefix '{e.path}'. "
                f"Set another prefix with '{PATH_KEY}'."
            )
        paths[e.path] = e.id


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
        slice=entity.slice,
        apis=list(operation.apis),
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

    modules = {"enums", "models", "repository", "router", "schemas", "validation_ext"}
    for op in entity.operations:
        if op.module in modules or op.name in modules:
            raise GenerationError(
                f"The operation '{op.name}' has the name of a module of the slice "
                f"'{entity.slice}'. Give it another name."
            )
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
    apis = python_apis(definition)
    return {
        "py": python_app(definition),
        "py_apis": apis,
        "py_api_mocks_imports": mocks_imports(apis),
    }
