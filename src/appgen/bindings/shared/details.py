"""The detail views of the front-end apps: one record in sections and tabs (ADR 0003).

The shared UI templates in `templates/ui/details/` render the values of
this module. A detail view reads its record by ID, and the related
records that its field paths go through. The values of a field path are
TypeScript expressions over the record (`record`) and the related records
(`lookups`), as in the list views (`appgen.bindings.shared.views`).
"""

from dataclasses import dataclass, field

from appgen.bindings.shared.auth import kind_operations
from appgen.bindings.shared.gaps import GapSpec, component_gap
from appgen.bindings.shared.views import (
    ActionPlan,
    FormRef,
    RelatedStep,
    ViewContext,
    action_paths,
    definition_display,
    label,
    state_ids,
    ts_key,
)
from appgen.dsl.model import Field
from appgen.dsl.storage import FILE_TYPES
from appgen.dsl.ui.common import States
from appgen.dsl.ui.states import effective_states
from appgen.dsl.ui.views import DetailSection, DetailTab, DetailView
from appgen.gen.naming import camel, kebab, pascal

_ROW = "record"


@dataclass(slots=True)
class SectionPlan:
    """A section of a detail view: a card with fields, or a generation gap."""

    name: str
    element_id: str
    title: str | None
    description: str | None
    fields: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The label and the JSX of each field."""
    grid: str = "grid gap-x-6 gap-y-4"
    """The Tailwind CSS classes of the field grid."""
    gap: GapSpec | None = None


_HISTORY_FORMATS = {
    "number",
    "currency",
    "percent",
    "date",
    "datetime",
    "relative_time",
    "boolean",
    "email",
    "url",
}
"""The formats of the values of the change log. The other formats show the value as text."""


@dataclass(frozen=True, slots=True)
class HistoryField:
    """A field or a relation of the change log of a history tab (ADR 0040)."""

    name: str
    """The name in the app definition: the key of the changes of an entry."""
    label: str
    format: str = "text"
    currency: str | None = None

    @property
    def key(self) -> str:
        return ts_key(self.name)


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """A relation of the change log: the display value of the related record of an ID."""

    name: str
    target: str
    text: str
    """The TypeScript text of the related record `item`."""

    @property
    def key(self) -> str:
        return ts_key(self.name)


@dataclass(slots=True)
class HistoryPlan:
    """A tab with the change log of the record (ADR 0040), and its restore."""

    api: str
    """The `HistoryApi` of the entity, for example `taskHistory`."""
    fields: list[HistoryField] = field(default_factory=list[HistoryField])
    records: list[HistoryRecord] = field(default_factory=list[HistoryRecord])
    restore: str | None = None
    """The update operation of the entity: without it, the tab has no restore."""


@dataclass(slots=True)
class TabPlan:
    """A tab of a detail view: sections, a list view of related records, or a gap."""

    name: str
    element_id: str
    label: str
    icon: str | None
    sections: list[SectionPlan] = field(default_factory=list[SectionPlan])
    view: str | None = None
    """The list view of the related records."""
    where: str | None = None
    """The TypeScript test of the related records, of `row` and `record`."""
    params: str | None = None
    """The query parameters of the related records, of `record`, for a view that sends its query."""
    gap: GapSpec | None = None
    history: HistoryPlan | None = None


@dataclass(slots=True)
class DetailPlan:
    """The values of a detail view that its template needs."""

    name: str
    view: DetailView
    entity: str
    title: str = ""
    """The JSX of the record title."""
    subtitle: str | None = None
    badges: list[str] = field(default_factory=list[str])
    sections: list[SectionPlan] = field(default_factory=list[SectionPlan])
    tabs: list[TabPlan] = field(default_factory=list[TabPlan])
    lookups: list[str] = field(default_factory=list[str])
    """The related entities that the view reads, sorted by name."""
    paths: list[str] = field(default_factory=list[str])
    """The field paths that the view shows: the title, the header, and the sections."""
    related: list[list[RelatedStep]] | None = None
    """With the API: the related records that the view loads by ID, in stages."""
    actions: list[ActionPlan] = field(default_factory=list[ActionPlan])
    forms: list[FormRef] = field(default_factory=list[FormRef])
    """The forms that the actions open in a dialog or a sheet."""
    imports: list[str] = field(default_factory=list[str])
    """The import lines of the actions, the gaps, and the list views."""
    states: States | None = None
    state_ids: list[str] = field(default_factory=list[str])
    uses: set[str] = field(default_factory=set[str])
    """The value components that the view uses, for its imports."""
    icons: set[str] = field(default_factory=set[str])

    @property
    def type(self) -> str:
        return pascal(self.entity)

    @property
    def var(self) -> str:
        return camel(self.entity)

    def code(self) -> str:
        """Return the TypeScript expressions of the view, to find the helpers that they call."""
        parts = [self.title, self.subtitle or "", *self.badges]
        sections = [*self.sections, *(s for tab in self.tabs for s in tab.sections)]
        parts += [jsx for s in sections for _, jsx in s.fields]
        parts += [(a.href or "") + (a.run or "") + (a.navigate_to or "") for a in self.actions]
        parts += [r.text for tab in self.tabs if tab.history for r in tab.history.records]
        return " ".join(parts)

    def entity_imports(self) -> list[tuple[str, list[str]]]:
        """Return the names that the view imports from each entity slice, in order."""
        names = {
            entity: [f"{camel(entity)}Api", f"type {pascal(entity)}"]
            for entity in dict.fromkeys([self.entity, *self.lookups])
        }
        for tab in self.tabs:
            if tab.history is None:
                continue
            if tab.history.api not in names[self.entity]:
                names[self.entity].insert(1, tab.history.api)
            for record in tab.history.records:
                names.setdefault(record.target, [f"{camel(record.target)}Api"])
        return list(names.items())

    def needs(self, name: str) -> bool:
        """Return True if the code of the view calls a helper, for example `pageHref`."""
        return f"{name}(" in self.code()

    def action(self, name: str | None) -> ActionPlan | None:
        """Return an action by name, if the template can render it."""
        return next((a for a in self.actions if a.name == name), None)


def section_grid(columns: int) -> str:
    """Return the Tailwind CSS classes of the field grid of a section with columns.

    The grid has one column on small screens, and two up to the large
    breakpoint.
    """
    classes = ["grid", "gap-x-6", "gap-y-4"]
    if columns >= 2:
        classes.append("sm:grid-cols-2")
    if columns >= 3:
        classes.append(f"lg:grid-cols-{columns}")
    return " ".join(classes)


def build_detail(ctx: ViewContext, name: str) -> DetailPlan:
    """Return the plan of a detail view."""
    definition = ctx.definition
    assert definition.ui is not None
    view = definition.ui.views[name]
    assert isinstance(view, DetailView)
    entity = view.entity
    plan = DetailPlan(name=name, view=view, entity=entity)
    paths: list[str] = []
    header = view.header
    title_path = (
        header.title if header and header.title else definition_display(definition.entities[entity])
    )
    paths.append(title_path)
    title = ctx.value(entity, title_path, row=_ROW)
    plan.title = (
        f"{{{title.text_expr}}}"
        if title.kind != "field" or title.type in FILE_TYPES
        else f'{{String({title.expr} ?? "")}}'
    )
    if header is not None:
        if header.subtitle:
            paths.append(header.subtitle)
            plan.subtitle = ctx.jsx(ctx.value(entity, header.subtitle, row=_ROW), plan)
        for path in header.badges:
            paths.append(path)
            value = ctx.value(entity, path, row=_ROW)
            if value.badge:
                value = ctx.value(entity, path, "badge", row=_ROW)
            plan.badges.append(ctx.jsx(value, plan))
    for section_name, section in view.sections.items():
        plan.sections.append(_section(ctx, plan, section_name, section, paths))
    for tab_name, tab in view.tabs.items():
        plan.tabs.append(_tab(ctx, plan, tab_name, tab, paths))
    plan.paths = paths
    plan.lookups = sorted(ctx.lookups_of(entity, paths))
    if ctx.server:
        plan.related = ctx.related(entity, paths + action_paths(view))
        plan.lookups = sorted({*plan.lookups, *(s.entity for st in plan.related for s in st)})
    plan.states = effective_states(definition, view)
    plan.state_ids = state_ids(definition, view)
    plan.actions = ctx.action_plans(entity, view.actions.items(), "row")
    plan.forms = ctx.form_refs(plan.actions)
    imports = {line for action in plan.actions for line in action.imports}
    for gap in [s.gap for s in plan.sections] + [
        g for tab in plan.tabs for g in [tab.gap, *(s.gap for s in tab.sections)]
    ]:
        if gap is not None:
            imports.add(f'import {{ {gap.name} }} from "{gap.module}.gen";')
    for tab in plan.tabs:
        if tab.view:
            imports.add(f'import {{ {pascal(tab.view)}View }} from "@/widgets/{kebab(tab.view)}";')
        if tab.history:
            names = "type HistoryField, HistoryList" if tab.history.fields else "HistoryList"
            imports.add(f'import {{ {names} }} from "@/shared/ui/history-list";')
    plan.imports = sorted(imports)
    plan.icons |= {a.action.icon for a in plan.actions if a.action.icon}
    plan.icons |= {tab.icon for tab in plan.tabs if tab.icon}
    states = plan.states
    plan.icons |= {s.icon for s in (states.empty, states.error) if s and s.icon}
    return plan


def _section(
    ctx: ViewContext, plan: DetailPlan, name: str, section: DetailSection, paths: list[str]
) -> SectionPlan:
    result = SectionPlan(
        name=name,
        element_id=section.id,
        title=section.title,
        description=section.description,
        grid=section_grid(section.columns),
    )
    if section.custom:
        result.gap = component_gap(ctx.definition, section.id)
        return result
    for path in section.fields:
        paths.append(path)
        value = ctx.value(plan.entity, path, row=_ROW)
        result.fields.append((value.label, ctx.jsx(value, plan, avatar=True, large=True)))
    return result


def _tab(
    ctx: ViewContext, plan: DetailPlan, name: str, tab: DetailTab, paths: list[str]
) -> TabPlan:
    result = TabPlan(name=name, element_id=tab.id, label=tab.label or label(name), icon=tab.icon)
    if tab.custom:
        result.gap = component_gap(ctx.definition, tab.id)
    elif tab.relation and tab.view:
        result.view = tab.view
        if ctx.view_plan(tab.view).server is not None:
            result.params = related_params(ctx, plan.entity, tab)
        else:
            result.where = related_test(ctx, plan.entity, tab.relation)
    elif tab.history:
        result.history = history_plan(ctx, plan.entity)
    for section_name, section in tab.sections.items():
        result.sections.append(_section(ctx, plan, section_name, section, paths))
    return result


def history_plan(ctx: ViewContext, entity_name: str) -> HistoryPlan:
    """Return the plan of a tab with the change log of a record (ADR 0040).

    The tab shows the label of each kept field, its values in the format
    of the field, and the display value of the related record of a
    relation. The restore needs the update operation of the entity.
    """
    definition = ctx.definition
    entity = definition.entities[entity_name]
    result = HistoryPlan(
        api=f"{camel(entity_name)}History",
        restore=kind_operations(definition, entity_name).get("update"),
    )
    for name in entity.history_members:
        member = entity.fields.get(name)
        if isinstance(member, Field):
            value = ctx.value(entity_name, name, row=_ROW)
            fmt = value.format if value.format in _HISTORY_FORMATS else "text"
            if value.currency_expr is not None:
                # The currency of the record can change: an old amount shows as a number.
                fmt = "number"
            currency = value.currency if fmt == "currency" else None
            result.fields.append(HistoryField(name, value.label, fmt, currency))
            continue
        relation = entity.relations[name]
        result.fields.append(HistoryField(name, relation.label or label(name)))
        target = relation.target
        display = definition_display(definition.entities[target])
        text = ctx.value(target, display, row="item").text_expr
        result.records.append(HistoryRecord(name, target, text))
    return result


def related_params(ctx: ViewContext, entity: str, tab: DetailTab) -> str:
    """Return the query parameters of the records of a tab of `record`, as TypeScript.

    A `one_to_many` relation gives the foreign key of the inverse relation,
    and a `many_to_many` relation gives `id`, the list of IDs of the record.
    """
    relation = ctx.definition.entities[entity].relations[tab.relation or ""]
    endpoint = ctx.endpoints[relation.target]
    if relation.kind == "many_to_many":
        element_id, value = tab.id, f"{_ROW}.{camel(tab.relation or '')}"
    else:
        inverse = ctx.definition.entities[relation.target].relations[relation.inverse or ""]
        element_id, value = inverse.id, f"{_ROW}.id"
    name = endpoint.params[element_id][0]
    return f"{{ {ts_key(name)}: {value} }}"


def related_test(ctx: ViewContext, entity: str, relation_name: str) -> str:
    """Return the TypeScript test of the records of a relation of `record`, of `row`.

    A `one_to_many` relation tests the foreign key of the inverse relation,
    and a `many_to_many` relation tests the list of IDs of the record.
    """
    definition = ctx.definition
    relation = definition.entities[entity].relations[relation_name]
    if relation.kind == "many_to_many":
        return f"{_ROW}.{camel(relation_name)}.includes(row.id)"
    # The definition check makes sure that a one_to_many relation has an inverse.
    inverse = relation.inverse or ""
    return f"row.{camel(inverse)}Id === {_ROW}.id"
