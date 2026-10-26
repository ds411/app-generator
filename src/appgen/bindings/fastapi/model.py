"""The app definition in the terms of the FastAPI binding.

The binding context gives this model to the templates as `py`. The model
gives each entity, field, relation, and operation the Python names, the
SQLAlchemy types, the Pydantic types, and the HTTP routes that the
templates write. The model reads only the definition, so it is
deterministic.
"""

import json
import math
import re
from dataclasses import dataclass, field
from dataclasses import field as dataclass_field
from decimal import Decimal
from typing import Any, cast

from appgen.bindings.fastapi.dashboards import TEST_TODAY, PyDashboard, python_dashboards
from appgen.bindings.fastapi.i18n import language_test
from appgen.bindings.fastapi.integrations import (
    mocks_imports,
    py_features,
    python_apis,
    python_connections,
)
from appgen.bindings.fastapi.jobs import TABLE as JOBS_TABLE
from appgen.bindings.fastapi.jobs import PyJob, python_jobs
from appgen.bindings.fastapi.lines import PyLines, python_lines
from appgen.bindings.fastapi.names import attribute, plural, singular
from appgen.bindings.fastapi.pysource import (
    LINE_LENGTH,
    call,
    from_import,
    import_block,
    literal,
    raise_problem,
    signature,
    string,
)
from appgen.bindings.fastapi.queries import PyListQuery, PySearchIndex, list_query
from appgen.bindings.fastapi.samples import PatternError, pattern_samples
from appgen.bindings.fastapi.seed import python_seed
from appgen.bindings.fastapi.totals import (
    PyTotal,
    TotalsTest,
    computed_sql,
    entity_totals,
    models_code,
    models_head,
    models_imports,
    totals_test,
)
from appgen.bindings.fastapi.webhooks import python_webhooks
from appgen.bindings.shared.i18n import i18n_plan
from appgen.dsl.access import RecordRule
from appgen.dsl.events import EVENT_NAMES
from appgen.dsl.expressions import (
    Binary,
    Call,
    Expression,
    FieldRef,
    Negate,
    Number,
    Total,
    date_paths,
    expression_paths,
    parse_expression,
)
from appgen.dsl.model import AppDefinition, Entity, Field, Operation, Relation
from appgen.dsl.rules import EntityCompareRule, EntityUniqueRule
from appgen.dsl.storage import FILE_TYPES, format_size, type_allows
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
SEARCH_KEY = "x-fastapi-search"
"""The extension key of the app that selects the search of the list endpoints."""
SEARCH_CONFIGS = {
    "ar": "arabic",
    "ca": "catalan",
    "da": "danish",
    "de": "german",
    "el": "greek",
    "en": "english",
    "es": "spanish",
    "eu": "basque",
    "fi": "finnish",
    "fr": "french",
    "ga": "irish",
    "hi": "hindi",
    "hu": "hungarian",
    "hy": "armenian",
    "id": "indonesian",
    "it": "italian",
    "lt": "lithuanian",
    "nb": "norwegian",
    "ne": "nepali",
    "nl": "dutch",
    "nn": "norwegian",
    "no": "norwegian",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sr": "serbian",
    "sv": "swedish",
    "ta": "tamil",
    "tr": "turkish",
    "yi": "yiddish",
}
"""The text search configuration of Postgres for each language (ISO 639-1)."""

_INT32 = 2**31 - 1
_FILE_SAMPLES = (
    ("image/png", "sample.png", "PNG"),
    ("application/pdf", "sample.pdf", 'b"%PDF-1.7\\n%%EOF\\n"'),
    ("text/plain", "sample.txt", 'b"A sample text."'),
    ("image/jpeg", "sample.jpg", 'b"\\xff\\xd8\\xff\\xe0 sample"'),
    ("image/gif", "sample.gif", 'b"GIF89a sample"'),
    ("image/webp", "sample.webp", 'b"RIFF\\x0c\\x00\\x00\\x00WEBPVP8 "'),
)
"""The files of the generated tests of the file fields: the media type, the name, and the
content as Python (`PNG` is a constant of the test module: an image of one pixel)."""
_OTHER_TYPES = ("text/html", "application/x-appgen-test", "image/x-appgen-test")
"""The media types of the generated tests of a type that a file field does not allow."""
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


@dataclass(frozen=True, slots=True)
class PySequence:
    """The database sequence of a field with `sequence`: the numbers of the new records."""

    id: str
    """The element ID, for example `entities.Invoice.fields.number.sequence`."""
    name: str
    """The name of the Postgres sequence, for example `invoices_number_seq`."""
    const: str
    """The module constant of the `Sequence`, for example `NUMBER_SEQUENCE`."""
    start: int
    table: str
    column: str
    prefix: str | None
    width: int | None
    """The least number of digits of a `string` field, else None for an `integer` field."""

    def declaration(self) -> str:
        """Return the declaration of the `Sequence` in the models module."""
        args = [f'"{self.name}"', f"start={self.start}", "metadata=Base.metadata"]
        return call(f"{self.const} = ", "Sequence", args)

    def default(self) -> str:
        """Return the `NextNumber` default of the column."""
        args = [self.const, f'"{self.table}"', f'"{self.column}"']
        if self.prefix:
            args.append(f'prefix="{self.prefix}"')
        if self.width is not None:
            args.append(f"width={self.width}")
        return f"NextNumber({', '.join(args)})"


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
    translatable: bool = False
    """True if the records have a value in each language (ADR 0026)."""
    sequence: PySequence | None = None
    """The sequence of the field: the database gives the value, and the inputs do not have it."""

    @property
    def aliased(self) -> bool:
        return self.attr != self.name

    @property
    def translations_attr(self) -> str:
        """The attribute of the values of the other languages, for example `title_translations`."""
        return f"{self.attr}_translations"

    @property
    def translations_name(self) -> str:
        """The column and the JSON name of the values of the languages of a translatable field."""
        return f"{self.name}_translations"

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
        if self.sequence is not None:
            args.append(f"default={self.sequence.default()}")
        return call(f"{self.attr}: Mapped[{type_}] = ", "mapped_column", args)

    def translations_column(self) -> str:
        """Return the model attribute of the values of the other languages (a JSON object)."""
        args = [f'"{self.translations_name}"'] if self.aliased else []
        args.append("JSON_TYPE")
        return call(
            f"{self.translations_attr}: Mapped[dict[str, str] | None] = ", "mapped_column", args
        )

    def translations_migration_column(self) -> str:
        """Return the `sa.Column` of the values of the other languages in the migration."""
        args = [f'"{self.translations_name}"', _MIGRATION_TYPES["JSON_TYPE"], "nullable=True"]
        return call("", "sa.Column", args, 8, ",")

    @property
    def text_rules(self) -> list[str]:
        """The rules of a value of a translatable field, as the arguments of `Field`."""
        return [f"{k}={v}" for k, v in self.constraints if k not in ("title", "description")]

    @property
    def text_type(self) -> str:
        """The type of a value of a translatable field in one language, for example `TitleText`."""
        return f"{pascal(self.name)}Text" if self.text_rules else "str"

    def text_alias(self) -> str:
        """Return the type alias of a value with the rules of the field, in the format of Ruff."""
        field_call = f"Field({', '.join(self.text_rules)})"
        line = f"{self.text_type} = Annotated[str, {field_call}]"
        if len(line) <= LINE_LENGTH:
            return line
        if len(f"    str, {field_call}") <= LINE_LENGTH:
            return f"{self.text_type} = Annotated[\n    str, {field_call}\n]"
        rules = "".join(f"        {rule},\n" for rule in self.text_rules)
        return f"{self.text_type} = Annotated[\n    str,\n    Field(\n{rules}    ),\n]"

    def translations_declaration(self, mode: str) -> str:
        """Return the declaration of the values of each language in a schema.

        The keys are the codes of the languages. In the input, a value has
        the rules of the field (`text_alias`), and null removes a translation.
        """
        default = "None"
        if self.aliased:
            default = f'Field(default=None, alias="{self.translations_name}")'
        if mode == "read":
            type_ = "dict[str, str] | None"
        else:
            type_ = f"dict[Language, {self.text_type} | None] | None"
        line = f"{self.translations_attr}: {type_} = {default}"
        if len(line) + 4 <= LINE_LENGTH:
            return line
        return f"{self.translations_attr}: (\n        {type_}\n    ) = {default}"

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


@dataclass(frozen=True, slots=True)
class PyFile:
    """A file field of an entity (ADR 0027): a JSON column, and the endpoints of its file."""

    name: str
    """The name in the definition: the column name and the JSON name."""
    attr: str
    """The Python attribute name."""
    id: str
    entity: str
    """The snake case name of the entity, for example `task`."""
    max_size: int
    """The largest file, in bytes."""
    media_types: tuple[str, ...]
    """The media types that the field allows, for example `image/*`. Empty: all types."""
    docs: list[tuple[str, str]]
    """The `title` and the `description` of the field, as the arguments of `pydantic.Field`."""

    @property
    def aliased(self) -> bool:
        return self.attr != self.name

    @property
    def rule(self) -> str:
        """The name of the module constant of the rule of the file, for example `SCREENSHOT`."""
        return constant(self.name)

    @property
    def path(self) -> str:
        """The path of the endpoints in the slice, for example `/{id}/screenshot`."""
        return "/{id}/" + kebab(self.name)

    @property
    def upload_operation(self) -> str:
        return f"upload_{self.entity}_{self.name}"

    @property
    def delete_operation(self) -> str:
        return f"delete_{self.entity}_{self.name}"

    @property
    def size_text(self) -> str:
        """The largest file as a short text, for example `5 MB`."""
        return format_size(self.max_size)

    @property
    def sample(self) -> tuple[str, str, str]:
        """A valid file for the tests: the name, the media type, and the content (Python)."""
        for media_type, name, content in _FILE_SAMPLES:
            if type_allows(self.media_types, media_type):
                return name, media_type, content
        media_type = self.media_types[0].replace("/*", "/x-sample")
        return "sample.bin", media_type, 'b"A sample file."'

    @property
    def rejected_type(self) -> str | None:
        """A media type that the field does not allow, for the tests, or None."""
        return next((t for t in _OTHER_TYPES if not type_allows(self.media_types, t)), None)

    def rule_call(self) -> str:
        """Return the constant of the rule of the file, for example `SCREENSHOT = FileRule(...)`."""
        args = [f"max_size={self.max_size}"]
        if self.media_types:
            args.append(f"types={_python_tuple(list[str | int | bool](self.media_types))}")
        return call(f"{self.rule} = ", "FileRule", args, 0)

    def column(self) -> str:
        """Return the declaration of the model attribute: the JSON value of the stored file."""
        args = [f'"{self.name}"'] if self.aliased else []
        args.append("JSON_TYPE")
        return call(f"{self.attr}: Mapped[StoredFile | None] = ", "mapped_column", args)

    def migration_column(self) -> str:
        """Return the `sa.Column` of the field in the migration."""
        args = [f'"{self.name}"', _MIGRATION_TYPES["JSON_TYPE"], "nullable=True"]
        return call("", "sa.Column", args, 8, ",")

    def declaration(self) -> str:
        """Return the declaration of the field in the read schema."""
        args = [f'alias="{self.name}"'] if self.aliased else []
        args += [f"{k}={v}" for k, v in self.docs]
        return _declare(self.attr, "FileRead | None", None, args)


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
    hidden: bool = False
    """True if a record rule can hide the embedded target (ADR 0025): the read allows None."""
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
                optional = self.nullable or self.hidden
                lines.append(f"{self.attr}: {target}" + (" | None" if optional else ""))
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
    expression: Expression | None = None
    totals: dict[str, PyTotal] = field(default_factory=dict[str, PyTotal])
    """The totals of the relations in the expression, by their text (ADR 0034)."""
    sql: str | None = None
    """The SQL form of a field with totals, for the sort and the filters of the lists, or None."""

    @property
    def paths(self) -> list[str]:
        """The field paths of the record in the expression."""
        return list(expression_paths(self.expression)) if self.expression is not None else []

    @property
    def testable(self) -> bool:
        """True if the expression has totals, numbers, and stored fields of the record only.

        The generated tests give these fields known values.
        """
        if self.expression is None or not self.totals or any(date_paths(self.expression)):
            return False
        return all("." not in path for path in self.paths)

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
    translated: bool = False
    """True if the app has translations: the message goes through `t` (ADR 0010)."""

    def unique_constraint(self, prefix: str) -> str:
        """Return the `UniqueConstraint` of a unique rule. The migration uses `prefix="sa."`."""
        args = [*(f'"{c}"' for c in self.columns), f'name="{self.constraint}"']
        return f"{prefix}UniqueConstraint({', '.join(args)})"

    def check_lines(self) -> list[str]:
        """Return the statements of `check_rules` that check a compare or a `no_overlap` rule."""
        if self.kind == "compare":
            test = f'not compare(record.{self.field}, "{self.op}", record.{self.other})'
            status = 422
        else:
            scope = "[" + ", ".join(f'"{s}"' for s in self.scope) + "]"
            test = f'await overlaps(session, record, "{self.start}", "{self.end}", {scope})'
            status = 409
        statement = raise_problem(status, self.message, {}, indent=8, translated=self.translated)
        first, *rest = statement.splitlines()
        # The template indents each line by 4 spaces.
        return [f"if {test}:", f"    {first}", *(line[4:] for line in rest)]


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
class PyEvent:
    """An event of an entity, or a transition with `run` (ADR 0031).

    The repository runs the custom operation of the event after the
    change, in the transaction of the change.
    """

    kind: str
    """`created`, `changed`, `deleted`, or `transition`."""
    id: str
    operation: PyOperation
    attrs: list[str] = field(default_factory=list[str])
    """`changed`: the attributes of the fields that the event watches."""
    fields: list[str] | None = None
    """`changed`: the names of `fields`, or None for all stored fields."""
    workflow: PyWorkflow | None = None
    """`transition`: the workflow of the transition."""
    before: list[str] = field(default_factory=list[str])
    """`transition`: the states before the transition."""
    after: str = ""
    """`transition`: the state after the transition."""
    name: str = ""
    """The name of the event, or of the transition."""

    def summary(self, entity: str) -> str:
        """Return the change that runs the operation, for the README."""
        if self.kind == "created":
            return f"A new {entity}"
        if self.kind == "deleted":
            return f"The delete of a {entity}"
        if self.kind == "changed":
            fields = ", ".join(f"`{name}`" for name in self.fields or [])
            return f"A change of {fields} of a {entity}" if fields else f"A change of a {entity}"
        assert self.workflow is not None
        return f"The transition `{self.name}` of the workflow `{self.workflow.name}`"

    @property
    def module(self) -> str:
        """The extension module of the operation, for example `notify_owner_ext`."""
        return f"{self.operation.name}_ext"

    @property
    def function(self) -> str:
        """The operation in its module, for example `notify_owner_ext.notify_owner`."""
        return f"{self.module}.{self.operation.name}"

    def call(self, indent: int) -> str:
        """Return the statement that runs the operation on `record`, without params."""
        args = ["session", self.function, "session", "record"]
        if self.operation.params:
            args.append(f"{self.operation.params_class}()")
        return call("await ", "run_event", args, indent)

    def condition(self) -> str:
        """Return the condition of a transition: the state after it, and a state before it."""
        assert self.workflow is not None
        attr = self.workflow.attr
        before = (
            f'before["{attr}"] == {string(self.before[0])}'
            if len(self.before) == 1
            else f'before["{attr}"] in {_python_tuple(list[str | int | bool](self.before))}'
        )
        return f"record.{attr} == {string(self.after)} and {before}"


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
class PyOwnerPath:
    """The owner of the records of an entity with record rules (ADR 0025): a path of relations.

    Each step is a many-to-one or a many-to-many relation. The last step
    goes to the user entity. A record belongs to each user at the end of
    the path.
    """

    path: str
    """The path in the definition, for example `project.team.members`."""
    steps: list[tuple[PyEntity, PyRelation]]
    """The entity and the relation of each step, from the entity of the rules to the users."""

    @property
    def ids(self) -> list[str]:
        """The element IDs of the relations of the path."""
        return [rel.id for _, rel in self.steps]

    @property
    def direct(self) -> PyRelation | None:
        """The relation of a path with one many-to-one step, else None."""
        if len(self.steps) == 1 and self.steps[0][1].side == "fk":
            return self.steps[0][1]
        return None

    def models(self, entity: PyEntity) -> list[PyEntity]:
        """Return the other models that the condition of the path uses, in path order."""
        found = [e for e, _ in self.steps[1:]]
        last_entity, last = self.steps[-1]
        if last.side == "m2m":
            found.append(last_entity.target(last))
        unique = {e.name: e for e in found if e.name != entity.name}
        return list(unique.values())

    def condition(self, prefix: str, user: str, indent: int = 4) -> str:
        """Return `<prefix><condition>`: the records of a user, as SQLAlchemy `EXISTS` subqueries.

        A many-to-one step is `has()`, and a many-to-many step is `any()`.
        The last many-to-one step compares its foreign key with the user.
        """
        return self._condition(0, prefix, user, indent)

    def _condition(self, index: int, prefix: str, user: str, indent: int) -> str:
        entity, rel = self.steps[index]
        if index == len(self.steps) - 1:
            if rel.side == "fk":
                return f"{prefix}{entity.name}.{rel.fk_attr} == {user}"
            inner = f"{entity.target(rel).name}.id == {user}"
        else:
            inner = self._condition(index + 1, "", user, indent + 4)
        method = "has" if rel.side == "fk" else "any"
        return _nested_call(prefix, f"{entity.name}.{rel.attr}.{method}", inner, indent)

    def owner_lines(self, user: str) -> list[str]:
        """Return the statements of a test that store the records of the path for a user.

        The last statement returns the values of a new record that make it
        belong to the user, for example `{"project_id": str(project.id)}`.
        """
        lines: list[str] = []
        current = user
        names: set[str] = set()
        for index in range(len(self.steps) - 1, 0, -1):
            entity, rel = self.steps[index]
            var = entity.snake if entity.snake not in names else f"{entity.snake}_{index}"
            names.add(var)
            lines.append(f"{var} = await make_{entity.snake}(session, {_link(rel, current)})")
            current = f"str({var}.id)"
        rel = self.steps[0][1]
        key = rel.fk_attr if rel.side == "fk" else rel.ids_field
        value = current if rel.side == "fk" else f"[{current}]"
        lines.append(f'return {{"{key}": {value}}}')
        return lines


def _varies(f: PyField) -> bool:
    """Return true if the test sample of a field has another value for the next `n`."""
    return re.search(r"\bn\b", f.sample) is not None


def _python_tuple(values: list[str | int | bool]) -> str:
    """Return a tuple of literal values as Python source, for example `("open",)`."""
    items = [string(v) if isinstance(v, str) else repr(v) for v in values]
    return f"({items[0]},)" if len(items) == 1 else f"({', '.join(items)})"


def _braces(prefix: str, items: list[str], indent: int) -> str:
    """Return `<prefix>{<items>}` on one line if it fits, else with one item on each line."""
    one_line = f"{prefix}{{{', '.join(items)}}}"
    if indent + len(one_line) + 1 <= LINE_LENGTH:
        return one_line
    pad = " " * indent
    inner = "".join(f"{pad}    {item},\n" for item in items)
    return f"{prefix}{{\n{inner}{pad}}}"


def _link(rel: PyRelation, value: str) -> str:
    """Return the keyword argument of a factory that links a record to the record of an ID."""
    if rel.side == "fk":
        return f"{rel.fk_attr}={value}"
    return f"{rel.ids_field}=[{value}]"


def _nested_call(prefix: str, func: str, arg: str, indent: int) -> str:
    """Return `<prefix><func>(<arg>)` on one line if it fits, else with the argument below."""
    one_line = f"{prefix}{func}({arg})"
    if "\n" not in arg and indent + len(one_line) <= LINE_LENGTH:
        return one_line
    pad = " " * indent
    return f"{prefix}{func}(\n{pad}    {arg},\n{pad})"


@dataclass(slots=True)
class PyRuleTest:
    """The generated test of a record rule of a role (ADR 0025)."""

    role: str
    id: str
    """The element ID of the rule."""
    entity: PyEntity
    reads: bool
    """True if the rule applies to the lists and the reads."""
    owner: bool
    """True if the rule has an owner: the records of another user are out of the scope."""
    inside: str
    """The values of the conditions in the scope, as a Python dict of JSON values."""
    outside: list[str]
    """For each condition with a value out of the scope: the values, as a Python dict."""
    patch: str | None
    """A change of a record in the scope that moves it out of the scope, as a Python dict."""
    ops: dict[str, PyOperation]
    """The operations of the entity that the role may call, by kind."""

    @property
    def name(self) -> str:
        return f"{self.role}_to_its_{self.entity.slice}"


@dataclass(slots=True)
class PyEmbedTest:
    """The generated test of a record rule on an embedded relation (ADR 0025)."""

    role: str
    entity: PyEntity
    """The entity that embeds the records."""
    relation: PyRelation
    """The embedded relation."""
    read: PyOperation
    """The read operation of the entity."""
    values: str
    """The values of a record of the entity in the scope of the role, as a Python dict."""
    inside: str
    """The values of an embedded record in the scope, as a Python dict."""
    outside: str
    """The values of an embedded record out of the scope, as a Python dict."""

    @property
    def target(self) -> PyEntity:
        return self.entity.target(self.relation)

    @property
    def link(self) -> str:
        """The key of the input of the target that refers to the record, for a `back` relation."""
        inverse = next(r for r in self.target.relations if r.name == self.relation.back_populates)
        return str(inverse.fk_attr)


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
    scope_action: str | None = None
    """`read` or `change`, if a record rule of a role can apply to the operation (ADR 0025)."""
    lines: list[PyLines] = dataclass_field(default_factory=list[PyLines])
    """The lines that a create or an update operation writes with the record (ADR 0035)."""

    @property
    def custom(self) -> bool:
        return self.kind == "custom"

    def line_imports(self) -> list[str]:
        """Return the imports of the schemas of the items of the lines of other slices."""
        schemas: dict[str, set[str]] = {}
        for ln in self.lines:
            if ln.target.slice != self.slice:
                module = f"app.features.{ln.target.slice}.schemas"
                schemas.setdefault(module, set()).add(ln.item_class)
        return [from_import(module, names) for module, names in sorted(schemas.items())]

    @property
    def own_line_items(self) -> list[str]:
        """The schemas of the items of the lines in the slice of the operation."""
        return [ln.item_class for ln in self.lines if ln.target.slice == self.slice]

    @property
    def input_class(self) -> str:
        """The schema of the body of a create or an update operation.

        With lines, the module of the operation has its own schema: the input of
        the record and the lines.
        """
        if self.lines:
            return pascal(self.name) + "Input"
        return self.entity + ("Create" if self.kind == "create" else "Update")

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
    """The stored fields without the file fields."""
    files: list[PyFile] = field(default_factory=list[PyFile])
    """The file fields (ADR 0027)."""
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
    scoped: bool = False
    """True if a record rule of a role names the entity (ADR 0018, ADR 0025)."""
    owner_path: PyOwnerPath | None = None
    """The owner path of the record rules of the entity, if a rule has `owner`."""
    hides: list[PyRelation] = field(default_factory=list[PyRelation])
    """The embedded relations whose records a record rule can hide, also in a nested embed."""
    translated: bool = False
    """True if the app has translations: the messages go through `t` (ADR 0010)."""
    full_text: bool = False
    """True if `q` uses the full-text search of Postgres (`x-fastapi-search: fulltext`)."""
    events: list[PyEvent] = field(default_factory=list[PyEvent])
    """The events and the transitions with `run` (ADR 0031): created, changed, deleted, the
    transitions."""
    totals: list[PyTotal] = field(default_factory=list[PyTotal])
    """The totals of the relations that the computed fields read: column properties (ADR 0034)."""
    totals_test: TotalsTest | None = None
    """The generated tests of the totals, or None."""
    lines: list[PyLines] = field(default_factory=list[PyLines])
    """The lines of the records that the operations write (ADR 0035): the repository has a
    function for each."""
    line_items: list[PyLines] = field(default_factory=list[PyLines])
    """The lines of other entities whose records are records of this entity: the schemas
    have an item for each, and the repository has `change` and `remove`."""

    @property
    def guard_module(self) -> str:
        return "access" if self.guard == "check_access" else "auth"

    @property
    def search_index(self) -> PySearchIndex | None:
        """The GIN index of the full-text search of `q` (`x-fastapi-search: fulltext`), or None."""
        return self.query.search_index(self)

    @property
    def owner(self) -> PyRelation | None:
        """The direct owner: a create sets it to the user, and a change keeps it (ADR 0018)."""
        return self.owner_path.direct if self.owner_path is not None else None

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
    def input_fields(self) -> list[PyField]:
        """The fields of the inputs: all fields except the fields with a sequence."""
        return [f for f in self.fields if f.sequence is None]

    @property
    def sequences(self) -> list[PySequence]:
        """The sequences of the fields with `sequence`."""
        return [f.sequence for f in self.fields if f.sequence is not None]

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
    def file_permission(self) -> PyOperation | None:
        """The operation whose permission the endpoints of the files need (ADR 0027).

        It is the update operation of the entity, else its create operation.
        Without both, the files have no endpoints: only the seed sets them.
        """
        for kind in ("update", "create"):
            found = next((op for op in self.operations if op.kind == kind), None)
            if found is not None:
                return found
        return None

    @property
    def file_endpoints(self) -> bool:
        """True if the slice has the endpoints of its files: `files.py`."""
        return bool(self.files) and self.file_permission is not None

    @property
    def file_scope(self) -> bool:
        """True if the endpoints of the files use the record rules of a change (ADR 0025)."""
        permission = self.file_permission
        return permission is not None and permission.protected and (self.scoped or bool(self.hides))

    def files_statement(self) -> str:
        """Return the statement of the repository that keeps the files of a record to delete."""
        items = [f"record.{f.attr}" for f in self.files]
        line = f"files = [{', '.join(items)}]"
        if 4 + len(line) <= LINE_LENGTH:
            return line
        return "files = [\n" + "".join(f"        {item},\n" for item in items) + "    ]"

    def file_imports(self) -> str:
        """Return the import block of the module of the endpoints of the files."""
        lines = {
            "from uuid import UUID",
            from_import(
                "fastapi",
                {"APIRouter", "UploadFile"} | ({"Depends"} if self.file_scope else set[str]()),
            ),
            "from app.core.db import SessionDep",
            "from app.core.errors import problem_responses",
            "from app.core.storage import FileRule, StorageDep, replace_file, upload",
            f"from app.features.{self.slice} import repository",
            f"from app.features.{self.slice}.schemas import {self.name}Read",
        }
        if self.file_scope:
            lines.add("from typing import Annotated")
            lines.add("from app.core.access import RecordScope, scope_of")
        return import_block(lines)

    @property
    def translatable(self) -> list[PyField]:
        """The translatable fields: the records have a value in each language (ADR 0026)."""
        return [f for f in self.fields if f.translatable]

    @property
    def translatable_names(self) -> str:
        """The attributes of the translatable fields, as the arguments of a call."""
        return ", ".join(f'"{f.attr}"' for f in self.translatable)

    @property
    def required_translatable(self) -> list[PyField]:
        """The required translatable fields: the default language must keep a value."""
        return [f for f in self.translatable if f.required]

    @property
    def translations_query(self) -> bool:
        """True if the reads take `translations=all`: the read schema has translatable fields.

        The read schema has the translatable fields of the entity, and of
        the records that it embeds.
        """
        return bool(self.translatable) or any(
            self.target(r).translatable for r in self.embedded if r.target != self.name
        )

    def router_dependencies(self, op: PyOperation) -> list[str]:
        """Return the dependencies of an operation in the router of the slice.

        A protected operation needs the user. An operation that returns a
        record with translatable fields, except a list, takes the query
        parameter `translations` (ADR 0026). A list declares it in its query.
        """
        dependencies = [f"Depends({self.guard})"] if op.protected else []
        returns = op.returns if op.custom else self.name if op.kind != "delete" else None
        if op.kind != "list" and returns and self.app_entities[returns].translations_query:
            dependencies.append("Depends(translations_query)")
        return dependencies

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
        return [f for f in self.input_fields if f.exact]

    @property
    def has_unique_input(self) -> bool:
        """True if two records with the same input break a unique constraint."""
        return (
            any(f.unique for f in self.input_fields)
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

    @property
    def created_event(self) -> PyEvent | None:
        return next((e for e in self.events if e.kind == "created"), None)

    @property
    def changed_event(self) -> PyEvent | None:
        return next((e for e in self.events if e.kind == "changed"), None)

    @property
    def deleted_event(self) -> PyEvent | None:
        return next((e for e in self.events if e.kind == "deleted"), None)

    @property
    def update_events(self) -> list[PyEvent]:
        """The events of an update, in the order of the runs: the transitions, then `changed`."""
        changed = self.changed_event
        return [e for e in self.events if e.kind == "transition"] + ([changed] if changed else [])

    @property
    def before_attrs(self) -> list[str]:
        """The attributes that an update reads before the change: workflows and `changed`."""
        attrs = [w.attr for w in self.workflows]
        changed = self.changed_event
        for attr in changed.attrs if changed else []:
            if attr not in attrs:
                attrs.append(attr)
        return attrs

    def before_code(self) -> str:
        """Return the statement of `update` that keeps the values before the change."""
        return _braces("before = ", [f'"{a}": record.{a}' for a in self.before_attrs], 4)

    def changed_constant_code(self) -> str:
        """Return the constant with the attributes that the event `changed` watches."""
        changed = self.changed_event
        assert changed is not None
        return literal(changed.attrs, "CHANGED_FIELDS = ")

    def event_import(self, events: list[PyEvent]) -> str:
        """Return the import of the extension modules of the operations of some events."""
        return from_import(f"app.features.{self.slice}", {e.module for e in events})

    def event_test_changes(self) -> list[str]:
        """The fields of a change that runs `changed` in the tests, or none if no change can.

        The tests change all fields to the values of other valid input,
        so that the rules of the entity hold. The workflow fields keep
        their state.
        """
        changed = self.changed_event
        if changed is None:
            return []
        fields = [f for f in self._test_fields() if f.attr not in self._workflow_attrs()]
        if not any(f.attr in changed.attrs and _varies(f) for f in fields):
            return []
        return [f.name for f in fields]

    def event_test_others(self) -> list[str]:
        """The fields of a change that does not run `changed` with `fields`, for the tests.

        They are the other fields that the rules of the entity do not read.
        """
        changed = self.changed_event
        if changed is None or len(changed.attrs) == len(self.fields):
            return []
        ruled = {a for r in self.rules for a in (r.field, r.other, r.start, r.end, *r.scope)}
        return [
            f.name
            for f in self._test_fields()
            if f.attr not in changed.attrs
            and f.attr not in ruled
            and f.attr not in self._workflow_attrs()
            and _varies(f)
        ]

    @property
    def event_operations(self) -> list[PyOperation]:
        """The operations of the events, each one time, in the order of the events."""
        found: dict[str, PyOperation] = {}
        for event in self.events:
            found.setdefault(event.operation.name, event.operation)
        return list(found.values())

    @property
    def event_hooks(self) -> list[str]:
        """The functions of the repository that run the events."""
        hooks = [("on_created", self.created_event), ("on_deleted", self.deleted_event)]
        hooks.insert(1, ("on_changed", self.update_events[0] if self.update_events else None))
        return [name for name, event in hooks if event is not None]

    def event_test_field(self) -> PyField:
        """A field that the change of the test of `changed` changes, and the event watches."""
        changed = self.changed_event
        assert changed is not None
        names = self.event_test_changes()
        return next(
            f for f in self.fields if f.name in names and f.attr in changed.attrs and _varies(f)
        )

    def transition_calls(self, event: PyEvent) -> list[str]:
        """The operations that the test of a transition expects, in order.

        They are the operations of the transitions of the same change, and
        of `changed` if it watches the field of the workflow.
        """
        assert event.workflow is not None
        before, attr = event.before[0], event.workflow.attr
        names = [
            e.operation.name
            for e in self.update_events
            if e.kind == "transition"
            and e.workflow is event.workflow
            and before in e.before
            and e.after == event.after
        ]
        changed = self.changed_event
        if changed is not None and attr in changed.attrs:
            names.append(changed.operation.name)
        return names

    @property
    def loop_event(self) -> PyEvent | None:
        """The event of the test that a change in an operation starts no event."""
        if self.created_event or self.deleted_event:
            return self.created_event or self.deleted_event
        return self.changed_event if self.event_test_changes() else None

    @property
    def event_test_sets_state(self) -> bool:
        """True if a test of a transition sets the state of a record in the database first."""
        return any(e.workflow is not None and e.before[0] != e.workflow.start for e in self.events)

    def event_test_imports(self) -> str:
        """Return the import block of the tests of the events."""
        sqlalchemy = {"func", "select"} | ({"update"} if self.event_test_sets_state else set[str]())
        schemas = {f"{self.name}Create"} if self.created_event else set[str]()
        if self.update_events:
            schemas.add(f"{self.name}Update")
        factories = {f"make_{self.snake}"}
        if self.created_event or self.event_test_changes():
            factories.add(f"{self.snake}_input")
        lines = {
            "from collections.abc import Awaitable, Callable",
            "from typing import Any",
            "from uuid import UUID",
            "import pytest",
            from_import("sqlalchemy", sqlalchemy),
            "from sqlalchemy.ext.asyncio import AsyncSession",
            from_import(
                f"app.features.{self.slice}",
                {f"{op.name}_ext" for op in self.event_operations} | {"repository"},
            ),
            f"from app.features.{self.slice}.models import {self.name}",
            from_import("tests.factories", factories),
        }
        if schemas:
            lines.add(from_import(f"app.features.{self.slice}.schemas", schemas))
        if self.files and self.deleted_event:
            lines |= {"from pathlib import Path", "from app.core.storage import FolderStorage"}
        return import_block(lines)

    def _test_fields(self) -> list[PyField]:
        return [f for f in self.fields if not f.translatable and f.type not in ("file", "image")]

    def _workflow_attrs(self) -> set[str]:
        return {w.attr for w in self.workflows}

    def repository_imports(self) -> str:
        """Return the import block of the repository module of the slice."""
        lines: set[str] = {
            "from typing import Any",
            "from uuid import UUID, uuid4",
            "from sqlalchemy.ext.asyncio import AsyncSession",
            "from app.core.errors import ProblemError",
            f"from app.features.{self.slice}.models import {self.name}",
            from_import(
                f"app.features.{self.slice}.schemas",
                {f"{self.name}Create", f"{self.name}Update"}
                | ({f"{self.name}Read"} if self.hides else set[str]())
                | {e.operation.params_class for e in self.events if e.operation.params}
                | {ln.item_class for ln in self.lines if ln.target.name == self.name},
            ),
            f"from app.features.{self.slice}.validation_ext import validate",
        }
        core = {"commit"} | ({"flush"} if self.scoped or self.events or self.lines else set[str]())
        if self.events:
            core.add("run_event")
        if self.fk_relations:
            core.add("ensure_exists")
        if self.m2m_relations:
            core.add("load_all")
        lines.add(from_import("app.core.db", core))
        if self.workflows:
            lines.add("from app.core.workflows import check_transition")
        sqlalchemy = {"select"} if self.lines else set[str]()
        if self.scoped:
            sqlalchemy |= {"Select", "select"}
            if self.owner_path:
                sqlalchemy.add("ColumnElement")
            lines.add("from app.core.access import RecordScope")
        if sqlalchemy:
            lines.add(from_import("sqlalchemy", sqlalchemy))
        if self.scoped or self.lines:
            lines.add("from collections.abc import Sequence")
        line_schemas: dict[str, set[str]] = {}
        for ln in self.lines:
            target = ln.target
            if target.name != self.name:
                module = f"app.features.{target.slice}"
                lines.add(f"from {module} import repository as {target.snake}_repository")
                lines.add(f"from {module}.models import {target.name}")
                line_schemas.setdefault(f"{module}.schemas", set()).update(
                    {ln.item_class, f"{target.name}Create", f"{target.name}Update"}
                )
        lines |= {from_import(module, names) for module, names in line_schemas.items()}
        if self.hides:
            lines.add("from collections.abc import Sequence")
            lines.add("from app.core.access import RecordScope")
            for rel in self.hides:
                target = self.target(rel)
                module = f"app.features.{target.slice}"
                lines.add(f"from {module} import repository as {target.snake}_repository")
        if self.owner_path is not None:
            for model in self.owner_path.models(self):
                lines.add(f"from app.features.{model.slice}.models import {model.name}")
        if self.files:
            lines.add("from app.core.storage import Storage, delete_files")
        i18n = {"t"} if self.translated else set[str]()
        if self.translatable:
            i18n.add("store_translations")
        if i18n:
            lines.add(from_import("app.core.i18n", i18n))
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
        search = {
            n
            for n in ("full_text", "matches", "search_rank", "search_vector", "web_query")
            if n + "(" in code
        }
        owner = op is not None and op.scope_action is not None
        typing = {"Annotated"} | ({"Literal"} if self.translations_query else set[str]())
        # Without sort keys, `SORTABLE` is an empty dict with a type.
        typing |= set[str]() if query.sort_keys else {"Any"}
        lines = {
            from_import("typing", typing),
            "from fastapi import APIRouter, Depends, Query"
            if owner
            else "from fastapi import APIRouter, Query",
            "from pydantic import ConfigDict"
            + (
                ", Field"
                if self.translations_query or any("Field(" in d for d in declarations)
                else ""
            ),
            "from sqlalchemy import func, " + ("or_, " if query.search else "") + "select",
            "from app.core.db import SessionDep",
            "from app.core.errors import problem_responses",
            from_import("app.core.pagination", pagination),
            f"from app.features.{self.slice}.schemas import {self.name}Read",
        }
        if search:
            lines.add(from_import("app.core.search", search))
        classes = {self.name} | {e.name for e in query.entities()}
        if query.aliases or self.totals:
            # `aliased()` prepares the mappers, and `app.models` adds the totals (ADR 0034):
            # all models must be imported first.
            if query.aliases:
                lines.add("from sqlalchemy.orm import aliased")
            lines.add(from_import("app.models", classes))
        else:
            for entity in [self, *query.entities()]:
                lines.add(f"from app.features.{entity.slice}.models import {entity.name}")
        if any(t.startswith("dt.") for t in types):
            lines.add("import datetime as dt")
        if "Decimal" in types:
            lines.add("from decimal import Decimal")
        if "UUID" in types:
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
                "from app.core.access import RecordScope, scope_of",
                f"from app.features.{self.slice} import repository",
            }
        if self.translations_query:
            lines.add("from app.core.i18n import TRANSLATIONS, show_translations")
        return import_block(lines)

    def file_dependencies(self) -> list[str]:
        """Return the dependencies of the endpoints of the files in the router of the slice.

        They need the user of the operation whose permission they need, and
        they return the record, as a change does.
        """
        permission = self.file_permission
        if permission is None:
            return []
        dependencies = [f"Depends({self.guard})"] if permission.protected else []
        if self.translations_query:
            dependencies.append("Depends(translations_query)")
        return dependencies

    def router_imports(self) -> str:
        """Return the import block of the router module of the slice."""
        lines = {"from fastapi import APIRouter"}
        dependencies = {d for o in self.operations for d in self.router_dependencies(o)}
        dependencies |= set(self.file_dependencies() if self.file_endpoints else [])
        if dependencies:
            lines.discard("from fastapi import APIRouter")
            lines.add("from fastapi import APIRouter, Depends")
        if f"Depends({self.guard})" in dependencies:
            lines.add(f"from app.core.{self.guard_module} import {self.guard}")
        if "Depends(translations_query)" in dependencies:
            lines.add("from app.core.i18n import translations_query")
        modules = {o.module for o in self.operations}
        if self.file_endpoints:
            modules.add("files")
        if modules:
            lines.add(from_import(f"app.features.{self.slice}", modules))
        return import_block(lines)

    @property
    def not_null(self) -> list[str]:
        """The attributes that an update cannot set to null."""
        names = [f.attr for f in self.input_fields if f.required]
        return names + [r.fk_attr for r in self.fk_relations if r.required and r.fk_attr]

    def model_imports(self) -> str:
        """Return the import block of the models module of the slice."""
        types = {f.model_type for f in self.fields} | {c.type for c in self.computed}
        types |= {t.type for t in self.totals}
        sa_types = {f.sa_type.split("(")[0] for f in self.fields if not f.enum}
        if self.translatable or self.files:
            sa_types.add("JSON_TYPE")
        lines: set[str] = set()
        if any(t.startswith("dt.") for t in types):
            lines.add("import datetime as dt")
        if "Decimal" in types:
            lines.add("from decimal import Decimal")
        targets = {r.target for r in self.relations if r.target != self.name}
        typing = {"TYPE_CHECKING"} if targets or self.totals else set[str]()
        if "Any" in types or self.sequences:
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
        if self.search_index is not None:
            sqlalchemy.add("Index")
            lines.add("from app.core.search import search_vector")
        if self.sequences:
            sqlalchemy.add("Sequence")
        if sqlalchemy:
            lines.add(from_import("sqlalchemy", sqlalchemy))
        orm = {"Mapped", "mapped_column"}
        if self.relations:
            orm.add("relationship")
        if self.sequences:
            orm.add("declared_attr")
        lines.add(from_import("sqlalchemy.orm", orm))
        core = {"Record"} | ({"Base"} if self.join_tables or self.sequences else set[str]())
        core |= {"NextNumber"} if self.sequences else set[str]()
        core |= sa_types & set(_MIGRATION_TYPES)
        field_enums = {f.enum.name for f in self.fields if f.enum is not None}
        core |= {"enum_type"} if field_enums else set[str]()
        lines.add(from_import("app.core.db", core))
        if self.computed:
            lines.add("from app.core import compute")
        if self.files:
            lines.add("from app.core.types import StoredFile")
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
        declarations += [
            f.translations_declaration(m) for f in self.translatable for m in ("create", "read")
        ]
        declarations += [f.declaration() for f in self.files]
        pydantic = {"Field"} if any("Field(" in d for d in declarations) else set[str]()
        for name in ("AwareDatetime", "EmailStr", "JsonValue"):
            if name in types:
                pydantic.add(name)
        if self.sign_up_fields is not None or self.line_items:
            # The password of the sign-up schema has a minimum length, and the ID of an item
            # of the lines has a description.
            pydantic.add("Field")
        typing: set[str] = set()
        if self.not_null or self.translatable:
            pydantic.add("model_validator")
            typing.add("Self")
        if any(f.text_rules for f in self.translatable):
            pydantic.add("Field")
            typing.add("Annotated")
        if typing:
            lines.add(from_import("typing", typing))
        if pydantic:
            lines.add(from_import("pydantic", pydantic))
        core = {"InputModel", "ReadModel"}
        if self.not_null:
            core.add("reject_null")
        lines.add(from_import("app.core.schemas", core))
        if self.translatable:
            i18n = {"Language", "translated"}
            if self.required_translatable:
                i18n.add("reject_empty_default")
            lines.add(from_import("app.core.i18n", i18n))
        if "UrlStr" in types:
            lines.add("from app.core.types import UrlStr")
        if self.files:
            lines.add("from app.core.storage import FileRead")
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


@dataclass(frozen=True, slots=True)
class PyStorage:
    """The storage of the files of the file fields (ADR 0027), with the names of its settings.

    The name of each setting is its environment variable in lower case,
    for example `storage_folder` for `STORAGE_FOLDER`.
    """

    id: str
    kind: str
    """`local` (a folder) or `s3` (an S3-compatible service, else the folder)."""
    variables: dict[str, str]
    """The environment variable of each key of the section `storage`, for example
    `{"folder_env": "STORAGE_FOLDER"}`."""

    def setting(self, key: str) -> str:
        """Return the setting of a key, for example `storage_folder` for `folder_env`."""
        return self.variables[key].lower()

    @property
    def s3(self) -> bool:
        return self.kind == "s3"


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
    translated: bool = False
    """True if the app has translations: the messages go through `t` (ADR 0010)."""
    message_elements: list[str] = field(default_factory=list[str])
    """The IDs of the elements whose messages the sign-in sends to the users (ADR 0023):
    `auth.password_reset` and `auth.sign_up.verify_email`."""
    rule_tests: list[PyRuleTest] = field(default_factory=list[PyRuleTest])
    """The generated tests of the record rules (ADR 0025)."""
    embed_tests: list[PyEmbedTest] = field(default_factory=list[PyEmbedTest])
    """The generated tests of the record rules on the embedded relations (ADR 0025)."""
    smtp: bool = False
    """True if the app sends these messages by SMTP (`auth.delivery: smtp`), not with the
    extension file `app/core/messages_ext.py`."""
    dashboards: dict[str, PyDashboard] = field(default_factory=dict[str, PyDashboard])
    """The dashboards with the endpoints of their widgets, by name."""
    access: bool = False
    """True if the app has roles (`access`)."""
    auth: bool = False
    """True if the app has the sign-in (`auth`)."""
    search_config: str | None = None
    """The text search configuration of Postgres with `x-fastapi-search: fulltext`, else None."""
    jobs: dict[str, PyJob] = field(default_factory=dict[str, PyJob])
    """The jobs that the worker runs (ADR 0029), by name."""
    storage: PyStorage | None = None
    """The storage of the files of the file fields (ADR 0027), or None without `storage`."""

    @property
    def events(self) -> bool:
        """True if an entity has an event, or a transition has `run` (ADR 0031)."""
        return any(e.events for e in self.entities.values())

    @property
    def full_text(self) -> bool:
        """True if the list endpoints use the full-text search of Postgres."""
        return self.search_config is not None

    @property
    def lines(self) -> bool:
        """True if an operation writes lines (ADR 0035): an error can give its place."""
        return any(e.lines for e in self.entities.values())

    @property
    def search_indexes(self) -> list[PyEntity]:
        """The entities with a GIN index for the full-text search, in the order of the tables."""
        return [e for e in self.entity_order() if e.search_index is not None]

    @property
    def test_today(self) -> str:
        """The date that the generated tests of the dashboards send as `today`."""
        return TEST_TODAY.isoformat()

    @property
    def dashboard_guard(self) -> str | None:
        """The dependency of the protected widget endpoints, or None without the sign-in."""
        if self.access:
            return "check_access"
        return "current_user" if self.auth else None

    @property
    def dashboard_guard_module(self) -> str | None:
        """The module in `app/core/` of the dependency of the protected widget endpoints."""
        if self.access:
            return "access"
        return "auth" if self.auth else None

    def entity(self, name: str) -> PyEntity:
        return self.entities[name]

    def models_head(self) -> str:
        """Return the imports of `app/models.py` from the standard library and SQLAlchemy."""
        return models_head(self.entity_order())

    def models_imports(self, first: list[tuple[list[str], str]]) -> list[tuple[list[str], str]]:
        """Return the imports of `app/models.py` from the app: the traces and the line of each."""
        return models_imports(self.entity_order(), first)

    def models_totals(self) -> list[tuple[list[str], str]]:
        """Return the statements of `app/models.py` that add the totals (ADR 0034)."""
        return models_code(self.entity_order())

    def entity_order(self) -> list[PyEntity]:
        """The entities in source order."""
        return list(self.entities.values())

    @property
    def join_tables(self) -> list[PyJoinTable]:
        return [t for e in self.entities.values() for t in e.join_tables]

    @property
    def translatable(self) -> bool:
        """True if an entity has a translatable field (ADR 0026)."""
        return any(e.translatable for e in self.entities.values())

    @property
    def file_entities(self) -> list[PyEntity]:
        """The entities with file fields (ADR 0027), in source order."""
        return [e for e in self.entity_order() if e.files]

    @property
    def sequences(self) -> list[PySequence]:
        """The sequences of the fields with `sequence`, in source order."""
        return [s for e in self.entity_order() for s in e.sequences]

    @property
    def file_slices(self) -> list[PyEntity]:
        """The entities with the endpoints of their files, in source order."""
        return [e for e in self.entity_order() if e.file_endpoints]

    @property
    def needs(self) -> list[tuple[str, str, str]]:
        """The endpoints that need the permission of an operation, with the element of each.

        A dashboard widget needs the list operation of its entity. The
        endpoints of a file field need the update operation of the entity,
        else its create operation (ADR 0027).
        """
        found = [
            (w.operation_id, w.permission, w.id)
            for d in self.dashboards.values()
            for w in d.widgets
            if w.protected
        ]
        for entity in self.file_slices:
            permission = entity.file_permission
            if permission is None or not permission.protected:
                continue
            for f in entity.files:
                found.append((f.upload_operation, permission.name, f.id))
                found.append((f.delete_operation, permission.name, f.id))
        return found

    @property
    def openapi_schemas(self) -> list[tuple[str, str]]:
        """The schemas that the endpoints use, with the ID of their element, in a fixed order."""
        found: dict[str, str] = {}
        for op in self.operations.values():
            entity = self.entities[op.entity]
            if op.kind in ("create", "read", "update", "list"):
                found[f"{entity.name}Read"] = entity.id
            if op.kind in ("create", "update") and op.lines:
                found[op.input_class] = op.id
                found.update({ln.item_class: ln.id for ln in op.lines})
            elif op.kind in ("create", "update"):
                found[f"{entity.name}{op.kind.capitalize()}"] = entity.id
            if op.custom and op.params:
                found[op.params_class] = op.id
            if op.returns:
                found[f"{op.returns}Read"] = self.entities[op.returns].id
            if entity.files and op.kind in ("create", "read", "update", "list"):
                found.setdefault("FileRead", entity.files[0].id)
        for dashboard in self.dashboards.values():
            for widget in dashboard.widgets:
                if widget.kind == "stat":
                    found.setdefault("StatValue", widget.id)
                elif widget.kind == "chart":
                    found.setdefault("ChartValues", widget.id)
                else:
                    found.setdefault(f"{widget.entity.name}Read", widget.entity.id)
        return sorted(found.items())

    def imports(self, lines: list[str]) -> str:
        """Return import lines in the groups and the order of the Ruff import sorter."""
        return import_block(set(lines))

    def from_import(self, module: str, names: list[str]) -> str:
        """Return a `from` import with the names in the order of the Ruff import sorter."""
        return from_import(module, set(names))

    def call(
        self, prefix: str, func: str, args: list[str], indent: int = 4, suffix: str = ""
    ) -> str:
        """Return a call on one line if it fits, else with one argument on each line."""
        return call(prefix, func, args, indent, suffix)

    def signature(self, head: str, params: str | list[str], tail: str, indent: int = 0) -> str:
        """Return a function signature in the format of the Ruff formatter."""
        return signature(head, params, tail, indent)

    def string(self, value: str) -> str:
        """Return a text as a Python string literal, with the quotes of the Ruff formatter."""
        return string(value)

    def literal(self, value: Any, prefix: str = "", indent: int = 0) -> str:
        """Return a JSON value as a Python literal, in the format of the Ruff formatter."""
        return literal(value, prefix, indent)

    def message(self, text: str) -> str:
        """Return a message without values: a call of `t` with translations, else a literal."""
        return f"t({string(text)})" if self.translated else string(text)

    def problem(self, status: int, text: str, indent: int, suffix: str = "", **values: str) -> str:
        """Return `raise ProblemError(<status>, <message>)`: a call of `t` with translations.

        The values are Python expressions, for example `id="id"`. The
        suffix follows the raise, for example ` from error`. The result has
        no indent on its first line.
        """
        return raise_problem(
            status, text, values, indent=indent, translated=self.translated, suffix=suffix
        )

    def record_rule(self, entity: str, rule: RecordRule) -> str:
        """Return the entry of a record rule in the table of `app/core/access.py` (ADR 0025).

        For example `"Task": RecordRule(actions=frozenset({"read"}), where={"status": ("done",)}),`.
        The keys of `where` are the attributes of the fields.
        """
        actions = ", ".join(string(a) for a in sorted(rule.operations))
        args = [f"actions=frozenset({{{actions}}})"]
        if rule.owner is not None:
            args.append("owner=True")
        if rule.where:
            attrs = {f.name: f.attr for f in self.entities[entity].fields}
            items = [
                f"{string(attrs[name])}: {_python_tuple(values)}"
                for name, values in rule.conditions().items()
            ]
            args.append(_braces("where=", items, 12))
        return call(f"{string(entity)}: ", "RecordRule", args, 8, ",")

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
    _events(definition, entities, operations)
    python_lines(definition, entities, operations)
    _record_rules(definition, entities)
    search_config = _search_config(definition)
    for entity in entities.values():
        if definition.access is not None:
            entity.guard = "check_access"
        if definition.translations is not None:
            entity.translated = True
            for rule in entity.rules:
                rule.translated = True
        _place_routes(entity)
        _check_names(entity)
        entity.full_text = search_config is not None
        entity.query = list_query(definition, entity)
        entity.totals_test = totals_test(definition, entity)
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
        translated=definition.translations is not None,
        message_elements=_message_elements(definition),
        rule_tests=_rule_tests(definition, entities),
        embed_tests=_embed_tests(definition, entities),
        smtp=bool(_message_elements(definition))
        and definition.auth is not None
        and definition.auth.delivery == "smtp",
        dashboards=python_dashboards(definition, entities),
        access=definition.access is not None,
        auth=auth is not None,
        search_config=search_config,
        jobs=_jobs(definition, entities, operations),
        storage=_storage(definition, entities),
    )


def _jobs(
    definition: AppDefinition, entities: dict[str, PyEntity], operations: dict[str, PyOperation]
) -> dict[str, PyJob]:
    """Return the jobs. Raise GenerationError if an entity has the table of the job runs."""
    if definition.jobs:
        for entity in entities.values():
            if entity.table == JOBS_TABLE:
                raise GenerationError(
                    f"The entity '{entity.name}' has the table '{JOBS_TABLE}' of the runs of the "
                    "jobs. Give it another table with x-fastapi-table."
                )
    return python_jobs(definition, entities, operations)


def _storage(definition: AppDefinition, entities: dict[str, PyEntity]) -> PyStorage | None:
    """Return the storage of the files, or None without `storage`.

    Raise GenerationError if the operation ID of an endpoint of a file is
    the name of an operation.
    """
    for entity in entities.values():
        for f in entity.files if entity.file_endpoints else []:
            for operation_id in (f.upload_operation, f.delete_operation):
                if operation_id in definition.operations:
                    raise GenerationError(
                        f"The endpoint of the file field '{entity.name}.{f.name}' has the "
                        f"operation ID '{operation_id}' of an operation. Rename the operation."
                    )
    storage = definition.storage
    if storage is None:
        return None
    return PyStorage(id=storage.id, kind=storage.kind, variables=dict(storage.variables))


def _search_config(definition: AppDefinition) -> str | None:
    """Return the text search configuration of `x-fastapi-search: fulltext`, else None.

    The configuration is the one of the default language of the
    translations (`SEARCH_CONFIGS`), else `simple`, which does not change
    the words.
    """
    if definition.app.extensions.get(SEARCH_KEY) != "fulltext":
        return None
    translations = definition.translations
    if translations is None:
        return "simple"
    code = translations.default
    tag = translations.languages[code].locale_tag(code)
    return SEARCH_CONFIGS.get(tag.replace("_", "-").split("-")[0].lower(), "simple")


def _message_elements(definition: AppDefinition) -> list[str]:
    """Return the IDs of the elements whose messages the sign-in sends, in a fixed order."""
    auth = definition.auth
    if auth is None:
        return []
    ids = [auth.password_reset.id] if auth.password_reset is not None else []
    if auth.sign_up is not None and auth.sign_up.verify_email is not None:
        ids.append(auth.sign_up.verify_email.id)
    return ids


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


def _record_rules(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Give each entity with a record rule its owner path, and its operations their action."""
    if definition.access is None:
        return
    users = entities[definition.auth.user_entity] if definition.auth else None
    for role in definition.access.roles.values():
        for name, rule in role.records.items():
            entity = entities[name]
            entity.scoped = True
            if rule.owner is not None and users is not None:
                entity.owner_path = _owner_path(entities, entity, rule.owner)
    for entity in entities.values():
        entity.hides = [r for r in entity.embedded if _can_hide(entities, r)]
        for rel in entity.hides:
            rel.hidden = entities[rel.target].scoped and not rel.many
    for entity in entities.values():
        for op in entity.operations:
            returns = entities[op.returns] if op.returns else None
            shows = op.kind in ("list", "read", "create", "update") and bool(entity.hides)
            if op.protected and (entity.scoped or shows or (returns and returns.hides)):
                op.scope_action = "read" if op.kind in ("list", "read") else "change"


def _can_hide(entities: dict[str, PyEntity], rel: PyRelation) -> bool:
    """Return True if a record rule can hide the target of an embedded relation, or a nested one."""
    target = entities[rel.target]
    return target.scoped or any(_can_hide(entities, r) for r in target.embedded)


def _rule_tests(definition: AppDefinition, entities: dict[str, PyEntity]) -> list[PyRuleTest]:
    """Return the tests of the record rules, for the rules that the tests can check.

    The records of a test have the values of the conditions in the scope,
    and one record for each condition has a value out of the scope. A
    workflow with an initial state sets the state of each new record, so
    a condition on its field needs the initial state in the scope.
    """
    if definition.access is None:
        return []
    found: list[PyRuleTest] = []
    for role_name, role in definition.access.roles.items():
        for name, rule in role.records.items():
            entity = entities[name]
            ops: dict[str, PyOperation] = {}
            for op in entity.operations:
                if not op.protected or not role.allows_operation(op.name) or op.kind in ops:
                    continue
                if op.custom and any(p.required for p in op.params):
                    continue
                ops[op.kind] = op
            if not ops:
                continue
            values = _rule_values(entity, rule.conditions())
            if values is None:
                continue
            inside, outside, patch = values
            found.append(
                PyRuleTest(
                    role=role_name,
                    id=rule.id,
                    entity=entity,
                    reads="read" in rule.operations,
                    owner=rule.owner is not None,
                    inside=inside,
                    outside=outside,
                    patch=patch,
                    ops=ops,
                )
            )
    return found


def _embed_tests(definition: AppDefinition, entities: dict[str, PyEntity]) -> list[PyEmbedTest]:
    """Return the tests of the rules on the embedded relations that the tests can check.

    A test needs a role that reads the entity, a rule of the role on the
    target with conditions only and a value out of the scope, and no
    owner in the rule of the role on the entity.
    """
    if definition.access is None:
        return []
    found: list[PyEmbedTest] = []
    for role_name, role in definition.access.roles.items():
        for entity in entities.values():
            read = next(
                (
                    op
                    for op in entity.operations
                    if op.kind == "read" and op.protected and role.allows_operation(op.name)
                ),
                None,
            )
            own = role.records.get(entity.name)
            if read is None or (own is not None and own.owner is not None):
                continue
            values: tuple[str, list[str], str | None] | None = ("{}", [], None)
            if own is not None:
                values = _rule_values(entity, own.conditions())
            for rel in entity.hides:
                rule = role.records.get(rel.target)
                if values is None or rule is None or rule.owner is not None:
                    continue
                target = _rule_values(entities[rel.target], rule.conditions())
                if target is None or not target[1]:
                    continue
                found.append(
                    PyEmbedTest(
                        role=role_name,
                        entity=entity,
                        relation=rel,
                        read=read,
                        values=values[0],
                        inside=target[0],
                        outside=target[1][0],
                    )
                )
    return found


def _rule_values(
    entity: PyEntity, conditions: dict[str, list[str | int | bool]]
) -> tuple[str, list[str], str | None] | None:
    """Return the values of a test of a rule: in the scope, out of it, and a change out of it.

    Return None if no record of the tests can be in the scope.
    """
    fields = {f.name: f for f in entity.fields}
    initials = {w.field: w.initial for w in entity.workflows if w.initial is not None}
    moves = {w.field for w in entity.workflows}
    inside: dict[str, str] = {}
    others: dict[str, str] = {}
    for name, values in conditions.items():
        f = fields[name]
        initial = initials.get(name)
        if initial is not None:
            if initial not in values:
                return None
            inside[name] = string(initial)
            continue
        inside[name] = _python_value(values[0])
        other = _other_value(f, values)
        if other is not None:
            others[name] = other

    def merged(name: str, value: str) -> str:
        items = [f"{string(k)}: {value if k == name else v}" for k, v in inside.items()]
        return "{" + ", ".join(items) + "}"

    outside = [merged(name, value) for name, value in others.items()]
    patch = next(
        (f"{{{string(name)}: {value}}}" for name, value in others.items() if name not in moves),
        None,
    )
    as_dict = "{" + ", ".join(f"{string(k)}: {v}" for k, v in inside.items()) + "}"
    return as_dict, outside, patch


def _python_value(value: str | int | bool) -> str:
    return string(value) if isinstance(value, str) else repr(value)


def _other_value(f: PyField, values: list[str | int | bool]) -> str | None:
    """Return a valid value of a field that is not in a list, as Python source, or None."""
    if f.enum is not None:
        return next((string(v) for _, v in f.enum.members if v not in values), None)
    if f.type == "boolean":
        return next((repr(v) for v in (True, False) if v not in values), None)
    if f.type == "integer":
        bounds = dict(f.constraints)
        low = int(bounds.get("ge", "0"))
        high = int(bounds.get("le", str(low + len(values))))
        return next((str(n) for n in range(low, high + 1) if n not in values), None)
    return None


def _owner_path(entities: dict[str, PyEntity], entity: PyEntity, path: str) -> PyOwnerPath:
    """Return the steps of an owner path (the validator checks that each step exists)."""
    steps: list[tuple[PyEntity, PyRelation]] = []
    current = entity
    for step in path.split("."):
        relation = next(r for r in current.relations if r.name == step)
        steps.append((current, relation))
        current = entities[relation.target]
    return PyOwnerPath(path=path, steps=steps)


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
            if f.type not in FILE_TYPES
        ],
        files=[
            PyFile(
                name=field_name,
                attr=attribute(field_name),
                id=f.id,
                entity=snake(name),
                max_size=f.size_limit,
                media_types=tuple(f.media_types),
                docs=_constraints(f),
            )
            for field_name, f in entity.stored_fields.items()
            if f.type in FILE_TYPES
        ],
    )


def _computed(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Add the computed fields to the entities, and load the relations that they read.

    A total of a relation becomes a column property of the model (ADR 0034).
    """
    for name, entity in definition.entities.items():
        for field_name, f in entity.computed_fields.items():
            assert f.computed is not None
            expression = parse_expression(f.computed)
            totals = entity_totals(definition, entities, name, field_name, expression)
            lines: list[str] = []
            result = _render_computed(entities, name, expression, lines, totals)
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
                    expression=expression,
                    totals=totals,
                    sql=computed_sql(entities[name], expression, totals),
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


def _events(
    definition: AppDefinition, entities: dict[str, PyEntity], operations: dict[str, PyOperation]
) -> None:
    """Add the events and the transitions with `run` to the entities (ADR 0031)."""
    for name, entity in definition.entities.items():
        py_entity = entities[name]
        attrs = {f.name: f.attr for f in py_entity.fields}
        events = sorted(entity.events.items(), key=lambda item: EVENT_NAMES.index(item[0]))
        for kind, event in events:
            watched = event.fields if kind == "changed" and event.fields else list(attrs)
            py_entity.events.append(
                PyEvent(
                    kind=kind,
                    id=event.id,
                    operation=operations[event.operation],
                    attrs=[attrs[n] for n in watched] if kind == "changed" else [],
                    fields=event.fields,
                    name=kind,
                )
            )
    for workflow in definition.workflows.values():
        py_entity = entities[workflow.entity]
        py_workflow = next(w for w in py_entity.workflows if w.id == workflow.id)
        for transition_name, transition in workflow.transitions.items():
            if transition.run is None:
                continue
            py_entity.events.append(
                PyEvent(
                    kind="transition",
                    id=transition.id,
                    operation=operations[transition.run],
                    workflow=py_workflow,
                    before=list(transition.from_),
                    after=transition.to,
                    name=transition_name,
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
    entities: dict[str, PyEntity],
    entity: str,
    expression: Expression,
    lines: list[str],
    totals: dict[str, PyTotal],
) -> str:
    """Add the statements of an expression to `lines`, and return the name of its value.

    Each statement computes one part of the expression in a local variable,
    so that the lines stay short. A total reads its column property.
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
        case Total():
            return assign(f"compute.num(self.{totals[str(expression)].attr})")
        case Call(function, args):
            values = [
                _computed_path(entities, entity, a.path) for a in args if isinstance(a, FieldRef)
            ]
            return assign(f"compute.{function}({', '.join(values)})")
        case Binary(op, left, right):
            a = _render_computed(entities, entity, left, lines, totals)
            b = _render_computed(entities, entity, right, lines, totals)
            return assign(f"compute.{_COMPUTE_OPS[op]}({a}, {b})")
        case Negate(operand):
            inner = _render_computed(entities, entity, operand, lines, totals)
            return assign(f"compute.neg({inner})")


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


def _sequence(name: str, f: Field, table: str) -> PySequence | None:
    if f.sequence is None:
        return None
    return PySequence(
        id=f.sequence.id,
        name=f"{table}_{name}_seq",
        const=f"{constant(name)}_SEQUENCE",
        start=f.sequence.start,
        table=table,
        column=name,
        prefix=f.sequence.prefix,
        width=(f.sequence.width or 1) if f.type == "string" else None,
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
    sequence = _sequence(name, f, table)
    if sequence is not None and f.type == "integer":
        sa_type = "BigInteger"  # The numbers of a sequence grow.
    return PyField(
        name=name,
        attr=attribute(name),
        id=f.id,
        type=f.type,
        model_type=model_type,
        schema_type=schema_type,
        sa_type=sa_type,
        # A field with a sequence always has a value.
        required=f.required or sequence is not None,
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
        translatable=f.translatable,
        sequence=sequence,
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

    modules = {"enums", "files", "models", "repository", "router", "schemas", "validation_ext"}
    for op in entity.operations:
        if op.module in modules or op.name in modules:
            raise GenerationError(
                f"The operation '{op.name}' has the name of a module of the slice "
                f"'{entity.slice}'. Give it another name."
            )
    for f in entity.fields:
        claim(f.attr, f"the field '{f.name}'")
    for file in entity.files:
        claim(file.attr, f"the field '{file.name}'")
    for rel in entity.relations:
        claim(rel.attr, f"the relation '{rel.name}'")
        if rel.fk_attr:
            claim(rel.fk_attr, f"the foreign key of the relation '{rel.name}'")
        if rel.ids_field:
            claim(rel.ids_field, f"the IDs of the relation '{rel.name}'")


def binding_context(definition: AppDefinition) -> dict[str, Any]:
    """Return the values that the binding adds to the context of all templates.

    `i18n` is the plan of the languages (ADR 0010), or None without
    translations. `i18n_test` has the values of the test of the languages.
    `py_seed` has the rows of the seed (ADR 0021).
    """
    apis = python_apis(definition)
    plan = i18n_plan(definition)
    py = python_app(definition)
    return {
        "py": py,
        "py_seed": python_seed(definition, py),
        "py_apis": apis,
        "py_webhooks": python_webhooks(definition),
        "py_api_mocks_imports": mocks_imports(apis),
        "py_api_features": py_features(apis),
        "py_connections": python_connections(apis),
        "i18n": plan,
        "i18n_test": language_test(plan) if plan is not None else None,
    }
