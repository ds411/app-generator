"""The Next.js 16 binding: a full-stack TypeScript app.

The app uses the App Router, TypeScript in strict mode, Tailwind CSS,
shadcn/ui, Drizzle ORM with Postgres, and pnpm. Its code follows
Feature-Sliced Design (FSD): the Next.js `app/` folder in the root
holds only the routes, and the FSD layers `app`, `pages`, `widgets`,
`features`, `entities`, and `shared` are folders in `src/`. Each
route renders the page of its slice in `src/pages`.
"""

from pathlib import Path

from appgen.bindings import shared
from appgen.bindings.nextjs import db
from appgen.bindings.nextjs.model import FSD_LAYERS, context
from appgen.bindings.shared import forms, shadcn, typescript, ui, views
from appgen.bindings.shared.auth import auth_rules, kind_operations, public_kinds
from appgen.bindings.shared.gaps import gap_rules, gap_spec
from appgen.bindings.shared.i18n import finish, i18n_rules
from appgen.gen.binding import Binding, Output

_PAGE = "src/pages/{{ nextjs.pages[name].slice }}"
_ENTITY = "src/entities/{{ name | kebab }}"
_OPERATION = "src/features/{{ name | kebab }}"
_CUSTOM_OP = "element.kind == 'custom'"
_INTEGRATION = "src/shared/api/{{ ts_apis[name].folder }}"

# The app shell: the layouts, the menus, the breadcrumbs, and the search
# (shared templates, see `appgen.bindings.shared.ui`). Each layout with
# pages is a route group in `app/`.
_APP_SHELL = (
    Output(template="ui/config/pages.ts.j2", path="src/shared/config/pages.ts"),
    Output(template="ui/lib/pages.ts.j2", path="src/shared/lib/pages.ts"),
    Output(template="ui/lib/use-media-query.ts.j2", path="src/shared/lib/use-media-query.ts"),
    Output(template="ui/lib/use-resource.ts.j2", path="src/shared/lib/use-resource.ts"),
    Output(template="src/shared/lib/router.tsx.j2", path="src/shared/lib/router.tsx"),
    Output(
        template="src/shared/lib/access.tsx.j2",
        path="src/shared/lib/access.tsx",
        when="definition.access",
    ),
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
        template="app/group/layout.tsx.j2",
        path="app/({{ name | kebab }})/layout.tsx",
        for_each="layout",
        when="ui_plan.pages_of(name)",
    ),
    Output(
        template="app/group/bare-layout.tsx.j2",
        path="app/(bare)/layout.tsx",
        when="ui_plan.pages_of(none)",
    ),
    Output(template="app/not-found.tsx.j2", path="app/not-found.tsx"),
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

# One rule for each shadcn/ui component and hook. The app gets only the
# components that its UI uses (ADR 0003, "Binding map").
_SHADCN = tuple(
    Output(
        template=component.template,
        path=f"src/shared/ui/{name}.tsx",
        when=f"{name!r} in nextjs.shadcn",
    )
    for name, component in sorted(shadcn.registry().items())
)
_HOOKS = tuple(
    Output(
        template=f"shadcn/{hook}.ts.j2",
        path=f"src/shared/lib/{hook}.ts",
        when=f"{hook!r} in nextjs.hooks",
    )
    for hook in sorted({h for c in shadcn.registry().values() for h in c.hooks})
)

BINDING = Binding(
    name="nextjs",
    description="A Next.js 16 app with TypeScript, FSD, and pnpm.",
    template_dir=Path(__file__).parent / "templates",
    shared_template_dirs=(shared.TEMPLATE_DIR,),
    outputs=(
        Output(template="package.json.j2", path="package.json"),
        Output(template="pnpm-workspace.yaml.j2", path="pnpm-workspace.yaml"),
        Output(template="tsconfig.json.j2", path="tsconfig.json"),
        Output(template="next.config.ts.j2", path="next.config.ts"),
        Output(template="eslint.config.mjs.j2", path="eslint.config.mjs"),
        Output(template="postcss.config.mjs.j2", path="postcss.config.mjs"),
        Output(template="gitignore.j2", path=".gitignore"),
        Output(template="Dockerfile.j2", path="Dockerfile"),
        Output(template="dockerignore.j2", path=".dockerignore"),
        Output(template="compose.yaml.j2", path="compose.yaml"),
        Output(template="README.md.j2", path="README.md"),
        Output(template="root-pages-readme.md.j2", path="pages/README.md"),
        *(
            Output(template="layer-readme.md.j2", path=f"src/{layer}/README.md")
            for layer, _ in FSD_LAYERS
        ),
        Output(template="app/layout.tsx.j2", path="app/layout.tsx"),
        *_APP_SHELL,
        *views.view_rules(),
        *i18n_rules(),
        Output(
            template="src/shared/lib/i18n-server.ts.j2",
            path="src/shared/lib/i18n-server.ts",
            when="i18n",
        ),
        *auth_rules(),
        *forms.form_rules(),
        Output(
            template="app/page.tsx.j2",
            path="{{ nextjs.pages[name].route_file }}",
            for_each="page",
        ),
        Output(template="theme/globals.css.j2", path="src/app/styles/globals.css"),
        Output(template="src/app/providers/index.tsx.j2", path="src/app/providers/index.tsx"),
        Output(
            template="src/features/toggle-theme/index.ts.j2",
            path="src/features/toggle-theme/index.ts",
            when="nextjs.mode_toggle",
        ),
        Output(
            template="theme/mode-toggle.tsx.j2",
            path="src/features/toggle-theme/ui/mode-toggle.tsx",
            when="nextjs.mode_toggle",
        ),
        Output(template="src/pages/slice/index.ts.j2", path=_PAGE + "/index.ts", for_each="page"),
        Output(
            template="src/pages/slice/ui/page.tsx.j2",
            path=_PAGE + "/ui/{{ nextjs.pages[name].slice }}-page.tsx",
            for_each="page",
        ),
        Output(template="src/shared/config/index.ts.j2", path="src/shared/config/index.ts"),
        Output(template="src/shared/config/app.ts.j2", path="src/shared/config/app.ts"),
        Output(template="components.json.j2", path="components.json"),
        Output(template="shadcn/lib/utils.ts.j2", path="src/shared/lib/utils.ts"),
        Output(template="src/shared/lib/theme.ts.j2", path="src/shared/lib/theme.ts"),
        Output(template="drizzle.config.ts.j2", path="drizzle.config.ts"),
        Output(template="instrumentation.ts.j2", path="instrumentation.ts"),
        Output(template="env.example.j2", path=".env.example"),
        Output(template="src/shared/db/index.ts.j2", path="src/shared/db/index.ts"),
        Output(template="src/shared/db/client.ts.j2", path="src/shared/db/client.ts"),
        Output(template="src/shared/db/connect.ts.j2", path="src/shared/db/connect.ts"),
        Output(template="src/shared/db/migrate.ts.j2", path="src/shared/db/migrate.ts"),
        Output(template="src/shared/db/seed.ts.j2", path="src/shared/db/seed.ts"),
        Output(template="src/shared/db/seed-data.ts.j2", path="src/shared/db/seed-data.ts"),
        Output(template="src/shared/db/run-seed.ts.j2", path="src/shared/db/run-seed.ts"),
        Output(template="src/shared/db/schema/index.ts.j2", path="src/shared/db/schema/index.ts"),
        *(
            Output(
                template=template,
                path=path,
                when="definition.access" if "access" in template else "definition.auth",
            )
            for template, path in (
                ("src/shared/db/schema/credentials.ts.j2", "src/shared/db/schema/credentials.ts"),
                ("src/shared/auth/session.ts.j2", "src/shared/auth/session.ts"),
                ("src/shared/auth/password.ts.j2", "src/shared/auth/password.ts"),
                ("src/shared/auth/actions.ts.j2", "src/shared/auth/actions.ts"),
                ("src/shared/auth/index.ts.j2", "src/shared/auth/index.ts"),
                ("src/shared/auth/access.ts.j2", "src/shared/auth/access.ts"),
                ("app/sign-in/page.tsx.j2", "app/sign-in/page.tsx"),
            )
        ),
        *(
            Output(
                template=template,
                path=path,
                when="definition.auth and definition.auth.password_reset",
                extension=template.endswith(".ext.ts.j2"),
            )
            for template, path in (
                ("src/shared/auth/password-reset.ts.j2", "src/shared/auth/password-reset.ts"),
                (
                    "src/shared/auth/password-reset.ext.ts.j2",
                    "src/shared/auth/password-reset.ext.ts",
                ),
                ("app/forgot-password/page.tsx.j2", "app/forgot-password/page.tsx"),
                ("app/reset-password/page.tsx.j2", "app/reset-password/page.tsx"),
            )
        ),
        *(
            Output(template=template, path=path, when="definition.auth and definition.auth.sign_up")
            for template, path in (
                (
                    "src/features/sign-up/api/sign-up-action.ts.j2",
                    "src/features/sign-up/api/sign-up-action.ts",
                ),
                ("src/features/sign-up/api/sign-up.ts.j2", "src/features/sign-up/api/sign-up.ts"),
                ("app/sign-up/page.tsx.j2", "app/sign-up/page.tsx"),
            )
        ),
        Output(
            template="src/shared/db/schema/table.ts.j2",
            path="src/shared/db/schema/{{ nextjs.tables_by_entity[name].module }}.ts",
            for_each="entity",
        ),
        Output(template="src/shared/db/repository.ts.j2", path="src/shared/db/repository.ts"),
        Output(template="src/shared/api/types.ts.j2", path="src/shared/api/types.ts"),
        Output(template="src/shared/api/errors.ts.j2", path="src/shared/api/errors.ts"),
        Output(template="src/shared/api/client.ts.j2", path="src/shared/api/client.ts"),
        Output(template="src/shared/api/server.ts.j2", path="src/shared/api/server.ts"),
        Output(template="src/shared/api/index.ts.j2", path="src/shared/api/index.ts"),
        *(
            Output(
                template=f"src/entities/entity/{template}.j2",
                path=f"{_ENTITY}/{path}",
                for_each="entity",
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("server.ts", "server.ts"),
                ("model/types.ts", "model/types.ts"),
                ("model/meta.ts", "model/meta.ts"),
                ("model/schema.ts", "model/schema.ts"),
                ("api/repository.ts", "api/{{ name | kebab }}-repository.ts"),
                ("api/actions.ts", "api/{{ name | kebab }}-actions.ts"),
                ("api/api.ts", "api/{{ name | kebab }}-api.ts"),
            )
        ),
        *(
            Output(
                template=f"src/features/operation/{template}.j2",
                path=f"{_OPERATION}/{path}",
                for_each="operation",
                when=_CUSTOM_OP,
                extension=template.endswith(".ext.ts"),
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("api/api.ts", "api/{{ name | kebab }}-api.ts"),
                ("api/operation.gen.ts", "api/{{ name | kebab }}.gen.ts"),
                ("api/operation.ext.ts", "api/{{ name | kebab }}.ext.ts"),
            )
        ),
        Output(
            template="integrations/third-party.ts.j2",
            path="src/shared/api/third-party.ts",
            when="ts_apis",
        ),
        *(
            Output(
                template=f"integrations/{template}.j2",
                path=f"{_INTEGRATION}/{template}",
                for_each="api",
            )
            for template in ("index.ts", "types.ts", "client.ts")
        ),
        *gap_rules(),
        *_SHADCN,
        *_HOOKS,
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
        | {"detail_view", "detail_header", "detail_section", "detail_tab", "sort"}
        | {"dashboard", "grid", "grid_override", "stat_widget", "chart_widget", "list_widget"}
        | {"form", "form_section", "form_field", "form_on_success"}
        | {"field_rules", "required_rule", "length_rule", "number_rule", "pattern_rule"}
        | {"compare_rule"}
        | {"entity_compare_rule", "entity_unique_rule", "entity_overlap_rule"}
        | {"custom_widget", "custom_rule", "custom_action"}
        | {"page_content", "page_arrangement", "navigate_action", "form_action", "operation_action"}
        | {"view_responsive", "motion"}
        | {"translations", "language"}
        | {"workflow", "transition"}
        | {"auth", "sign_up", "password_reset", "access", "role"}
        | {"confirm", "on_success", "ui", "defaults", "states", "state", "loading_state"}
        | {"api", "api_operation"}
    ),
    gap_rule=Output(template="gaps/gap.ts.j2", path="src/gaps/{{ element_id }}.ext.ts"),
    context=context,
    finish=finish,
    filters={"json": typescript.to_json},
    helpers=typescript.HELPERS
    | ui.HELPERS
    | views.HELPERS
    | {"public_kinds": public_kinds, "kind_operations": kind_operations}
    | {"gap_spec": gap_spec, "rule_key": db.record_key, "rule_keys": db.record_keys},
    stub_markers=("TODO(appgen)", "Not implemented yet"),
)
