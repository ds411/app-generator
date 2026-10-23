"""The detail views of the front-end apps: one record in sections and tabs (ADR 0003).

The shared UI templates in `templates/ui/details/` render the values of
this module. A detail view reads its record by ID, and the related
records that its field paths go through. The values of a field path are
TypeScript expressions over the record (`record`) and the related records
(`lookups`), as in the list views (`appgen.bindings.shared.views`).
"""

from dataclasses import dataclass, field

from appgen.bindings.shared.gaps import GapSpec, component_gap
from appgen.bindings.shared.views import (
    ActionPlan,
    FormRef,
    ViewContext,
    definition_display,
    label,
    state_ids,
)
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
    gap: GapSpec | None = None


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
        return " ".join(parts)

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
        f"{{{title.text_expr}}}" if title.kind != "field" else f'{{String({title.expr} ?? "")}}'
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
    plan.lookups = sorted(ctx.lookups_of(entity, paths))
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
        result.fields.append((value.label, ctx.jsx(value, plan, avatar=True)))
    return result


def _tab(
    ctx: ViewContext, plan: DetailPlan, name: str, tab: DetailTab, paths: list[str]
) -> TabPlan:
    result = TabPlan(name=name, element_id=tab.id, label=tab.label or label(name), icon=tab.icon)
    if tab.custom:
        result.gap = component_gap(ctx.definition, tab.id)
    elif tab.relation and tab.view:
        result.view = tab.view
        result.where = related_test(ctx, plan.entity, tab.relation)
    for section_name, section in tab.sections.items():
        result.sections.append(_section(ctx, plan, section_name, section, paths))
    return result


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
