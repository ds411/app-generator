from textwrap import dedent, indent

import pytest

from appgen.dsl import AppDefinition, DefinitionError, Diagnostic, Location, load_definition_text
from appgen.dsl.ui import Token, TokenGroup, TokenTable, check_tokens
from appgen.dsl.validator import validate_definition

HEADER = dedent(
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

TOKENS = dedent(
    """\
    color:
      $description: The color palette.
      blue:
        "50": { $value: "#eff6ff" }
        600: { $value: "#2563eb" }
        400: { $value: "#60a5fa" }
      white: { $value: "#ffffff" }
      slate:
        950: { $value: "oklch(0.129 0.042 264.695)" }
      primary:
        $value: "{color.blue.600}"
        $modes: { dark: "{color.blue.400}" }
      background:
        $value: "{color.white}"
        $modes: { light: "{color.white}", dark: "{color.slate.950}" }
      surface: { $value: "{color.background}" }
    font_family:
      sans: { $value: [Inter, ui-sans-serif, sans-serif] }
      mono: { $value: JetBrains Mono }
    font_size:
      sm: { $value: 0.875rem }
    font_weight:
      regular: { $value: 400 }
    line_height:
      normal: { $value: 1.5 }
    letter_spacing:
      tight: { $value: -0.01em }
    typography:
      body:
        $value:
          font_family: "{font_family.sans}"
          font_size: "{font_size.sm}"
          font_weight: "{font_weight.regular}"
          line_height: 1.5
    spacing:
      $type: dimension
      0: { $value: 0 }
      4: { $value: 1rem }
    size:
      sidebar: { $value: 16rem }
    radius:
      lg: { $value: 0.625rem }
    shadow:
      card:
        $value:
          - { color: "#0000001a", offset_x: 0px, offset_y: 1px, blur: 3px, spread: 0px }
          - { color: "{color.blue.600}", offset_x: 0px, offset_y: 1px, blur: 2px, spread: -1px }
        $modes:
          dark:
            { color: "#00000080", offset_x: 0, offset_y: 1px, blur: 3px, spread: 0, inset: false }
    breakpoint:
      md: { $value: 768px }
    duration:
      fast: { $value: 150ms }
    """
)


def text(tokens: str) -> str:
    return HEADER + indent(tokens, "    ")


def load(tokens: str = TOKENS) -> AppDefinition:
    return load_definition_text(text(tokens), "app.yaml")


def check(tokens: str) -> list[Diagnostic]:
    definition = load(tokens)
    assert definition.ui is not None
    return check_tokens(definition.ui.tokens)


def codes(tokens: str) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in check(tokens)]


def test_loads_the_token_tree() -> None:
    definition = load()

    assert definition.ui is not None
    tokens = definition.ui.tokens
    assert tokens is not None
    assert isinstance(tokens.color, TokenGroup)
    assert tokens.color.description == "The color palette."
    blue = tokens.color.children["blue"]
    assert isinstance(blue, TokenGroup)
    assert list(blue.children) == ["50", "600", "400"]
    primary = tokens.color.children["primary"]
    assert isinstance(primary, Token)
    assert primary.value == "{color.blue.600}"
    assert primary.mode_value("light") == "{color.blue.600}"
    assert primary.mode_value("dark") == "{color.blue.400}"


def test_tokens_keep_their_location() -> None:
    tokens = load().ui.tokens  # pyright: ignore[reportOptionalMemberAccess]

    assert tokens is not None
    assert tokens.color is not None
    assert tokens.color.location == Location("app.yaml", 9, 5)
    assert tokens.color.children["primary"].location == Location("app.yaml", 18, 7)


def test_valid_tokens_have_no_problems() -> None:
    assert check(TOKENS) == []


def test_definition_without_tokens_has_no_problems() -> None:
    assert check_tokens(None) == []


def test_table_lists_each_token_with_its_type() -> None:
    tokens = load().ui.tokens  # pyright: ignore[reportOptionalMemberAccess]

    table = TokenTable.build(tokens)

    assert table.tokens["color.blue.600"].type == "color"
    assert table.tokens["spacing.4"].type == "dimension"
    assert table.tokens["typography.body"].element_id == "ui.tokens.typography.body"
    assert "color.blue" in table.groups


def test_table_resolves_references_for_each_mode() -> None:
    table = TokenTable.build(load().ui.tokens)  # pyright: ignore[reportOptionalMemberAccess]

    assert table.resolve("color.primary", "light") == "#2563eb"
    assert table.resolve("color.primary", "dark") == "#60a5fa"
    assert table.resolve("color.surface", "dark") == "oklch(0.129 0.042 264.695)"
    assert table.resolve("typography.body", "light") == {
        "font_family": ["Inter", "ui-sans-serif", "sans-serif"],
        "font_size": "0.875rem",
        "font_weight": 400,
        "line_height": 1.5,
    }


def test_reference_to_a_missing_token() -> None:
    [diagnostic] = check(TOKENS.replace('"{color.blue.600}"\n', '"{color.blue.700}"\n'))

    assert diagnostic.code == "invalid-token-value"
    assert diagnostic.element_id == "ui.tokens.color.primary"
    assert diagnostic.message == "$value: The token 'color.blue.700' does not exist."
    assert diagnostic.location == Location("app.yaml", 19, 17)


def test_reference_to_a_missing_token_in_a_mode() -> None:
    [diagnostic] = check(TOKENS.replace('dark: "{color.blue.400}"', 'dark: "{color.blue.4}"'))

    assert diagnostic.message == "$modes.dark: The token 'color.blue.4' does not exist."


def test_reference_to_a_missing_token_in_a_composite_value() -> None:
    [diagnostic] = check(TOKENS.replace('"{font_size.sm}"', '"{font_size.md}"'))

    assert diagnostic.element_id == "ui.tokens.typography.body"
    assert "The token 'font_size.md' does not exist." in diagnostic.message


def test_reference_to_a_group() -> None:
    [diagnostic] = check(
        TOKENS.replace('{ $value: "{color.background}" }', '{ $value: "{color.blue}" }')
    )

    assert (
        diagnostic.message
        == "$value: The reference '{color.blue}' refers to a group, not to a token."
    )


def test_reference_to_a_token_of_another_type() -> None:
    [diagnostic] = check(TOKENS.replace('"{font_size.sm}"', '"{color.white}"'))

    assert "of the type 'color', but this value needs the type 'dimension'" in diagnostic.message


def test_malformed_reference() -> None:
    [diagnostic] = check(TOKENS.replace('"{color.background}"', '"{color..background}"'))

    assert "is not valid" in diagnostic.message


def test_loop_of_references() -> None:
    tokens = TOKENS.replace('$value: "{color.white}"\n', '$value: "{color.surface}"\n')

    diagnostics = check(tokens)

    assert [(d.code, d.element_id) for d in diagnostics] == [
        ("token-loop", "ui.tokens.color.background")
    ]
    assert diagnostics[0].message == (
        "The tokens refer to each other in a loop: "
        "color.background -> color.surface -> color.background."
    )


def test_token_that_refers_to_itself() -> None:
    assert codes(
        TOKENS.replace('{ $value: "{color.background}" }', '{ $value: "{color.surface}" }')
    ) == [("token-loop", "ui.tokens.color.surface")]


@pytest.mark.parametrize(
    ("old", "new", "element_id"),
    [
        ('"#ffffff"', '"#fffff"', "ui.tokens.color.white"),
        ('"#ffffff"', "white", "ui.tokens.color.white"),
        ("0.875rem", "14", "ui.tokens.font_size.sm"),
        ("768px", "48rem", "ui.tokens.breakpoint.md"),
        ("$value: 400", "$value: bold", "ui.tokens.font_weight.regular"),
        ("$value: 1.5", "$value: tall", "ui.tokens.line_height.normal"),
        ("150ms", "0.15s", "ui.tokens.duration.fast"),
        ("JetBrains Mono", "[]", "ui.tokens.font_family.mono"),
        ("line_height: 1.5\n", "line_height: 1.5\n      color: red\n", "ui.tokens.typography.body"),
        ("line_height: 1.5\n", "\n", "ui.tokens.typography.body"),
        ("spread: -1px", "spread: wide", "ui.tokens.shadow.card"),
        ("inset: false", "inset: 1", "ui.tokens.shadow.card"),
    ],
)
def test_invalid_literal_values(old: str, new: str, element_id: str) -> None:
    assert old in TOKENS
    assert codes(TOKENS.replace(old, new, 1)) == [("invalid-token-value", element_id)]


def test_type_must_agree_with_the_group() -> None:
    tokens = TOKENS.replace("$type: dimension", "$type: color").replace(
        "lg: { $value: 0.625rem }", "lg: { $value: 0.625rem, $type: number }"
    )

    assert codes(tokens) == [
        ("token-type-mismatch", "ui.tokens.spacing"),
        ("token-type-mismatch", "ui.tokens.radius.lg"),
    ]


def test_invalid_token_name() -> None:
    [diagnostic] = check(TOKENS.replace("  sidebar:", "  Sidebar:"))

    assert diagnostic.code == "invalid-name"
    assert diagnostic.element_id == "ui.tokens.size.Sidebar"


def test_unknown_dollar_key_in_a_group_gets_a_hint() -> None:
    [diagnostic] = check(TOKENS.replace("  sidebar:", "  $sidebar:"))

    assert diagnostic.code == "invalid-name"
    assert diagnostic.hint is not None
    assert "$value, $type, $description, $modes" in diagnostic.hint


def errors(tokens: str) -> list[Diagnostic]:
    with pytest.raises(DefinitionError) as caught:
        load(tokens)
    return caught.value.diagnostics


def test_unknown_dollar_key_in_a_token_is_a_load_error() -> None:
    [diagnostic] = errors(
        TOKENS.replace('white: { $value: "#ffffff" }', 'white: { $value: "#ffffff", $mode: x }')
    )

    assert diagnostic.code == "unknown-key"
    assert diagnostic.message == "The key '$mode' is not known here."


def test_unknown_mode_is_a_load_error() -> None:
    [diagnostic] = errors(TOKENS.replace("$modes: { dark:", "$modes: { dim:"))

    assert diagnostic.code == "invalid-value"
    assert "'dim'" in diagnostic.message
    assert diagnostic.location == Location("app.yaml", 20, 19)


def test_unknown_top_level_group_is_a_load_error() -> None:
    [diagnostic] = errors(TOKENS.replace("duration:\n", "durations:\n"))

    assert diagnostic.code == "unknown-key"
    assert diagnostic.hint == "Did you mean 'duration'?"


def test_token_value_in_a_group_must_be_a_mapping() -> None:
    [diagnostic] = errors(TOKENS.replace('white: { $value: "#ffffff" }', 'white: "#ffffff"'))

    assert diagnostic.message == "Expected a mapping."
    assert diagnostic.location == Location("app.yaml", 15, 14)


def test_tokens_and_groups_have_element_ids() -> None:
    definition = load()

    token = definition.find("ui.tokens.color.blue.600")
    assert isinstance(token, Token)
    assert token.id == "ui.tokens.color.blue.600"
    assert isinstance(definition.find("ui.tokens.color.blue"), TokenGroup)
    assert definition.find("ui.tokens.typography.body") is not None


def test_validator_reports_token_problems() -> None:
    definition = load(TOKENS.replace('"{color.blue.600}"\n', '"{color.blue.700}"\n'))

    assert [(d.code, d.element_id) for d in validate_definition(definition)] == [
        ("invalid-token-value", "ui.tokens.color.primary")
    ]


def test_extension_keys_in_a_group_are_not_tokens() -> None:
    tokens = load(TOKENS.replace("color:\n", "color:\n  x-figma: { file: abc }\n", 1)).ui.tokens  # pyright: ignore[reportOptionalMemberAccess]

    assert tokens is not None
    assert tokens.color is not None
    assert "x-figma" not in tokens.color.children
    assert tokens.color.extensions == {"x-figma": {"file": "abc"}}
