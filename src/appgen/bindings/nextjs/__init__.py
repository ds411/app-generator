"""The Next.js 16 binding: a full-stack TypeScript app.

The app uses the App Router, TypeScript in strict mode, Tailwind CSS,
and pnpm. Its code follows Feature-Sliced Design (FSD): the Next.js
`app/` folder in the root holds only the routes, and the FSD layers
`app`, `pages`, `widgets`, `features`, `entities`, and `shared` are
folders in `src/`. Each route renders the page of its slice in
`src/pages`.
"""

import json
from pathlib import Path
from typing import Any

from appgen.bindings.nextjs.model import FSD_LAYERS, context
from appgen.gen.binding import Binding, Output


def to_json(value: Any) -> str:
    """Return a value as JSON with an indent of two spaces, as the Node.js tools write it."""
    return json.dumps(value, indent=2, ensure_ascii=False)


_PAGE = "src/pages/{{ nextjs.pages[name].slice }}"

BINDING = Binding(
    name="nextjs",
    description="A Next.js 16 app with TypeScript, FSD, and pnpm.",
    template_dir=Path(__file__).parent / "templates",
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
        Output(template="src/app/styles/globals.css.j2", path="src/app/styles/globals.css"),
        Output(template="src/pages/slice/index.ts.j2", path=_PAGE + "/index.ts", for_each="page"),
        Output(
            template="src/pages/slice/ui/page.tsx.j2",
            path=_PAGE + "/ui/{{ nextjs.pages[name].slice }}-page.tsx",
            for_each="page",
        ),
        Output(template="src/shared/config/index.ts.j2", path="src/shared/config/index.ts"),
        Output(template="src/shared/config/app.ts.j2", path="src/shared/config/app.ts"),
    ),
    covers=frozenset({"app", "page"}),
    gap_rule=Output(template="gaps/gap.ts.j2", path="src/gaps/{{ element_id }}.ext.ts"),
    context=context,
    filters={"json": to_json},
)
