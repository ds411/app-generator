"""The React 19 binding: a standalone front-end app with mock data.

The app uses TypeScript, Vite, React Router, and pnpm. Its code follows
Feature-Sliced Design (FSD): the layers `app`, `pages`, `widgets`,
`features`, `entities`, and `shared` are folders in `src/`.
"""

from pathlib import Path
from typing import Annotated, Literal

import pydantic

from appgen.bindings import shared
from appgen.bindings.react.api_client import DATA_KEY
from appgen.bindings.react.gaps import gap_spec
from appgen.bindings.react.helpers import HELPERS, context, to_json
from appgen.bindings.shared import forms, shadcn, ui, views
from appgen.bindings.shared.auth import auth_rules
from appgen.bindings.shared.i18n import finish, i18n_rules
from appgen.bindings.shared.mock_data import MOCK_COUNT_KEY
from appgen.gen.binding import Binding, ExtensionKey, Output

_PAGE = "src/pages/{{ name | kebab }}"
_ENTITY = "src/entities/{{ name | kebab }}"
_GAP = "{{ gap_spec(definition, element_id, element_kind).base }}"
_CUSTOM_OP = "element.kind == 'custom'"

# The generation gaps (ADR 0005): a generated file and an extension file
# for each custom element. See `appgen.bindings.react.gaps`.
_COMPONENT_GAPS = (
    ("page_content", "element.custom"),
    ("detail_tab", "element.custom"),
    ("detail_section", "element.custom"),
    ("custom_widget", None),
    ("form_field", "element.widget == 'custom'"),
)
_FUNCTION_GAPS = ("custom_rule", "custom_action")

# One rule for each shadcn/ui component and hook of the shared templates.
# The app gets only the components that its UI uses (ADR 0003).
_SHADCN = tuple(
    Output(
        template=component.template,
        path=f"src/shared/ui/{name}.tsx",
        when=f"{name!r} in react.shadcn",
    )
    for name, component in sorted(shadcn.registry().items())
)
_HOOKS = tuple(
    Output(
        template=f"shadcn/{hook}.ts.j2",
        path=f"src/shared/lib/{hook}.ts",
        when=f"{hook!r} in react.hooks",
    )
    for hook in sorted({h for c in shadcn.registry().values() for h in c.hooks})
)


# The app shell: the layouts, the menus, the breadcrumbs, and the search
# (shared templates, see `appgen.bindings.shared.ui`).
_APP_SHELL = (
    Output(template="ui/config/pages.ts.j2", path="src/shared/config/pages.ts"),
    Output(template="ui/lib/pages.ts.j2", path="src/shared/lib/pages.ts"),
    Output(template="ui/lib/use-media-query.ts.j2", path="src/shared/lib/use-media-query.ts"),
    Output(template="ui/lib/use-resource.ts.j2", path="src/shared/lib/use-resource.ts"),
    Output(template="src/shared/lib/router.tsx.j2", path="src/shared/lib/router.tsx"),
    Output(
        template="ui/widgets/layout/layout.tsx.j2",
        path="src/widgets/layouts/ui/{{ name | kebab }}-layout.tsx",
        for_each="layout",
    ),
    Output(
        template="ui/widgets/layout/index.ts.j2",
        path="src/widgets/layouts/index.ts",
        when="ui_plan.layouts",
    ),
    Output(
        template="ui/widgets/navigation/menu.tsx.j2",
        path="src/widgets/navigation/ui/{{ name | kebab }}-menu.tsx",
        for_each="menu",
        when="name in ui_plan.menus",
    ),
    Output(
        template="ui/widgets/navigation/index.ts.j2",
        path="src/widgets/navigation/index.ts",
        when="ui_plan.menus",
    ),
    *(
        Output(
            template=f"ui/widgets/breadcrumbs/{template}.j2",
            path=f"src/widgets/page-breadcrumbs/{path}",
            when="ui_plan.breadcrumbs",
        )
        for template, path in (
            ("index.ts", "index.ts"),
            ("page-breadcrumbs.tsx", "ui/page-breadcrumbs.tsx"),
            ("record-labels.ts", "model/record-labels.ts"),
        )
    ),
    Output(
        template="ui/features/search-pages/index.ts.j2",
        path="src/features/search-pages/index.ts",
        when="ui_plan.search",
    ),
    Output(
        template="ui/features/search-pages/page-search.tsx.j2",
        path="src/features/search-pages/ui/page-search.tsx",
        when="ui_plan.search",
    ),
    Output(template="ui/widgets/page-header/index.ts.j2", path="src/widgets/page-header/index.ts"),
    Output(
        template="ui/widgets/page-header/page-header.tsx.j2",
        path="src/widgets/page-header/ui/page-header.tsx",
    ),
    Output(template="src/pages/not-found/index.ts.j2", path="src/pages/not-found/index.ts"),
    Output(
        template="ui/pages/not-found.tsx.j2",
        path="src/pages/not-found/ui/not-found-page.tsx",
    ),
)


def _gap_rules(template: str, suffix: str, kind: str, when: str | None = None) -> list[Output]:
    """Return the rules of the generated file and the extension file of a gap."""
    return [
        Output(
            template=f"gap/{template}.{part}.{suffix}.j2",
            path=f"{_GAP}.{part}.{suffix}",
            for_each=kind,
            when=when,
            extension=part == "ext",
        )
        for part in ("gen", "ext")
    ]


BINDING = Binding(
    name="react",
    description="A React 19 app with Vite, React Router, FSD, and mock data.",
    template_dir=Path(__file__).parent / "templates",
    shared_template_dirs=(shared.TEMPLATE_DIR,),
    outputs=(
        Output(template="package.json.j2", path="package.json"),
        Output(template="tsconfig.json.j2", path="tsconfig.json"),
        Output(template="vite.config.ts.j2", path="vite.config.ts"),
        Output(template="eslint.config.js.j2", path="eslint.config.js"),
        Output(template="index.html.j2", path="index.html"),
        Output(template="gitignore.j2", path=".gitignore"),
        Output(template="Dockerfile.j2", path="Dockerfile"),
        Output(template="dockerignore.j2", path=".dockerignore"),
        Output(template="nginx.conf.j2", path="nginx.conf"),
        Output(template="README.md.j2", path="README.md"),
        Output(template="src/app/main.tsx.j2", path="src/app/main.tsx"),
        Output(template="src/app/app.tsx.j2", path="src/app/app.tsx"),
        Output(template="src/app/router.tsx.j2", path="src/app/router.tsx"),
        *_APP_SHELL,
        *views.view_rules(),
        *i18n_rules(),
        *auth_rules(),
        Output(
            template="src/shared/auth/index.ts.j2",
            path="src/shared/auth/index.ts",
            when="definition.auth",
        ),
        Output(
            template="src/app/auth/require-auth.tsx.j2",
            path="src/app/auth/require-auth.tsx",
            when="definition.auth",
        ),
        *forms.form_rules(),
        Output(template="src/vite-env.d.ts.j2", path="src/vite-env.d.ts"),
        Output(template="src/layer.md.j2", path="src/widgets/README.md"),
        Output(template="src/layer.md.j2", path="src/features/README.md"),
        Output(template="src/layer.md.j2", path="src/entities/README.md"),
        Output(template="src/shared/config/app.ts.j2", path="src/shared/config/app.ts"),
        Output(template="components.json.j2", path="components.json"),
        Output(template="theme/globals.css.j2", path="src/app/styles/index.css"),
        Output(template="src/app/providers/index.tsx.j2", path="src/app/providers/index.tsx"),
        Output(template="src/app/layout/root-layout.tsx.j2", path="src/app/layout/root-layout.tsx"),
        Output(
            template="src/features/toggle-theme/index.ts.j2",
            path="src/features/toggle-theme/index.ts",
            when="react.mode_toggle",
        ),
        Output(
            template="theme/mode-toggle.tsx.j2",
            path="src/features/toggle-theme/ui/mode-toggle.tsx",
            when="react.mode_toggle",
        ),
        Output(template="shadcn/lib/utils.ts.j2", path="src/shared/lib/utils.ts"),
        Output(template="src/shared/lib/theme.ts.j2", path="src/shared/lib/theme.ts"),
        *_SHADCN,
        *_HOOKS,
        Output(template="src/shared/api/types.ts.j2", path="src/shared/api/types.ts"),
        Output(
            template="src/shared/api/query.ts.j2",
            path="src/shared/api/query.ts",
            when="not react.api",
        ),
        Output(
            template="src/shared/api/mock-store.ts.j2",
            path="src/shared/api/mock-store.ts",
            when="not react.api",
        ),
        Output(
            template="src/shared/api/http.ts.j2", path="src/shared/api/http.ts", when="react.api"
        ),
        Output(
            template="src/shared/api/http-store.ts.j2",
            path="src/shared/api/http-store.ts",
            when="react.api",
        ),
        Output(template="src/shared/api/index.ts.j2", path="src/shared/api/index.ts"),
        Output(
            template="src/entities/entity/index.ts.j2",
            path=_ENTITY + "/index.ts",
            for_each="entity",
        ),
        Output(
            template="src/entities/entity/model/types.ts.j2",
            path=_ENTITY + "/model/types.ts",
            for_each="entity",
        ),
        Output(
            template="src/entities/entity/model/schema.ts.j2",
            path=_ENTITY + "/model/schema.ts",
            for_each="entity",
            when="ui_forms.names",
        ),
        Output(
            template="src/entities/entity/model/meta.ts.j2",
            path=_ENTITY + "/model/meta.ts",
            for_each="entity",
        ),
        Output(
            template="src/entities/entity/api/api.ts.j2",
            path=_ENTITY + "/api/{{ name | kebab }}-api.ts",
            for_each="entity",
        ),
        Output(
            template="src/entities/entity/api/mock-data.ts.j2",
            path=_ENTITY + "/api/{{ name | kebab }}-mock-data.ts",
            for_each="entity",
            when="not react.api",
        ),
        Output(
            template="src/pages/page/index.ts.j2",
            path=_PAGE + "/index.ts",
            for_each="page",
        ),
        Output(
            template="src/pages/page/ui/page.tsx.j2",
            path=_PAGE + "/ui/{{ name | kebab }}-page.tsx",
            for_each="page",
        ),
        Output(
            template="src/features/operation/index.ts.j2",
            path="src/features/{{ name | kebab }}/index.ts",
            for_each="operation",
            when=_CUSTOM_OP,
        ),
        Output(
            template="src/features/operation/operation.gen.ts.j2",
            path=_GAP + ".gen.ts",
            for_each="operation",
            when=_CUSTOM_OP,
        ),
        Output(
            template="gap/function.ext.ts.j2",
            path=_GAP + ".ext.ts",
            for_each="operation",
            when=_CUSTOM_OP + " and not react.api",
            extension=True,
        ),
        *(
            rule
            for kind, when in _COMPONENT_GAPS
            for rule in _gap_rules("component", "tsx", kind, when)
        ),
        *(rule for kind in _FUNCTION_GAPS for rule in _gap_rules("function", "ts", kind)),
    ),
    covers=frozenset(
        {"app", "page", "entity", "field", "relation", "operation", "param"}
        | {"theme", "tokens", "token_group", "token"}
        | {"layout", "sidebar", "topbar", "content", "footer"}
        | {"layout_override", "sidebar_override", "topbar_override", "content_override"}
        | {"menu", "menu_group", "menu_item", "menu_sub_item"}
        | {"table_view", "cards_view", "board_view", "column", "card", "badge_ref", "board_column"}
        | {"calendar_view"}
        | {"search_filter", "select_filter", "boolean_filter", "date_range_filter", "pagination"}
        | {"badge_set", "badge_value"}
        | {"form", "form_section", "form_field", "form_on_success"}
        | {"field_rules", "required_rule", "length_rule", "number_rule", "pattern_rule"}
        | {"compare_rule"}
        | {"detail_view", "detail_header", "detail_section", "detail_tab", "sort"}
        | {"dashboard", "grid", "grid_override", "stat_widget", "chart_widget", "list_widget"}
        | {"custom_widget", "custom_rule", "custom_action"}
        | {"page_content", "page_arrangement", "navigate_action", "form_action", "operation_action"}
        | {"view_responsive", "motion"}
        | {"translations", "language"}
        | {"workflow", "transition"}
        | {"auth", "access", "role"}
        | {"confirm", "on_success", "ui", "defaults", "states", "state", "loading_state"}
    ),
    # The rules of the entities are rules of the back end. The React app has mock data.
    # The React app has no sign-up page (#269), no password reset pages
    # (#270), no owner rules (#273), and no sign-in with a provider (#271)
    # yet. The clients of the third-party APIs come with #265.
    excludes=frozenset(
        {"entity_compare_rule", "entity_unique_rule", "entity_overlap_rule", "api"}
        | {"sign_up", "password_reset", "record_rule", "provider"}
    ),
    context=context,
    finish=finish,
    filters={"json": to_json},
    helpers=HELPERS | ui.HELPERS | views.HELPERS | {"gap_spec": gap_spec},
    stub_markers=("TODO(appgen)", "Not implemented yet"),
    extension_keys=(
        ExtensionKey(
            name=MOCK_COUNT_KEY,
            kinds=frozenset({"entity"}),
            type=Annotated[int, pydantic.Field(ge=1)],
            description="The number of mock records of the entity (default: 12).",
        ),
        ExtensionKey(
            name=DATA_KEY,
            kinds=frozenset({"app"}),
            type=Literal["mock", "api"],
            description="The data of the app: `mock` (default) or `api`, the FastAPI app "
            "of the same definition.",
        ),
    ),
)
