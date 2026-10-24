from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import nextjs, react
from appgen.bindings.shared.i18n import finish
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen.generator import generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        fields:
          title: { type: string, required: true }
    pages:
      tasks: { path: /tasks, title: Tasks }
    """
)

TRANSLATIONS = dedent(
    """\
    translations:
      default: en
      languages:
        en: { label: English }
        de:
          label: Deutsch
          text: { Tasks: Aufgaben, Title: Titel }
        fr:
          label: Français
          text: { Tasks: Tâches }
    """
)


def codes(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def test_a_language_that_misses_a_key_of_another_language_is_reported() -> None:
    assert codes(BASE + TRANSLATIONS) == [
        (
            "missing-translation",
            "translations.languages.fr",
            "The language 'fr' has no translation of 'Title'.",
        )
    ]


def test_the_default_language_is_a_language_without_text() -> None:
    text = TRANSLATIONS.replace("default: en", "default: es").replace(
        "      text: { Tasks: Tâches }", "      text: { Tasks: Tâches, Title: Titre }"
    )
    assert [c[:2] for c in codes(BASE + text)] == [("unknown-reference", "translations")]
    text = TRANSLATIONS.replace("en: { label: English }", "en: { label: English, text: { a: b } }")
    assert ("invalid-value", "translations.languages.en") in [c[:2] for c in codes(BASE + text)]


def test_the_section_is_no_longer_reserved() -> None:
    text = TRANSLATIONS.replace(
        "      text: { Tasks: Tâches }", "      text: { Tasks: Tâches, Title: Titre }"
    )
    definition = load_definition_text(BASE + text, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.translations is not None
    assert definition.find("translations.languages.de") is not None


@pytest.fixture(scope="module")
def example() -> AppDefinition:
    return load_definition(EXAMPLE)


@pytest.mark.parametrize("binding", [react.BINDING, nextjs.BINDING], ids=["react", "nextjs"])
def test_the_front_ends_translate_the_text_and_cover_the_languages(
    example: AppDefinition, binding: object
) -> None:
    result = generate(example, binding)  # pyright: ignore[reportArgumentType]
    files = {f.path: f.content for f in result.files}
    i18n = files["src/shared/lib/i18n.ts"]
    assert "// @trace translations file" in i18n
    assert '"Projects": "Projekte",' in i18n
    assert "@trace translations.languages.de" in i18n
    assert not [g for g in result.gaps if g.kind in ("translations", "language")]
    menu = files["src/widgets/navigation/ui/main-menu.tsx"]
    assert 'import { t } from "@/shared/lib/i18n";' in menu
    assert '<span>{t("Projects")}</span>' in menu
    assert "<LanguageProvider>" in files["src/app/providers/index.tsx"]


def test_an_app_without_translations_has_the_text_as_it_is(example: AppDefinition) -> None:
    text = EXAMPLE.read_text()
    plain = load_definition_text(text[: text.index("\ntranslations:")], str(EXAMPLE))
    files = {f.path: f.content for f in generate(plain, react.BINDING).files}
    assert "src/shared/lib/i18n.ts" not in files
    assert not any("@/shared/lib/i18n" in content for content in files.values())
    assert "<span>Projects</span>" in files["src/widgets/navigation/ui/main-menu.tsx"]


def test_finish_imports_t_after_the_directive(example: AppDefinition) -> None:
    content = '// @trace app file\n"use client";\n\nexport const a = t("A");\n'
    assert finish("src/a.tsx", content, example) == (
        '// @trace app file\n"use client";\nimport { t } from "@/shared/lib/i18n";\n\n'
        'export const a = t("A");\n'
    )
    content = 'import { b } from "./b";\n\nexport const a = b.closest("a") + t("A");\n'
    assert finish("src/a.ts", content, example).startswith(
        'import { t } from "@/shared/lib/i18n";\nimport { b }'
    )
    assert finish("src/a.ts", "export const a = b.closest(1);\n", example) == (
        "export const a = b.closest(1);\n"
    )
    assert finish("README.md", 't("A")\n', example) == 't("A")\n'
