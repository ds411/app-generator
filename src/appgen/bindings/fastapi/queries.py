"""The query of the list endpoints: the filters, the search, and the sort of the views.

The list endpoint of an entity takes a parameter for each filter of the
tables and card lists of the entity, `q` for their search, and a sort key
for each sortable column and for the sort of each table, card list, and
board. The equality filters of the fields stay as they are, so that the
clients that use them do not change. A select filter makes the parameter
of its field a list (`?status=a&status=b`), which also takes one value.

A field path of a view can go through relations, for example
`owner.name`. A filter goes through them with `has()` (an `EXISTS`
subquery), and a sort key reads the related value with a correlated
subquery. A computed field and a relation to many records have no sort
key, because their values are not columns.

Each list endpoint takes `id`, a list of record IDs: the React app
sends it to load the related records of a page, and the records of a
tab of a detail view that lists a `many_to_many` relation. `q` also
searches the display field of the entity, so that a form can search the
options of a reference field. A board adds a filter of its group field,
so that it loads each column, and a calendar adds the date ranges of its
start (and of its end), so that it loads the records of the shown dates.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.pysource import LINE_LENGTH, call, string
from appgen.bindings.shared.views import definition_display
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.fields import TEXT_TYPES
from appgen.dsl.ui.views import (
    ApiViewBase,
    BoardView,
    BooleanFilter,
    CalendarView,
    CardsView,
    DateRangeFilter,
    DetailTab,
    DetailView,
    SearchFilter,
    SelectFilter,
    TableView,
    View,
)
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyField, PyRelation

_SORT_TYPES = frozenset(
    {"string", "text", "email", "url", "integer", "decimal", "boolean", "date", "datetime"}
    | {"uuid", "enum"}
)
"""The field types that a sort key can have."""
_FIXED_PARAMS = frozenset({"limit", "offset", "sort"})
"""The parameters of all list endpoints (`PageQuery`)."""


@dataclass(frozen=True, slots=True)
class Call:
    """A call in generated code. The renderer puts it on one line or on many."""

    func: str
    args: tuple[Expr, ...]


type Expr = str | Call


def render(expr: Expr, indent: int, prefix: str = "", suffix: str = "") -> str:
    """Return the code of an expression in the format of the Ruff formatter.

    A call that does not fit in the line length has one argument on each
    line and a trailing comma, so that the formatter keeps it as it is.
    The first line has no indent. The next lines have the indent.
    """
    one_line = prefix + _flat(expr) + suffix
    if isinstance(expr, str) or indent + len(one_line) <= LINE_LENGTH:
        return one_line
    pad = " " * indent
    inner = "".join(f"{pad}    {render(arg, indent + 4, suffix=',')}\n" for arg in expr.args)
    return f"{prefix}{expr.func}(\n{inner}{pad}){suffix}"


def _flat(expr: Expr) -> str:
    if isinstance(expr, str):
        return expr
    return f"{expr.func}({', '.join(_flat(arg) for arg in expr.args)})"


@dataclass(frozen=True, slots=True)
class Hop:
    """A relation of a field path, from one entity to the next."""

    source: PyEntity
    relation: PyRelation
    target: PyEntity


@dataclass(frozen=True, slots=True)
class PyPath:
    """A field path of a view, for example `owner.name`, in the terms of the binding."""

    path: str
    hops: tuple[Hop, ...]
    entity: PyEntity
    """The entity at the end of the path."""
    field: PyField | None = None
    relation: PyRelation | None = None
    computed: bool = False
    """True for a computed field: it has no column."""

    @property
    def column(self) -> str:
        """The column at the end of the path, on the class of its entity.

        For a relation, it is the foreign key column. For `id`, the primary key.
        """
        if self.field is not None:
            return f"{self.entity.name}.{self.field.attr}"
        if self.relation is not None:
            return f"{self.entity.name}.{self.relation.fk_attr}"
        return f"{self.entity.name}.id"

    @property
    def datetime(self) -> bool:
        return self.field is not None and self.field.type == "datetime"

    @property
    def aliases(self) -> list[str]:
        """The names of the aliases of the entities of the hops, for example `_project_owner`."""
        segments = self.path.split(".")[:-1]
        return ["_" + "_".join(segments[: i + 1]) for i in range(len(segments))]

    def criterion(self, inner: Expr) -> Expr:
        """Return a condition on the records, from a condition on the entity at the end."""
        for hop in reversed(self.hops):
            inner = Call(f"{hop.source.name}.{hop.relation.attr}.has", (inner,))
        return inner

    def entities(self) -> list[PyEntity]:
        """The entities whose classes the conditions of the path use."""
        found = [h.source for h in self.hops] + [self.entity]
        relation = self.relation
        if relation is not None and relation.side != "fk":
            found.append(self.entity.target(relation))
        return found


@dataclass(slots=True)
class TestPlan:
    """How a generated test makes a record with a known value of a path.

    Without a parent and a target, the test reads the value of the field
    `attr` of a new record. With a parent, the test makes the parent first
    and links the record to it with `fk`: the value is `attr` of the parent.
    With a target, the test makes a target record, and links the record to
    it with `fk` (a foreign key) or `ids` (a many-to-many relation).
    """

    attr: str | None = None
    parent: PyEntity | None = None
    target: PyEntity | None = None
    fk: str | None = None
    ids: str | None = None


@dataclass(slots=True)
class PyParam:
    """A query parameter of a list endpoint for a filter."""

    name: str
    """The name in the URL, for example `status`, `due_date_from`, or `project.status`."""
    attr: str
    """The attribute of the query model."""
    type: str
    """The Python type of the value, without None, for example `list[TaskStatus]`."""
    kind: str
    """`eq` (equality), `in` (select), `from` and `to` (date range), or `search`."""
    path: PyPath
    """The path of the value. For the search, the first of its paths."""
    ids: list[str] = field(default_factory=list[str])
    """The definition elements of the parameter, for the traces."""
    description: str | None = None
    search: list[PyPath] = field(default_factory=list[PyPath])
    """For the search: the paths of the text fields."""
    test: TestPlan | None = None
    """How a test makes a record with a known value, or None if no test is generated."""
    hop_test: TestPlan | None = None
    """For the search: a test of a field of a related record, or None."""
    full_text: bool = False
    """For the search: True for the full-text search of Postgres (`x-fastapi-search`)."""

    @property
    def rank_field(self) -> PyField | None:
        """For the full-text search: a field of the vector that the test of the rank can set.

        The test stores the words `report draft`, so the field must take a
        free text of 20 characters.
        """
        for path in self.vector:
            f = path.field
            if f is None or f.type not in ("string", "text") or f.enum is not None:
                continue
            rules = dict(f.constraints)
            if "pattern" in rules or int(rules.get("max_length", "20")) < 20:
                continue
            if int(rules.get("min_length", "0")) <= 12:
                return f
        return None

    @property
    def vector(self) -> list[PyPath]:
        """For the full-text search: the text fields of the entity, in one vector with an index."""
        return [p for p in self.search if self.full_text and _in_vector(p)]

    @property
    def is_list(self) -> bool:
        return self.type.startswith("list[")

    def declaration(self) -> str:
        """Return the declaration of the parameter in the query model."""
        type_ = self.type + " | None"
        args = [f'alias="{self.name}"'] if self.attr != self.name else []
        if self.description:
            args.append(f"description={_string(self.description)}")
        if not args:
            return f"{self.attr}: {type_} = None"
        return call(f"{self.attr}: {type_} = ", "Field", ["default=None", *args])

    def where_lines(self) -> list[str]:
        """Return the statements that add the condition of the parameter to `statement`."""
        value = f"query.{self.attr}"
        if self.kind == "search":
            return self._search_lines(value)
        path = self.path
        match self.kind:
            case "in":
                condition = path.criterion(self._in(value))
            case "from":
                bound = f"day_start({value})" if path.datetime else value
                condition = path.criterion(f"{path.column} >= {bound}")
            case "to" if path.datetime:
                condition = path.criterion(f"{path.column} < day_start({value}, 1)")
            case "to":
                condition = path.criterion(f"{path.column} <= {value}")
            case _:
                condition = path.criterion(f"{path.column} == {value}")
        test = f"if {value}:" if self.is_list else f"if {value} is not None:"
        where = render(Call("statement.where", (condition,)), 8, "statement = ")
        return [test, f"    {where}"]

    def _search_lines(self, value: str) -> list[str]:
        """Return the statements of `q`: on Postgres the full-text search, else `LIKE`."""
        terms = tuple(p.criterion(Call("contains", (p.column, "word"))) for p in self.search)
        if not self.full_text:
            where = render(Call("statement.where", (Call("or_", terms),)), 8, "statement = ")
            return [f"for word in search_words({value}):", f"    {where}"]
        vector = self.vector
        matches: list[Expr] = ["matches(vector, words)"] if vector else []
        for p in self.search:
            if not _in_vector(p):
                inner = Call("matches", (Call("search_vector", (p.column,)), "words"))
                matches.append(p.criterion(inner))
        lines = ["rank = None"] if vector else []
        lines += [f"if {value} and full_text(session):", f"    words = web_query({value})"]
        if vector:
            columns = Call("search_vector", tuple(p.column for p in vector))
            lines.append("    " + render(columns, 8, "vector = "))
        where = Call("statement.where", (Call("or_", tuple(matches)),))
        lines.append("    " + render(where, 8, "statement = "))
        if vector:
            lines.append("    rank = search_rank(vector, words)")
        where = render(Call("statement.where", (Call("or_", terms),)), 12, "statement = ")
        return [*lines, "else:", f"    for word in search_words({value}):", f"        {where}"]

    def _in(self, value: str) -> Expr:
        relation = self.path.relation
        if relation is None or relation.side == "fk":
            return Call(f"{self.path.column}.in_", (value,))
        entity = self.path.entity
        target = entity.target(relation)
        method = "any" if relation.many else "has"
        inner = Call(f"{target.name}.id.in_", (value,))
        return Call(f"{entity.name}.{relation.attr}.{method}", (inner,))


def _in_vector(path: PyPath) -> bool:
    """Return True for a text field of the entity itself: the vector of its index has it."""
    return not path.hops and path.field is not None and not path.computed


def _string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass(slots=True)
class PySortKey:
    """A key of the `sort` parameter of a list endpoint."""

    name: str
    """The key, for example `due_date` or `owner.name`."""
    path: PyPath
    """The path of the value. For a relation, the display field of the target."""
    ids: list[str] = field(default_factory=list[str])
    """The definition elements that ask for the key (columns and sorts), for the traces."""
    test: TestPlan | None = None
    """How a test makes records with known values, or None if no test is generated."""

    def entry(self) -> str:
        """Return the entry of the key in the `SORTABLE` mapping, at an indent of 4."""
        path = self.path
        prefix = f'"{self.name}": '
        if not path.hops:
            return f"{prefix}{path.column},"
        aliases = path.aliases
        conditions: list[Expr] = []
        for index, hop in enumerate(path.hops):
            source = hop.source.name if index == 0 else aliases[index - 1]
            conditions.append(_join(hop, source, aliases[index]))
        column = aliases[-1] + "." + path.column.partition(".")[2]
        return render(Call("lookup", (column, *conditions)), 4, prefix, ",")


def _join(hop: Hop, source: str, alias: str) -> str:
    """Return the condition that joins the alias of the target of a hop to its source."""
    relation = hop.relation
    if relation.side == "fk":
        return f"{alias}.id == {source}.{relation.fk_attr}"
    inverse = next(r for r in hop.target.relations if r.name == relation.back_populates)
    return f"{alias}.{inverse.fk_attr} == {source}.id"


@dataclass(frozen=True, slots=True)
class PySearchIndex:
    """The GIN index of the full-text search of an entity: the vector of the text fields of `q`."""

    name: str
    """The index name, for example `ix_projects_search`."""
    table: str
    entity: str
    fields: tuple[PyField, ...]
    ids: tuple[str, ...]
    """The definition elements of `q`, for the traces."""

    def model_code(self) -> str:
        """Return the declaration of the index after the model class (only for Postgres)."""
        columns = Call("search_vector", tuple(f"{self.entity}.{f.attr}" for f in self.fields))
        index = Call("Index", (f'"{self.name}"', columns, 'postgresql_using="gin"'))
        return render(index, 0, suffix='.ddl_if(dialect="postgresql")')

    def migration_lines(self, config: str) -> list[str]:
        """Return the statements of the first migration that create the index, at an indent of 4.

        The expression is the one of `search_vector` in `app/core/search.py`,
        so that Alembic finds no difference between the index and the model.
        """
        parts = [f"coalesce(\"{f.name}\", '')" for f in self.fields]
        tokens = [f"to_tsvector('{config}'::regconfig, {parts[0]}"]
        tokens += [f" || ' ' || {part}" for part in parts[1:]]
        tokens[-1] += ")"
        one_line = "vector = " + string("".join(tokens))
        if 8 + len(one_line) <= LINE_LENGTH:
            lines = [f"    {one_line}"]
        else:
            chunks = [""]
            for token in tokens:
                if chunks[-1] and 12 + len(string(chunks[-1] + token)) > LINE_LENGTH:
                    chunks.append("")
                chunks[-1] += token
            lines = ["    vector = (", *(f"        {string(c)}" for c in chunks), "    )"]
        args = [f'"{self.name}"', f'"{self.table}"', "[sa.text(vector)]", 'postgresql_using="gin"']
        return [*lines, "    " + call("", "op.create_index", args, 8)]


@dataclass(slots=True)
class PyListQuery:
    """The filters and the sort keys of the list endpoint of an entity."""

    params: list[PyParam] = field(default_factory=list[PyParam])
    sort_keys: list[PySortKey] = field(default_factory=list[PySortKey])

    @property
    def aliases(self) -> list[tuple[str, str]]:
        """The aliases of the related entities of the sort keys: the name and the entity."""
        found: dict[str, str] = {}
        for key in self.sort_keys:
            for alias, hop in zip(key.path.aliases, key.path.hops, strict=True):
                found.setdefault(alias, hop.target.name)
        return list(found.items())

    @property
    def search(self) -> PyParam | None:
        return next((p for p in self.params if p.kind == "search"), None)

    def search_index(self, entity: PyEntity) -> PySearchIndex | None:
        """Return the GIN index of the full-text search of the entity, or None."""
        search = self.search
        if search is None or not search.vector:
            return None
        fields = tuple(f for p in search.vector if (f := p.field) is not None)
        name = f"ix_{entity.table[:53]}_search"
        return PySearchIndex(name, entity.table, entity.name, fields, tuple(search.ids))

    @property
    def ranked(self) -> bool:
        """True if the full-text search orders the records by their rank without a sort."""
        search = self.search
        return search is not None and bool(search.vector)

    @property
    def view_sort_keys(self) -> list[PySortKey]:
        """The sort keys that a view asks for."""
        return [k for k in self.sort_keys if k.ids]

    @property
    def sort_tests(self) -> bool:
        """True if the tests check the order of a sort key of a view."""
        return any(k.test for k in self.view_sort_keys)

    def entities(self) -> list[PyEntity]:
        """The entities whose classes the conditions and the sort keys use."""
        paths = [p.path for p in self.params] + [s for p in self.params for s in p.search]
        found = [e for path in paths for e in path.entities()]
        return found + [h.target for k in self.sort_keys for h in k.path.hops]


def list_query(definition: AppDefinition, entity: PyEntity) -> PyListQuery:
    """Return the query of the list endpoint of an entity, from its fields and its views.

    Raise GenerationError if two parameters get the same name.
    """
    builder = _Builder(definition, entity)
    builder.add(
        PyParam(
            "id",
            "id",
            "list[UUID]",
            "in",
            PyPath("id", (), entity),
            [entity.id],
            "The IDs of the records.",
            test=_ID_TEST,
        )
    )
    for f in entity.filters:
        path = PyPath(f.name, (), entity, field=f)
        builder.add(PyParam(f.name, f.attr, f.read_type, "eq", path, [f.id]))
    for r in entity.fk_relations:
        assert r.fk_attr is not None
        path = PyPath(r.name, (), entity, relation=r)
        builder.add(PyParam(r.fk_attr, r.fk_attr, "UUID", "eq", path, [r.id]))
    for f in entity.sortable:
        builder.keys[f.name] = PySortKey(f.name, PyPath(f.name, (), entity, field=f))
    views: list[View] = list(definition.ui.views.values()) if definition.ui is not None else []
    for view in views:
        if isinstance(view, ApiViewBase):
            continue
        if isinstance(view, DetailView):
            for tab in view.tabs.values():
                builder.tab(view.entity, tab)
        if view.entity != entity.name:
            continue
        if isinstance(view, TableView | CardsView):
            for filter_ in view.filters.values():
                builder.filter(filter_)
        if isinstance(view, BoardView):
            builder.board(view)
        if isinstance(view, CalendarView):
            builder.calendar(view)
        if isinstance(view, TableView | CardsView | BoardView) and view.sort is not None:
            builder.sort_key(view.sort.field, view.sort.id)
        if isinstance(view, TableView):
            for name, column in view.columns.items():
                if column.sortable:
                    builder.sort_key(column.field or name, column.id)
    return builder.done()


class _Builder:
    def __init__(self, definition: AppDefinition, entity: PyEntity) -> None:
        self.definition = definition
        self.entity = entity
        self.params: dict[str, PyParam] = {}
        self.keys: dict[str, PySortKey] = {}
        self.search: dict[str, PyPath] = {}
        self.search_ids: list[str] = []

    def add(self, param: PyParam) -> None:
        if param.name in _FIXED_PARAMS or param.name in self.params:
            raise GenerationError(
                f"The list endpoint of the entity '{self.entity.name}' has two query "
                f"parameters '{param.name}'. Rename a field, or remove a filter of a view."
            )
        self.params[param.name] = param

    def filter(
        self, filter_: SearchFilter | SelectFilter | BooleanFilter | DateRangeFilter
    ) -> None:
        if isinstance(filter_, SearchFilter):
            for path in filter_.fields:
                self.search.setdefault(path, self.resolve(path))
            self.search_ids.append(filter_.id)
            return
        path = self.resolve(filter_.field)
        if isinstance(filter_, DateRangeFilter):
            self.date_range(path, filter_.id)
        elif isinstance(filter_, BooleanFilter):
            self.value(path, "eq", "bool", filter_.id)
        else:
            self.value(path, "in", f"list[{_value_type(path)}]", filter_.id)

    def value(self, path: PyPath, kind: str, type_: str, element_id: str) -> None:
        """Add a filter by a value (`eq`) or by a list of values (`in`) of a path."""
        name, attr = _names(path)
        existing = self.params.get(name)
        if existing is not None and existing.path.path == path.path:
            if kind == "in":
                existing.kind, existing.type = kind, type_
            existing.ids.append(element_id)
            existing.test = existing.test or _test(path)
            return
        self.add(PyParam(name, attr, type_, kind, path, [element_id], test=_test(path)))

    def date_range(self, path: PyPath, element_id: str) -> None:
        """Add the first and the last day of a date or a date-time path."""
        name, attr = _names(path)
        for end, word in (("from", "first"), ("to", "last")):
            existing = self.params.get(f"{name}_{end}")
            if existing is not None and existing.kind == end and existing.path.path == path.path:
                existing.ids.append(element_id)
                continue
            description = f"The {word} day of `{path.path}`."
            param = PyParam(f"{name}_{end}", f"{attr}_{end}", "dt.date", end, path)
            param.ids, param.description, param.test = [element_id], description, _test(path)
            self.add(param)

    def board(self, view: BoardView) -> None:
        """Add the filter of the group field of a board: the board loads each column."""
        path = self.resolve(view.group_by)
        self.value(path, "in", f"list[{_value_type(path)}]", view.id)

    def calendar(self, view: CalendarView) -> None:
        """Add the date ranges that a calendar sends for the shown days.

        A calendar with a required end loads the records that start before
        the last day and end after the first day. Else it loads the records
        that start in the shown days.
        """
        self.date_range(self.resolve(view.start), view.id)
        if view.end is not None:
            end = self.resolve(view.end)
            if end.field is not None and end.field.required:
                self.date_range(end, view.id)

    def tab(self, owner: str, tab: DetailTab) -> None:
        """Trace `id` to a tab that lists the records of a `many_to_many` relation."""
        relation = self.definition.entities[owner].relations.get(tab.relation or "")
        if relation is None or relation.kind != "many_to_many":
            return
        if relation.target == self.entity.name:
            self.params["id"].ids.append(tab.id)

    def sort_key(self, path_text: str, element_id: str) -> None:
        path = self.resolve(path_text)
        relation = path.relation
        if relation is not None:
            if relation.many:
                return
            display = definition_display(self.definition.entities[relation.target])
            path = self.resolve(f"{path_text}.{display}")
        if path.computed or (path.field is not None and path.field.type not in _SORT_TYPES):
            return
        last = path_text.rsplit(".", 1)[-1]
        if path.field is None and any(f.name == last for f in path.entity.files):
            # A file field (ADR 0027): the views do not sort by a file.
            return
        key = self.keys.setdefault(path_text, PySortKey(path_text, path))
        key.test = key.test or _test(path)
        key.ids.append(element_id)

    def display(self) -> PyPath | None:
        """Return the display field of the entity if it is a text: `q` searches it."""
        name = definition_display(self.definition.entities[self.entity.name])
        found = next((f for f in self.entity.fields if f.name == name), None)
        if found is None or found.type not in TEXT_TYPES:
            return None
        return PyPath(name, (), self.entity, field=found)

    def resolve(self, path: str) -> PyPath:
        return resolve_path(self.entity, path)

    def done(self) -> PyListQuery:
        params = list(self.params.values())
        display = self.display()
        if display is not None:
            self.search.setdefault(display.path, display)
            assert display.field is not None
            self.search_ids.append(display.field.id)
        if self.search:
            paths = list(self.search.values())
            fields = ", ".join(f"`{p.path}`" for p in paths)
            description = f"Words that each record has in one of the fields {fields}, in any case."
            if self.entity.full_text:
                description = (
                    f"A web search in the fields {fields}: words, a phrase in quotes, `or`, "
                    "and `-word`. Postgres compares the stems of the words. SQLite finds "
                    "each word in one of the fields, in any case."
                )
            search = PyParam(
                "q",
                "q",
                "str",
                "search",
                paths[0],
                self.search_ids,
                description,
                paths,
                test=next((_test(p) for p in paths if not p.hops), None),
                hop_test=next((t for p in paths if p.hops and (t := _test(p))), None),
                full_text=self.entity.full_text,
            )
            self.add(search)
            params.append(search)
        attrs = [p.attr for p in params]
        for attr in attrs:
            if attrs.count(attr) > 1 or attr in _FIXED_PARAMS:
                raise GenerationError(
                    f"Two query parameters of the list endpoint of the entity "
                    f"'{self.entity.name}' give the Python name '{attr}'. Rename a field, "
                    "or remove a filter of a view."
                )
        return PyListQuery(params, list(self.keys.values()))


def resolve_path(entity: PyEntity, path: str) -> PyPath:
    """Return a field path of the definition, from an entity, in the terms of the binding."""
    hops: list[Hop] = []
    segments = path.split(".")
    for segment in segments[:-1]:
        relation = next(r for r in entity.relations if r.name == segment)
        target = entity.target(relation)
        hops.append(Hop(entity, relation, target))
        entity = target
    last = segments[-1]
    found = next((f for f in entity.fields if f.name == last), None)
    if found is not None:
        return PyPath(path, tuple(hops), entity, field=found)
    relation = next((r for r in entity.relations if r.name == last), None)
    if relation is not None:
        return PyPath(path, tuple(hops), entity, relation=relation)
    computed = any(c.name == last for c in entity.computed)
    return PyPath(path, tuple(hops), entity, computed=computed)


_ID_TEST = TestPlan(attr="id")
"""A test of `id` makes records, and reads their IDs."""


def _names(path: PyPath) -> tuple[str, str]:
    """Return the name in the URL and the attribute of the parameter of a path."""
    relation = path.relation
    if path.field is not None:
        name, attr = path.field.name, path.field.attr
    elif relation is None:
        name = attr = "id"
    elif relation.side == "fk":
        name = attr = str(relation.fk_attr)
    elif relation.side == "m2m":
        name = attr = str(relation.ids_field)
    else:
        name = attr = f"{relation.attr}_id"
    if not path.hops:
        return name, attr
    segments = path.path.split(".")[:-1]
    return ".".join([*segments, name]), "__".join([*segments, attr])


def _value_type(path: PyPath) -> str:
    """Return the Python type of one value of a select filter."""
    if path.field is not None and path.field.enum is not None:
        return path.field.enum.name
    return "UUID"


def _test(path: PyPath) -> TestPlan | None:
    """Return how a test makes a record with a known value of a path, or None."""
    relation = path.relation
    if len(path.hops) > 1 or path.computed:
        return None
    if path.hops:
        hop = path.hops[0]
        if hop.relation.side != "fk" or path.field is None:
            return None
        return TestPlan(attr=path.field.attr, parent=hop.target, fk=hop.relation.fk_attr)
    if path.field is not None:
        return TestPlan(attr=path.field.attr)
    if relation is None:
        return None
    target = path.entity.target(relation)
    if relation.side == "fk":
        return TestPlan(target=target, fk=relation.fk_attr)
    if relation.side == "m2m":
        return TestPlan(target=target, ids=relation.ids_field)
    return None
