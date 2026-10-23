"""Copy the shadcn/ui components into the shared templates of the front-end bindings.

The Next.js and the React bindings write the shadcn/ui components into
the generated apps. To keep the generation deterministic and without
network, the component sources are templates in the repository. This
script fetches them once from a fixed commit of the shadcn/ui repository,
changes their imports to the FSD paths of the generated apps, and writes:

- `src/appgen/bindings/shared/templates/shadcn/<name>.tsx.j2`: one
  template for each component, with a trace header.
- `src/appgen/bindings/shared/templates/shadcn/registry.json`: the npm
  packages and the other components that each component needs.

Run it with `uv run scripts/vendor_shadcn.py`. Change `COMMIT` or
`COMPONENTS` to update the components.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

COMMIT = "3d98900e"
"""The commit of shadcn-ui/ui that the templates come from."""
BASE = f"https://raw.githubusercontent.com/shadcn-ui/ui/{COMMIT}/apps/v4/registry/new-york-v4"

COMPONENTS = (
    "alert-dialog",
    "avatar",
    "badge",
    "breadcrumb",
    "button",
    "calendar",
    "card",
    "chart",
    "checkbox",
    "collapsible",
    "command",
    "dialog",
    "dropdown-menu",
    "empty",
    "field",
    "input",
    "input-group",
    "label",
    "pagination",
    "popover",
    "radio-group",
    "scroll-area",
    "select",
    "separator",
    "sheet",
    "sidebar",
    "skeleton",
    "sonner",
    "spinner",
    "switch",
    "table",
    "tabs",
    "textarea",
    "tooltip",
)
"""The components that the bindings can use (ADR 0003, "Binding map"), with their dependencies."""

OUT = Path(__file__).parent.parent / "src/appgen/bindings/shared/templates/shadcn"

# The registry imports and their FSD paths in the generated apps.
IMPORTS = (
    (re.compile(r'from "cn"'), 'from "@/shared/lib/utils"'),
    (re.compile(r'from "@/registry/new-york-v4/lib/utils"'), 'from "@/shared/lib/utils"'),
    (re.compile(r'from "@/registry/new-york-v4/ui/([a-z-]+)"'), r'from "@/shared/ui/\1"'),
    (re.compile(r'from "@/registry/new-york-v4/hooks/([a-z-]+)"'), r'from "@/shared/lib/\1"'),
    # Each binding writes the theme module: next-themes in Next.js, its own
    # provider in the React app.
    (re.compile(r'from "next-themes"'), 'from "@/shared/lib/theme"'),
)


def fetch(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=30) as response:
        return response.read().decode("utf-8")


def parse_registry(text: str) -> dict[str, dict[str, list[str]]]:
    """Read the names, the npm packages, and the component dependencies of `_registry.ts`."""
    items: dict[str, dict[str, list[str]]] = {}
    for block in re.split(r"\n  \{\n", text)[1:]:
        name = re.search(r'name: "([^"]+)"', block)
        if name is None:
            continue

        def strings(key: str, block: str = block) -> list[str]:
            match = re.search(key + r": \[([^\]]*)\]", block)
            return re.findall(r'"([^"]+)"', match.group(1)) if match else []

        items[name.group(1)] = {
            "dependencies": [re.sub(r"(?<=.)@.*$", "", d) for d in strings("dependencies")],
            "registry_dependencies": strings("registryDependencies"),
            "files": re.findall(r'path: "([^"]+)"', block),
        }
    return items


def closure(names: tuple[str, ...], registry: dict[str, dict[str, list[str]]]) -> list[str]:
    todo = list(names)
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        # Hooks, for example use-mobile, are not components.
        if name not in seen and not name.startswith("use-"):
            seen.add(name)
            todo.extend(registry[name]["registry_dependencies"])
    return sorted(seen)


def main() -> int:
    registry = parse_registry(fetch("ui/_registry.ts"))
    names = closure(COMPONENTS, registry)
    missing = sorted(set(names) - set(COMPONENTS))
    if missing:
        print(f"Add these dependencies to COMPONENTS: {', '.join(missing)}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    data: dict[str, dict[str, list[str]]] = {}
    for name in names:
        item = registry[name]
        [path] = [f for f in item["files"] if f.startswith("ui/")]
        source = fetch(path)
        for pattern, replacement in IMPORTS:
            source = pattern.sub(replacement, source)
        hooks = sorted(set(re.findall(r'from "@/shared/lib/(use-[a-z-]+)"', source)))
        packages = {
            match if not match.startswith("@") else "/".join(match.split("/")[:2])
            for match in re.findall(r'from "([^".][^"]*)"', source)
            if not match.startswith("@/") and match != "react"
        }
        template = '{{ trace_header("app") }}\n{% raw %}\n' + source.rstrip() + "\n{% endraw %}\n"
        (OUT / f"{name}.tsx.j2").write_text(template, encoding="utf-8", newline="\n")
        data[name] = {
            "dependencies": sorted(
                {p.split("/")[0] if not p.startswith("@") else p for p in packages}
            ),
            "components": sorted(d for d in item["registry_dependencies"] if d in registry),
            "hooks": hooks,
        }
    for hook in sorted({h for item in data.values() for h in item["hooks"]}):
        source = fetch(f"hooks/{hook}.ts")
        template = '{{ trace_header("app") }}\n{% raw %}\n' + source.rstrip() + "\n{% endraw %}\n"
        (OUT / f"{hook}.ts.j2").write_text(template, encoding="utf-8", newline="\n")
    registry_file = OUT / "registry.json"
    document = {"source": f"shadcn-ui/ui@{COMMIT} new-york-v4", "components": data}
    registry_file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(names)} components to {OUT}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
