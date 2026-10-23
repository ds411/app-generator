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
from appgen.bindings.nextjs.model import FSD_LAYERS, context
from appgen.bindings.shared import shadcn, typescript
from appgen.bindings.shared.gaps import gap_rules, gap_spec
from appgen.gen.binding import Binding, Output

_PAGE = "src/pages/{{ nextjs.pages[name].slice }}"
_ENTITY = "src/entities/{{ name | kebab }}"
_OPERATION = "src/features/{{ name | kebab }}"
_CUSTOM_OP = "element.kind == 'custom'"

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
        Output(template="src/shared/db/migrate.ts.j2", path="src/shared/db/migrate.ts"),
        Output(template="src/shared/db/schema/index.ts.j2", path="src/shared/db/schema/index.ts"),
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
        *gap_rules(),
        *_SHADCN,
        *_HOOKS,
    ),
    covers=frozenset(
        {"app", "page", "entity", "field", "relation", "operation", "param"}
        | {"theme", "tokens", "token_group", "token"}
        | {"custom_widget", "custom_rule", "custom_action"}
    ),
    gap_rule=Output(template="gaps/gap.ts.j2", path="src/gaps/{{ element_id }}.ext.ts"),
    context=context,
    filters={"json": typescript.to_json},
    helpers=typescript.HELPERS | {"gap_spec": gap_spec},
)
