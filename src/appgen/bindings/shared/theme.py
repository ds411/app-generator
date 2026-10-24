"""The theme of the front-end apps: CSS variables from the design tokens (ADR 0003).

The Next.js and the React apps use Tailwind CSS 4 and shadcn/ui. Both get
their theme from the shared template `theme/globals.css.j2`, which renders
the `Theme` of this module:

- Each color token, and each token with another value in the dark mode,
  is a CSS variable in `:root` (light) and in `.dark` (dark), and
  `@theme inline` maps it to a Tailwind CSS theme variable. Thus
  `color.primary_foreground` gives `--primary-foreground` (the shadcn/ui
  name) and the utilities `bg-primary-foreground` and so on.
- The other tokens are Tailwind CSS theme variables with one value, for
  example `spacing.4` gives `--spacing-4` and `font_size.sm` gives
  `--text-sm`.
- `radius.lg` also gives `--radius`, the base radius of shadcn/ui.
- Each typography token gives a utility class, for example
  `typography-heading`.
- A shadcn/ui variable without a token keeps the shadcn/ui default (the
  neutral theme of new-york-v4).
"""

from dataclasses import dataclass, field

from pydantic import JsonValue

from appgen.dsl.model import AppDefinition
from appgen.gen.elements import iter_elements
from appgen.gen.tokens import ResolvedToken, resolve_tokens

# The Tailwind CSS theme namespace of each token group with one value.
_NAMESPACES: dict[str, str] = {
    "font_family": "font",
    "font_size": "text",
    "font_weight": "font-weight",
    "line_height": "leading",
    "letter_spacing": "tracking",
    "spacing": "spacing",
    "size": "size",
    "radius": "radius",
    "shadow": "shadow",
    "breakpoint": "breakpoint",
    "duration": "duration",
}
_GENERIC_FONTS = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "ui-rounded",
        "emoji",
        "math",
    }
)

SHADCN_DEFAULTS: dict[str, tuple[str, str]] = {
    "background": ("oklch(1 0 0)", "oklch(0.145 0 0)"),
    "foreground": ("oklch(0.145 0 0)", "oklch(0.985 0 0)"),
    "card": ("oklch(1 0 0)", "oklch(0.205 0 0)"),
    "card-foreground": ("oklch(0.145 0 0)", "oklch(0.985 0 0)"),
    "popover": ("oklch(1 0 0)", "oklch(0.205 0 0)"),
    "popover-foreground": ("oklch(0.145 0 0)", "oklch(0.985 0 0)"),
    "primary": ("oklch(0.205 0 0)", "oklch(0.922 0 0)"),
    "primary-foreground": ("oklch(0.985 0 0)", "oklch(0.205 0 0)"),
    "secondary": ("oklch(0.97 0 0)", "oklch(0.269 0 0)"),
    "secondary-foreground": ("oklch(0.205 0 0)", "oklch(0.985 0 0)"),
    "muted": ("oklch(0.97 0 0)", "oklch(0.269 0 0)"),
    "muted-foreground": ("oklch(0.556 0 0)", "oklch(0.708 0 0)"),
    "accent": ("oklch(0.97 0 0)", "oklch(0.269 0 0)"),
    "accent-foreground": ("oklch(0.205 0 0)", "oklch(0.985 0 0)"),
    "destructive": ("oklch(0.577 0.245 27.325)", "oklch(0.704 0.191 22.216)"),
    "border": ("oklch(0.922 0 0)", "oklch(1 0 0 / 10%)"),
    "input": ("oklch(0.922 0 0)", "oklch(1 0 0 / 15%)"),
    "ring": ("oklch(0.708 0 0)", "oklch(0.556 0 0)"),
    "chart-1": ("oklch(0.646 0.222 41.116)", "oklch(0.488 0.243 264.376)"),
    "chart-2": ("oklch(0.6 0.118 184.704)", "oklch(0.696 0.17 162.48)"),
    "chart-3": ("oklch(0.398 0.07 227.392)", "oklch(0.769 0.188 70.08)"),
    "chart-4": ("oklch(0.828 0.189 84.429)", "oklch(0.627 0.265 303.9)"),
    "chart-5": ("oklch(0.769 0.188 70.08)", "oklch(0.645 0.246 16.439)"),
    "sidebar": ("oklch(0.985 0 0)", "oklch(0.205 0 0)"),
    "sidebar-foreground": ("oklch(0.145 0 0)", "oklch(0.985 0 0)"),
    "sidebar-primary": ("oklch(0.205 0 0)", "oklch(0.488 0.243 264.376)"),
    "sidebar-primary-foreground": ("oklch(0.985 0 0)", "oklch(0.985 0 0)"),
    "sidebar-accent": ("oklch(0.97 0 0)", "oklch(0.269 0 0)"),
    "sidebar-accent-foreground": ("oklch(0.205 0 0)", "oklch(0.985 0 0)"),
    "sidebar-border": ("oklch(0.922 0 0)", "oklch(1 0 0 / 10%)"),
    "sidebar-ring": ("oklch(0.708 0 0)", "oklch(0.556 0 0)"),
}
"""The colors of shadcn/ui (new-york-v4, neutral) in the light and the dark mode."""

SHADCN_RADIUS = "0.625rem"
_SHADCN_RADII = {
    "sm": "calc(var(--radius) - 4px)",
    "md": "calc(var(--radius) - 2px)",
    "lg": "var(--radius)",
    "xl": "calc(var(--radius) + 4px)",
}


@dataclass(frozen=True, slots=True)
class Variable:
    """One CSS variable, with the token that it comes from (None for a default)."""

    name: str
    """The name without `--`, for example `primary-foreground`."""
    value: str
    element_id: str | None = None


@dataclass(frozen=True, slots=True)
class Utility:
    """A utility class for a typography token, for example `typography-heading`."""

    name: str
    declarations: tuple[tuple[str, str], ...]
    element_id: str


@dataclass(slots=True)
class Theme:
    """The CSS of the theme, in the order of the template."""

    light: list[Variable] = field(default_factory=list[Variable])
    """The variables of `:root`."""
    dark: list[Variable] = field(default_factory=list[Variable])
    """The variables of `.dark`."""
    inline: list[Variable] = field(default_factory=list[Variable])
    """The `@theme inline` variables, which refer to a variable of `:root`."""
    static: list[Variable] = field(default_factory=list[Variable])
    """The `@theme static` variables, which have one value."""
    utilities: list[Utility] = field(default_factory=list[Utility])
    body_typography: str | None = None
    """The utility of the `typography.body` token, if the definition has it."""
    file_ids: list[str] = field(default_factory=list[str])
    """The IDs of `ui.tokens` and of its groups, for the file traces of the CSS file."""
    motion: str = "full"
    """The motion setting: `full`, `reduced`, or `none`."""
    motion_id: str | None = None
    """The ID of `ui.tokens.motion`, if the definition has it."""


def css_name(path: str) -> str:
    """Return the CSS name of a token path below its group: `blue.600` gives `blue-600`."""
    return path.replace("_", "-").replace(".", "-")


def css_var(path: str) -> str:
    """Return the CSS variable of a token path: `size.sidebar` gives `var(--size-sidebar)`."""
    group, _, rest = path.partition(".")
    if group == "color":
        return f"var(--{css_name(rest)})"
    return f"var(--{_NAMESPACES[group]}-{css_name(rest)})"


def css_value(token: ResolvedToken, value: JsonValue) -> str:
    """Return a token value as CSS text."""
    if token.type == "fontFamily":
        return font_stack(value)
    if token.type == "shadow":
        shadows = value if isinstance(value, list) else [value]
        return ", ".join(_shadow(item) for item in shadows)
    return _plain(value)


def font_stack(value: JsonValue) -> str:
    """Return a font family list as CSS: names that are not generic get quotes."""
    names = value if isinstance(value, list) else [value]
    return ", ".join(str(name) if str(name) in _GENERIC_FONTS else f'"{name}"' for name in names)


def _plain(value: JsonValue) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _shadow(value: JsonValue) -> str:
    if not isinstance(value, dict):
        return _plain(value)
    parts = [_plain(value.get(key, 0)) for key in ("offset_x", "offset_y", "blur", "spread")]
    text = " ".join([*parts, _plain(value.get("color", "transparent"))])
    return f"inset {text}" if value.get("inset") else text


def build_theme(definition: AppDefinition) -> Theme:
    """Return the theme of a definition from its resolved tokens."""
    theme = Theme()
    theme.file_ids = [
        e.id for e in iter_elements(definition) if e.kind in ("tokens", "token_group")
    ]
    motion = definition.ui.tokens.motion if definition.ui and definition.ui.tokens else None
    if motion is not None:
        theme.motion = motion.value
        theme.motion_id = motion.id
    tokens = resolve_tokens(definition)
    named: set[str] = set()
    for token in tokens:
        path = token.path.split(".", 1)[1]
        name = css_name(path)
        if token.group == "typography":
            theme.utilities.append(_utility(token, f"typography-{name}"))
            if path == "body":
                theme.body_typography = f"typography-{name}"
            continue
        light = css_value(token, token.light)
        dark = css_value(token, token.dark)
        if token.group == "color":
            theme.light.append(Variable(name, light, token.element_id))
            if dark != light:
                theme.dark.append(Variable(name, dark, token.element_id))
            theme.inline.append(Variable(f"color-{name}", f"var(--{name})", token.element_id))
            named.add(name)
            continue
        variable = f"{_NAMESPACES[token.group]}-{name}"
        if dark != light:
            theme.light.append(Variable(variable, light, token.element_id))
            theme.dark.append(Variable(variable, dark, token.element_id))
            theme.inline.append(Variable(variable, f"var(--{variable})", token.element_id))
        else:
            theme.static.append(Variable(variable, light, token.element_id))
        named.add(variable)
        if token.group == "radius" and path == "lg":
            theme.light.insert(0, Variable("radius", light, token.element_id))
            named.add("radius")
    if "radius" not in named:
        theme.light.insert(0, Variable("radius", SHADCN_RADIUS))
    for name, (light, dark) in SHADCN_DEFAULTS.items():
        if name not in named:
            theme.light.append(Variable(name, light))
            theme.dark.append(Variable(name, dark))
            theme.inline.append(Variable(f"color-{name}", f"var(--{name})"))
    for size, value in _SHADCN_RADII.items():
        if f"radius-{size}" not in named:
            theme.inline.append(Variable(f"radius-{size}", value))
    return theme


def _utility(token: ResolvedToken, name: str) -> Utility:
    value = token.light if isinstance(token.light, dict) else {}
    declarations: list[tuple[str, str]] = []
    for key, prop in (
        ("font_family", "font-family"),
        ("font_size", "font-size"),
        ("font_weight", "font-weight"),
        ("line_height", "line-height"),
        ("letter_spacing", "letter-spacing"),
    ):
        if key in value:
            item = value[key]
            declarations.append((prop, font_stack(item) if key == "font_family" else _plain(item)))
    return Utility(name, tuple(declarations), token.element_id)
