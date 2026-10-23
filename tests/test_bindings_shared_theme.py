"""Tests of the shared theme of the front-end bindings: CSS variables from the tokens."""

from textwrap import dedent

from appgen.bindings.shared.theme import (
    SHADCN_DEFAULTS,
    Variable,
    build_theme,
    css_name,
    font_stack,
)
from appgen.dsl import load_definition_text

DEFINITION = load_definition_text(
    dedent(
        """\
        version: 0
        app: { name: themed, title: Themed }
        entities:
          Note: { fields: { text: { type: text } } }
        ui:
          tokens:
            color:
              blue:
                600: { $value: "#2563eb" }
                400: { $value: "#60a5fa" }
              primary:
                $value: "{color.blue.600}"
                $modes: { dark: "{color.blue.400}" }
              status:
                todo: { $value: "#64748b" }
            font_family:
              sans: { $value: [Inter, ui-sans-serif, sans-serif] }
            font_size:
              sm: { $value: 0.875rem }
            spacing:
              4: { $value: 1rem }
            radius:
              lg: { $value: 0.5rem }
            shadow:
              card:
                $value: { color: "#0000001a", offset_x: 0px, offset_y: 1px, blur: 3px, spread: 0px }
                $modes:
                  dark: { color: "#00000066", offset_x: 0px, offset_y: 1px, blur: 3px, spread: 0px }
            typography:
              body:
                $value:
                  font_family: "{font_family.sans}"
                  font_size: "{font_size.sm}"
                  font_weight: 400
                  line_height: 1.5
        """
    )
)


def _values(variables: list[Variable]) -> dict[str, tuple[str, str | None]]:
    return {v.name: (v.value, v.element_id) for v in variables}


def test_css_names_and_font_stacks() -> None:
    assert css_name("primary_foreground") == "primary-foreground"
    assert css_name("blue.600") == "blue-600"
    assert (
        font_stack(["Inter", "ui-sans-serif", "Fira Code"]) == '"Inter", ui-sans-serif, "Fira Code"'
    )


def test_color_tokens_are_variables_in_both_modes() -> None:
    theme = build_theme(DEFINITION)
    light, dark, inline = _values(theme.light), _values(theme.dark), _values(theme.inline)
    assert light["primary"] == ("#2563eb", "ui.tokens.color.primary")
    assert dark["primary"] == ("#60a5fa", "ui.tokens.color.primary")
    assert "blue-600" not in dark
    assert light["status-todo"] == ("#64748b", "ui.tokens.color.status.todo")
    assert inline["color-primary"] == ("var(--primary)", "ui.tokens.color.primary")


def test_other_tokens_are_tailwind_theme_variables() -> None:
    theme = build_theme(DEFINITION)
    static = _values(theme.static)
    assert static["text-sm"] == ("0.875rem", "ui.tokens.font_size.sm")
    assert static["spacing-4"] == ("1rem", "ui.tokens.spacing.4")
    assert static["font-sans"][0] == '"Inter", ui-sans-serif, sans-serif'
    assert _values(theme.light)["radius"] == ("0.5rem", "ui.tokens.radius.lg")
    # A token with another value in the dark mode is a variable of both modes.
    assert _values(theme.dark)["shadow-card"] == (
        "0px 1px 3px 0px #00000066",
        "ui.tokens.shadow.card",
    )
    assert _values(theme.inline)["shadow-card"][0] == "var(--shadow-card)"


def test_shadcn_variables_without_a_token_keep_the_defaults() -> None:
    theme = build_theme(DEFINITION)
    light = _values(theme.light)
    assert light["foreground"] == (SHADCN_DEFAULTS["foreground"][0], None)
    assert _values(theme.inline)["radius-sm"] == ("calc(var(--radius) - 4px)", None)


def test_typography_tokens_are_utilities() -> None:
    theme = build_theme(DEFINITION)
    [utility] = theme.utilities
    assert utility.name == "typography-body"
    assert ("font-size", "0.875rem") in utility.declarations
    assert theme.body_typography == "typography-body"
    assert "ui.tokens.typography" in theme.file_ids
