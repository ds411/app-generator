"""The Next.js 16 binding: a full-stack TypeScript app.

The app uses the App Router, TypeScript in strict mode, Tailwind CSS,
shadcn/ui, Drizzle ORM with Postgres, and pnpm. Its code follows
Feature-Sliced Design (FSD): the Next.js `app/` folder in the root
holds only the routes, and the FSD layers `app`, `pages`, `widgets`,
`features`, `entities`, and `shared` are folders in `src/`. Each
route renders the page of its slice in `src/pages`.
"""

import json
from pathlib import Path
from typing import Any

from appgen.bindings import shared
from appgen.bindings.nextjs.model import FSD_LAYERS, context
from appgen.bindings.shared import shadcn
from appgen.gen.binding import Binding, Output


def to_json(value: Any) -> str:
    """Return a value as JSON with an indent of two spaces, as the Node.js tools write it."""
    return json.dumps(value, indent=2, ensure_ascii=False)


_PAGE = "src/pages/{{ nextjs.pages[name].slice }}"

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
        *_SHADCN,
        *_HOOKS,
    ),
    covers=frozenset(
        {"app", "page", "entity", "field", "relation", "theme", "tokens", "token_group", "token"}
    ),
    gap_rule=Output(template="gaps/gap.ts.j2", path="src/gaps/{{ element_id }}.ext.ts"),
    context=context,
    filters={"json": to_json},
)
