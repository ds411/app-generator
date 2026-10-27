"""The secret links of the records (ADR 0049): the pages with `share`, for all bindings.

A page with `share` is a detail page. A link opens its shared page, for
example `/shared/lessons/{token}`, without a sign-in. The server gives
the record and the related records that the detail view shows, because
the guest may not read the lists of the entities. The stages of the
related records are the stages of `loadRelated` of the list views
(`ViewContext.related`).
"""

from dataclasses import dataclass, field

from appgen.bindings.shared.auth import kind_operations
from appgen.bindings.shared.details import build_detail
from appgen.bindings.shared.views import RelatedStep, ViewContext
from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.views import DetailView
from appgen.gen.binding import Output
from appgen.gen.naming import camel


@dataclass(slots=True)
class SharePlan:
    """The page with `share` of an entity, and the records that its shared page shows."""

    page: str
    """The name of the page."""
    page_id: str
    """The element ID of the page: the traces of the links name it."""
    entity: str
    view: str
    """The detail view of the page."""
    path: str
    """The path of the page, for example `/lessons/{id}`."""
    shared_path: str
    """The path of the shared page, for example `/shared/lessons/{token}`."""
    update: str
    """The update operation of the entity: a link needs its permission."""
    related: list[list[RelatedStep]] = field(default_factory=list[list[RelatedStep]])
    """The related records that the detail view shows, in the stages of `loadRelated`."""

    @property
    def shared_prefix(self) -> str:
        """The path of the shared page without the token, for example `/shared/lessons/`."""
        return self.shared_path.removesuffix("{token}")

    @property
    def related_entities(self) -> list[str]:
        """The entities of the related records, sorted by name."""
        return sorted({step.entity for stage in self.related for step in stage})

    def related_key(self, entity: str) -> str:
        """Return the key of the related records of an entity in the answer: `course`."""
        return camel(entity)


def share_plans(definition: AppDefinition) -> dict[str, SharePlan]:
    """Return the page with `share` of each entity that has one (the validator allows one)."""
    ui = definition.ui
    if ui is None or definition.auth is None:
        return {}
    ctx: ViewContext | None = None
    found: dict[str, SharePlan] = {}
    for name, page in definition.pages.items():
        content = page.content
        view = ui.views.get(content.view or "") if page.share and content is not None else None
        if not isinstance(view, DetailView) or content is None or content.view is None:
            continue
        ctx = ctx or ViewContext(definition)
        detail = build_detail(ctx, content.view)
        update = kind_operations(definition, view.entity).get("update")
        if update is None:
            continue
        found[view.entity] = SharePlan(
            page=name,
            page_id=page.id,
            entity=view.entity,
            view=content.view,
            path=page.path,
            shared_path=page.shared_path,
            update=update,
            related=ctx.related(view.entity, detail.paths),
        )
    return found


def share_rules() -> tuple[Output, ...]:
    """Return the output rules of the front ends: the button "Share", and the shared views.

    The bindings put `share_plans` in their context as `shares`.
    """
    return (
        *(
            Output(
                template=f"ui/features/share-record/{template}.j2",
                path=f"src/features/share-record/{path}",
                when="shares",
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("share-button.tsx", "ui/share-button.tsx"),
            )
        ),
        Output(
            template="ui/details/shared-view.tsx.j2",
            path="src/widgets/{{ name | kebab }}/ui/{{ name | kebab }}-shared-view.tsx",
            for_each="detail_view",
            when="shares.values() | selectattr('view', 'equalto', name) | list",
        ),
    )
