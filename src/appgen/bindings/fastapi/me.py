"""The value `$me`, the signed-in user, in the FastAPI app: the generated tests.

A total of a computed field or a dashboard widget with `$me` in its filter
gives the records of the user of the token of each request: the SQL has
`me()` of `app/core/db.py`, a parameter that the database reads at each
run of a statement. The app keeps the user of the token of each request
(`remember_user` of `app/core/auth.py`), also for the public endpoints.

The generated tests store records of two users, and read each value with
the token of each user, and without a token. A test plans only the cases
that it knows: a total `count(...)` alone in its computed field, a stat
widget with `count`, and a list widget, each with a filter of only `$me`
values (`eq`).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import JsonValue

from appgen.bindings.fastapi.dashboards import PyDashboard, PyWidget
from appgen.bindings.fastapi.queries import resolve_path
from appgen.dsl.auth import ME
from appgen.dsl.expressions import Total, parse_expression
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.dashboards import ListWidget, StatWidget

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity

type MeKind = Literal["total", "stat", "list"]


@dataclass(frozen=True, slots=True)
class PyMeTest:
    """A generated test of a value with `$me`: the records of two users, and the reads."""

    name: str
    """The end of the name of the test function, for example `lesson_my_submissions`."""
    element_id: str
    """The computed field or the widget."""
    kind: MeKind
    records: PyEntity
    """The entity of the records that the filter counts or lists."""
    user_attrs: tuple[str, ...]
    """The foreign key attributes of the records to the user entity: the relations of `$me`."""
    path: str
    """The URL of the read: an f-string of `record`, the record of the total."""
    owner: PyEntity | None = None
    """For a total: the entity with the computed field. The test stores one record of it."""
    link: str | None = None
    """For a total: the foreign key attribute of the records to the record of the total."""
    key: str = "value"
    """For a total: the key of the computed field in the JSON of the record."""
    limit: int = 0
    """For a list widget: the most records of the list."""


def _me_paths(record_filter: dict[str, JsonValue]) -> list[str] | None:
    """Return the paths of a filter of only `$me` values (`eq`), or None for another filter."""
    paths: list[str] = []
    for path, condition in record_filter.items():
        if condition != ME and condition != {"eq": ME}:
            return None
        paths.append(path)
    return paths or None


def _user_attrs(entity: PyEntity, paths: list[str]) -> tuple[str, ...] | None:
    """Return the foreign key attributes of direct relations, or None for another path."""
    found: list[str] = []
    for path in paths:
        resolved = resolve_path(entity, path)
        relation = resolved.relation
        if resolved.hops or relation is None or relation.side != "fk" or relation.fk_attr is None:
            return None
        found.append(relation.fk_attr)
    return tuple(found)


def me_tests(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    dashboards: dict[str, PyDashboard],
) -> list[PyMeTest]:
    """Return the generated tests of the totals and the widgets with `$me`, in source order."""
    if definition.auth is None:
        return []
    found: list[PyMeTest] = []
    for entity in entities.values():
        found += _total_tests(definition, entity)
    for dashboard in dashboards.values():
        for widget in dashboard.widgets:
            test = _widget_test(definition, dashboard, widget)
            if test is not None:
                found.append(test)
    return found


def _total_tests(definition: AppDefinition, entity: PyEntity) -> list[PyMeTest]:
    """Return the tests of the computed fields of an entity that count the records of the user."""
    read = next((o for o in entity.operations if o.kind == "read" and o.path == "/{id}"), None)
    if read is None:
        return []
    fields = definition.entities[entity.name].fields
    found: list[PyMeTest] = []
    for c in entity.computed:
        dsl = fields[c.name]
        expression = parse_expression(c.source)
        paths = _me_paths(dict(dsl.filter or {}))
        if not isinstance(expression, Total) or expression.function != "count" or paths is None:
            continue
        total = c.totals[str(expression)]
        if total.relation.side == "m2m":
            continue
        inverse = next(r for r in total.target.relations if r.name == total.relation.back_populates)
        attrs = _user_attrs(total.target, paths)
        if attrs is None or inverse.fk_attr is None:
            continue
        found.append(
            PyMeTest(
                name=f"{entity.snake}_{c.name}",
                element_id=c.id,
                kind="total",
                records=total.target,
                user_attrs=attrs,
                path=entity.path + "/{record.id}",
                owner=entity,
                link=inverse.fk_attr,
                key=c.name,
            )
        )
    return found


def _widget_test(
    definition: AppDefinition, dashboard: PyDashboard, widget: PyWidget
) -> PyMeTest | None:
    """Return the test of a stat widget with `count` or of a list widget with `$me`, or None."""
    assert definition.ui is not None
    source = definition.ui.dashboards[dashboard.name].widgets[widget.name]
    if not isinstance(source, StatWidget | ListWidget) or source.period_field is not None:
        return None
    if isinstance(source, StatWidget) and source.aggregate != "count":
        return None
    paths = _me_paths(dict(source.filter))
    attrs = _user_attrs(widget.entity, paths) if paths is not None else None
    if attrs is None:
        return None
    return PyMeTest(
        name=f"{dashboard.module}_{widget.name}",
        element_id=widget.id,
        kind="stat" if isinstance(source, StatWidget) else "list",
        records=widget.entity,
        user_attrs=attrs,
        path=dashboard.path + widget.path,
        limit=widget.limit,
    )
