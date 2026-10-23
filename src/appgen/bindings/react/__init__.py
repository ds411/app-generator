"""The React 19 binding: a standalone front-end app with mock data.

The app uses TypeScript, Vite, React Router, and pnpm. Its code follows
Feature-Sliced Design (FSD): the layers `app`, `pages`, `widgets`,
`features`, `entities`, and `shared` are folders in `src/`.
"""

from pathlib import Path

from appgen.bindings import shared
from appgen.bindings.react.gaps import gap_spec, param_type
from appgen.bindings.react.helpers import HELPERS, context, to_json
from appgen.bindings.shared import shadcn
from appgen.gen.binding import Binding, Output

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
        Output(template="README.md.j2", path="README.md"),
        Output(template="src/app/main.tsx.j2", path="src/app/main.tsx"),
        Output(template="src/app/app.tsx.j2", path="src/app/app.tsx"),
        Output(template="src/app/router.tsx.j2", path="src/app/router.tsx"),
        Output(template="src/vite-env.d.ts.j2", path="src/vite-env.d.ts"),
        Output(template="src/layer.md.j2", path="src/widgets/README.md"),
        Output(template="src/layer.md.j2", path="src/features/README.md"),
        Output(template="src/layer.md.j2", path="src/entities/README.md"),
        Output(template="src/shared/config/app.ts.j2", path="src/shared/config/app.ts"),
        Output(template="components.json.j2", path="components.json"),
        Output(template="src/app/styles/index.css.j2", path="src/app/styles/index.css"),
        Output(template="shadcn/lib/utils.ts.j2", path="src/shared/lib/utils.ts"),
        Output(template="src/shared/lib/theme.ts.j2", path="src/shared/lib/theme.ts"),
        *_SHADCN,
        *_HOOKS,
        Output(template="src/shared/api/types.ts.j2", path="src/shared/api/types.ts"),
        Output(template="src/shared/api/mock-store.ts.j2", path="src/shared/api/mock-store.ts"),
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
            when=_CUSTOM_OP,
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
        | {"custom_widget", "custom_rule", "custom_action"}
    ),
    context=context,
    filters={"json": to_json},
    helpers=HELPERS | {"gap_spec": gap_spec, "param_type": param_type},
)
