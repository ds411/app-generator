"""Copy the shadcn/ui components into the shared templates of the front-end bindings.

The Next.js and the React bindings write the shadcn/ui components into
the generated apps. To keep the generation deterministic and without
network, the component sources are templates in the repository. This
script fetches them once from a fixed commit of the shadcn/ui repository,
changes their imports to the FSD paths of the generated apps, changes
their fixed text to calls of the text helpers (`TEXTS`), changes the
classes of a side to logical classes and turns the icons of a direction
in `rtl` (`DIRECTION`, `appgen.bindings.shared.sides`), and writes:

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

from appgen.bindings.shared.sides import logical_classes

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


def attr(name: str, text: str) -> tuple[str, str]:
    """A text in a JSX attribute, for example `aria-label="Close"`."""
    return f'{name}="{text}"', f'{name}={{% endraw %}}{{{{ jsx_attr("{text}") }}}}{{% raw %}}'


def child(text: str) -> tuple[str, str]:
    """A text as a JSX child, for example `<span>Close</span>`."""
    return f">{text}<", f'>{{% endraw %}}{{{{ jsx_text("{text}") }}}}{{% raw %}}<'


def default(name: str, text: str) -> tuple[str, str]:
    """A text as the default value of a parameter, for example `title = "Search"`."""
    return f'{name} = "{text}"', f'{name} = {{% endraw %}}{{{{ tr(js("{text}")) }}}}{{% raw %}}'


def localized(old: str, new: str) -> tuple[str, str]:
    """Code for an app with translations, for example a format in the selected locale."""
    end, start = "{% endraw %}", "{% raw %}"
    return (
        old,
        f"{end}{{% if i18n %}}{start}{new}{end}{{% else %}}{start}{old}{end}{{% endif %}}{start}",
    )


def text(value: str) -> str:
    """A fixed text as a JavaScript expression in the code of a `localized` change."""
    return f'{{% endraw %}}{{{{ tr(js("{value}")) }}}}{{% raw %}}'


def text_format(value: str, **values: str) -> str:
    """A fixed text with values as a JavaScript expression in the code of a `localized` change."""
    arguments = "".join(f', {name}="{expression}"' for name, expression in values.items())
    return f'{{% endraw %}}{{{{ js_format("{value}"{arguments}) }}}}{{% raw %}}'


_CALENDAR_LOCALE = f"""/** The names of the months and the days, in the selected locale. */
const localeFormatters: Partial<Formatters> = {{
  formatCaption: (month) => dateTimeFormat({{ month: "long", year: "numeric" }}).format(month),
  formatMonthDropdown: (month) => dateTimeFormat({{ month: "short" }}).format(month),
  formatYearDropdown: (year) => dateTimeFormat({{ year: "numeric" }}).format(year),
  formatWeekdayName: (weekday) => dateTimeFormat({{ weekday: "short" }}).format(weekday),
}}

/** The labels of the calendar, in the selected language. */
const localeLabels: Partial<Labels> = {{
  labelNav: () => {text("Navigation bar")},
  labelNext: () => {text("Go to the next month")},
  labelPrevious: () => {text("Go to the previous month")},
  labelMonthDropdown: () => {text("Choose the month")},
  labelYearDropdown: () => {text("Choose the year")},
  labelGrid: (month) => dateTimeFormat({{ month: "long", year: "numeric" }}).format(month),
  labelWeekday: (weekday) => dateTimeFormat({{ weekday: "long" }}).format(weekday),
  labelDayButton: (day, modifiers) => {{
    const date = dateTimeFormat({{ dateStyle: "full" }}).format(day)
    const label = modifiers.today ? {text_format("Today, {date}", date="date")} : date
    return modifiers.selected ? {text_format("{date}, selected", date="label")} : label
  }},
}}

"""

# The code of the components that formats dates and numbers. An app with
# translations uses the locale of the selected language (ADR 0010).
LOCALE: dict[str, tuple[tuple[str, str], ...]] = {
    "calendar": (
        localized(
            'import { Button, buttonVariants } from "@/shared/ui/button"\n',
            'import { Button, buttonVariants } from "@/shared/ui/button"\n'
            'import { dateTimeFormat, firstWeekday } from "@/shared/lib/format"\n'
            'import { getDirection, getLocale } from "@/shared/lib/i18n"\n',
        ),
        localized("  type DayButton,\n", "  type DayButton,\n  type Formatters,\n  type Labels,\n"),
        localized("function Calendar({\n", _CALENDAR_LOCALE + "function Calendar({\n"),
        localized(
            """      formatters={{
        formatMonthDropdown: (date) =>
          date.toLocaleString("default", { month: "short" }),
        ...formatters,
      }}
""",
            """      lang={getLocale()}
      dir={getDirection()}
      weekStartsOn={firstWeekday()}
      labels={localeLabels}
      formatters={{ ...localeFormatters, ...formatters }}
""",
        ),
    ),
    "chart": (
        localized(
            'import { cn } from "@/shared/lib/utils"\n',
            'import { getLocale } from "@/shared/lib/i18n"\n'
            'import { cn } from "@/shared/lib/utils"\n',
        ),
        localized("item.value.toLocaleString()", "item.value.toLocaleString(getLocale())"),
    ),
}

# The fixed text of the components. The text helpers of the bindings
# write a call of `t` for an app with translations, and the text as it is
# for an app without translations (ADR 0010).
TEXTS: dict[str, tuple[tuple[str, str], ...]] = {
    "breadcrumb": (attr("aria-label", "breadcrumb"), child("More")),
    "command": (
        default("title", "Command Palette"),
        default("description", "Search for a command to run..."),
    ),
    "dialog": (child("Close"),),
    "pagination": (
        attr("aria-label", "pagination"),
        attr("aria-label", "Go to previous page"),
        child("Previous"),
        attr("aria-label", "Go to next page"),
        child("Next"),
        child("More pages"),
    ),
    "sheet": (child("Close"),),
    "sidebar": (
        child("Sidebar"),
        child("Displays the mobile sidebar."),
        child("Toggle Sidebar"),
        attr("aria-label", "Toggle Sidebar"),
        attr("title", "Toggle Sidebar"),
    ),
    "spinner": (attr("aria-label", "Loading"),),
}


def turned(icon: str) -> tuple[str, str]:
    """An icon of a direction, for example `<ChevronRightIcon />`, that turns in `rtl`."""
    return f"<{icon} />", f'<{icon} className="rtl:rotate-180" />'


def moved(classes: str, rtl: str) -> tuple[str, str]:
    """Classes that move an element to a side, and the classes of the move in `rtl`."""
    return f" {classes} ", f" {classes} {rtl} "


# The changes for a language from right to left (ADR 0010), in addition
# to the logical classes: the icons of a direction turn, and a move to
# the side goes to the other side.
DIRECTION: dict[str, tuple[tuple[str, str], ...]] = {
    "breadcrumb": (turned("ChevronRight"),),
    "dropdown-menu": (
        (
            '<ChevronRightIcon className="ml-auto size-4" />',
            '<ChevronRightIcon className="ml-auto size-4 rtl:rotate-180" />',
        ),
    ),
    "pagination": (turned("ChevronLeftIcon"), turned("ChevronRightIcon")),
    "sidebar": (
        turned("PanelLeftIcon"),
        moved("w-4 -translate-x-1/2", "rtl:translate-x-1/2"),
        moved("translate-x-px flex-col", "rtl:-translate-x-px"),
        moved("-translate-x-px items-center", "rtl:translate-x-px"),
    ),
    "switch": (
        moved(
            "data-[state=checked]:translate-x-[calc(100%-2px)]",
            "rtl:data-[state=checked]:-translate-x-[calc(100%-2px)]",
        ),
    ),
}


def translate(name: str, source: str) -> str:
    """Change the fixed text of a component to calls of the text helpers, its formats and sides."""
    for old, new in (*DIRECTION.get(name, ()), *TEXTS.get(name, ()), *LOCALE.get(name, ())):
        if old not in source:
            raise ValueError(f"The component {name} has no text {old!r}.")
        source = source.replace(old, new)
    return logical_classes(source)


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
        body = translate(name, source.rstrip())
        template = '{{ trace_header("app") }}\n{% raw %}\n' + body + "\n{% endraw %}\n"
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
