from pathlib import Path
from textwrap import dedent, indent

import pytest

from appgen.dsl import AppDefinition, load_definition_text
from appgen.gen import Binding, GenerationError, Output, ResolvedToken, generate, resolve_tokens
from appgen.gen.tokens import token_sort_key


def _definition(tokens: str) -> AppDefinition:
    return load_definition_text(
        dedent(
            """\
            version: 0
            app: { name: demo, title: Demo }
            entities:
              Task:
                fields:
                  title: { type: string }
            ui:
              tokens:
            """
        )
        + indent(dedent(tokens), "    ")
    )


TOKENS = """\
color:
  blue:
    600: { $value: "#2563eb" }
    400: { $value: "#60a5fa" }
    50: { $value: "#eff6ff" }
  white: { $value: "#ffffff" }
  slate:
    950: { $value: "#020617" }
  primary:
    $value: "{color.blue.600}"
    $modes: { dark: "{color.blue.400}" }
  background:
    $value: "{color.white}"
    $modes: { dark: "{color.slate.950}" }
  surface: { $value: "{color.background}" }
font_family:
  sans: { $value: [Inter, sans-serif] }
font_size:
  sm: { $value: 0.875rem }
typography:
  body:
    $value:
      font_family: "{font_family.sans}"
      font_size: "{font_size.sm}"
      font_weight: 400
      line_height: 1.5
"""


@pytest.fixture
def tokens() -> dict[str, ResolvedToken]:
    return {t.path: t for t in resolve_tokens(_definition(TOKENS))}


def test_a_literal_value_is_the_same_in_both_modes(tokens: dict[str, ResolvedToken]) -> None:
    white = tokens["color.white"]
    assert (white.light, white.dark) == ("#ffffff", "#ffffff")
    assert white.light_refs == white.dark_refs == ()
    assert (white.element_id, white.group, white.type) == (
        "ui.tokens.color.white",
        "color",
        "color",
    )


def test_a_reference_resolves_to_the_value_of_its_target(tokens: dict[str, ResolvedToken]) -> None:
    primary = tokens["color.primary"]
    assert primary.light == "#2563eb"
    assert primary.light_refs == ("ui.tokens.color.blue.600",)


def test_each_mode_resolves_its_own_value(tokens: dict[str, ResolvedToken]) -> None:
    primary = tokens["color.primary"]
    assert primary.value("dark") == "#60a5fa"
    assert primary.refs("dark") == ("ui.tokens.color.blue.400",)


def test_a_chain_of_references_resolves_in_each_mode(tokens: dict[str, ResolvedToken]) -> None:
    surface = tokens["color.surface"]
    assert (surface.light, surface.dark) == ("#ffffff", "#020617")
    assert surface.light_refs == ("ui.tokens.color.background", "ui.tokens.color.white")
    assert surface.dark_refs == ("ui.tokens.color.background", "ui.tokens.color.slate.950")


def test_references_inside_composite_values_resolve(tokens: dict[str, ResolvedToken]) -> None:
    body = tokens["typography.body"]
    assert body.light == {
        "font_family": ["Inter", "sans-serif"],
        "font_size": "0.875rem",
        "font_weight": 400,
        "line_height": 1.5,
    }
    assert body.light_refs == ("ui.tokens.font_family.sans", "ui.tokens.font_size.sm")


def test_the_token_set_is_flat_and_sorted() -> None:
    paths = [t.path for t in resolve_tokens(_definition(TOKENS))]
    assert paths == sorted(paths, key=token_sort_key)
    assert paths[:3] == ["color.background", "color.blue.50", "color.blue.400"]
    assert "color.blue" not in paths


def test_a_definition_without_tokens_has_none() -> None:
    definition = load_definition_text(
        "version: 0\napp: { name: demo, title: Demo }\n"
        "entities:\n  Task:\n    fields:\n      title: { type: string }\n"
    )
    assert resolve_tokens(definition) == []


def test_a_loop_of_references_stops_the_run() -> None:
    # The loader does not run the validator, so a loop can reach the resolver.
    definition = _definition(
        """\
        color:
          a: { $value: "{color.b}" }
          b: { $value: "{color.a}" }
        """
    )
    with pytest.raises(
        GenerationError, match=r"loop of references: color\.a -> color\.b -> color\.a"
    ):
        resolve_tokens(definition)


def test_templates_get_the_resolved_tokens(tmp_path: Path) -> None:
    (tmp_path / "theme.css.j2").write_text(
        "{{ trace_header('app') }}\n:root {\n"
        "{% for t in tokens if t.group == 'color' %}"
        "  --{{ t.path | replace('.', '-') }}: {{ t.light }}; {{ trace(t.element_id) }}\n"
        "{% endfor %}}\n"
    )
    binding = Binding(
        name="temp",
        description="A binding for one test.",
        template_dir=tmp_path,
        outputs=(Output("theme.css.j2", "theme.css"),),
        covers=frozenset({"app"}),
    )
    css = generate(_definition(TOKENS), binding).files[0].content
    assert "  --color-primary: #2563eb; /* @trace ui.tokens.color.primary */\n" in css
