"""The React 19 binding: a standalone front-end app with mock data.

The app uses TypeScript, Vite, React Router, and pnpm. Its code follows
Feature-Sliced Design (FSD): the layers `app`, `pages`, `widgets`,
`features`, `entities`, and `shared` are folders in `src/`.
"""

from pathlib import Path

from appgen.bindings.react.helpers import HELPERS
from appgen.gen.binding import Binding, Output

_PAGE = "src/pages/{{ name | kebab }}"

BINDING = Binding(
    name="react",
    description="A React 19 app with Vite, React Router, FSD, and mock data.",
    template_dir=Path(__file__).parent / "templates",
    outputs=(
        Output(template="package.json.j2", path="package.json"),
        Output(template="tsconfig.json.j2", path="tsconfig.json"),
        Output(template="vite.config.ts.j2", path="vite.config.ts"),
        Output(template="eslint.config.js.j2", path="eslint.config.js"),
        Output(template="index.html.j2", path="index.html"),
        Output(template="gitignore.j2", path=".gitignore"),
        Output(template="README.md.j2", path="README.md"),
        Output(template="src/app/main.tsx.j2", path="src/app/main.tsx"),
        Output(template="src/app/app.tsx.j2", path="src/app/app.tsx"),
        Output(template="src/app/router.tsx.j2", path="src/app/router.tsx"),
        Output(template="src/vite-env.d.ts.j2", path="src/vite-env.d.ts"),
        Output(template="src/layer.md.j2", path="src/widgets/README.md"),
        Output(template="src/layer.md.j2", path="src/features/README.md"),
        Output(template="src/layer.md.j2", path="src/entities/README.md"),
        Output(template="src/shared/config/app.ts.j2", path="src/shared/config/app.ts"),
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
    ),
    covers=frozenset({"app", "page"}),
    helpers=HELPERS,
)
