import re
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import nextjs, react
from appgen.bindings.shared.i18n import app_texts, finish, text_helpers
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen.binding import Binding
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
    assert "<LanguageProvider" in files["src/app/providers/index.tsx"]


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


def plain_example() -> AppDefinition:
    text = EXAMPLE.read_text()
    return load_definition_text(text[: text.index("\ntranslations:")], str(EXAMPLE))


def test_a_text_with_values_is_as_before_without_translations() -> None:
    helpers = text_helpers(plain_example())
    assert helpers["jsx_format"]("Page {page} of {count}", page="page", count="pageCount") == (
        "Page {page} of {pageCount}"
    )
    assert helpers["js_format"]("{count} chosen", count="names.length") == (
        "`${names.length} chosen`"
    )
    assert (
        helpers["js_format"]("Use `a`, ${ x: {count}", count="n") == "`Use \\`a\\`, \\${ x: ${n}`"
    )
    assert helpers["text"]("Done") == '"Done"'
    with pytest.raises(ValueError, match="do not agree"):
        helpers["jsx_format"]("Page {page} of {count}", page="page")


def test_a_text_with_values_is_a_call_of_t_with_translations(example: AppDefinition) -> None:
    helpers = text_helpers(example)
    assert helpers["jsx_format"]("Page {page} of {count}", page="page", count="pageCount") == (
        '{t("Page {page} of {count}", { count: pageCount, page })}'
    )
    assert helpers["js_format"]("{count} chosen", count="names.length") == (
        't("{count} chosen", { count: names.length })'
    )
    assert helpers["text"]("Done") == '"Done"'


@pytest.mark.parametrize("binding", [react.BINDING, nextjs.BINDING], ids=["react", "nextjs"])
def test_the_texts_of_an_app_are_the_keys_that_it_translates(
    example: AppDefinition, binding: Binding
) -> None:
    texts = app_texts(example, binding)
    # The texts of the definition, the defaults of the generator, and the fixed texts.
    assert {"Projects", "Due date", "To do", "Todo", "Cancel", "No projects yet"} <= set(texts)
    assert {"Rows per page", "Page {page} of {count}", "Close", "Toggle Sidebar", "Other"} <= set(
        texts
    )
    assert texts == sorted(texts)
    assert app_texts(plain_example(), binding) == []


def test_the_example_translates_each_text_of_its_apps(example: AppDefinition) -> None:
    assert example.translations is not None
    german = example.translations.languages["de"].text
    for binding in (react.BINDING, nextjs.BINDING):
        assert [text for text in app_texts(example, binding) if text not in german] == []


def test_a_translation_keeps_the_values_of_its_key() -> None:
    text = TRANSLATIONS.replace(
        "text: { Tasks: Aufgaben, Title: Titel }",
        'text: { Tasks: Aufgaben, Title: Titel, "Page {page} of {count}": "Seite {page}" }',
    ).replace(
        "      text: { Tasks: Tâches }",
        '      text: { Tasks: Tâches, Title: Titre, "Page {page} of {count}": "{count} {pages}" }',
    )
    assert [c for c in codes(BASE + text) if c[0] == "translation-values"] == [
        (
            "translation-values",
            "translations.languages.de",
            "The translation of 'Page {page} of {count}' in 'de' must have the values "
            "{count}, {page}.",
        ),
        (
            "translation-values",
            "translations.languages.fr",
            "The translation of 'Page {page} of {count}' in 'fr' must have the values "
            "{count}, {page}.",
        ),
    ]
    text = TRANSLATIONS.replace(
        "text: { Tasks: Aufgaben, Title: Titel }", 'text: { Tasks: "{n} Aufgaben", Title: Titel }'
    ).replace("      text: { Tasks: Tâches }", "      text: { Tasks: Tâches, Title: Titre }")
    assert [c[2] for c in codes(BASE + text)] == [
        "The translation of 'Tasks' in 'de' must have no values in braces."
    ]


@pytest.mark.parametrize("binding", [react.BINDING, nextjs.BINDING], ids=["react", "nextjs"])
def test_the_components_translate_their_fixed_text(
    example: AppDefinition, binding: Binding
) -> None:
    files = {f.path: f.content for f in generate(example, binding).files}
    assert '<span className="sr-only">{t("Close")}</span>' in files["src/shared/ui/dialog.tsx"]
    pagination = files["src/shared/ui/list-pagination.tsx"]
    assert 'aria-label={t("Next page")}' in pagination
    assert '{t("{first}\u2013{last} of {total}", { first, last, total })}' in pagination
    i18n = files["src/shared/lib/i18n.ts"]
    assert "export function t(text: string, values?: Record<string" in i18n
    plain = {f.path: f.content for f in generate(plain_example(), binding).files}
    assert '<span className="sr-only">Close</span>' in plain["src/shared/ui/dialog.tsx"]
    assert "{first}\u2013{last} of {total}\n" in plain["src/shared/ui/list-pagination.tsx"]
    stub = plain["src/widgets/overview/ui/workload-widget.ext.tsx"]
    assert (
        '"Not implemented yet: ui.dashboards.overview.widgets.workload" : "Not available yet."'
        in (stub)
    )


def test_finish_imports_t_after_the_header_of_a_file_without_imports(
    example: AppDefinition,
) -> None:
    content = '// @trace:gap a file\nexport const a = t("A");\n'
    assert finish("src/a.tsx", content, example) == (
        '// @trace:gap a file\nimport { t } from "@/shared/lib/i18n";\n\nexport const a = t("A");\n'
    )


_HELPER_TEXT = re.compile(
    r'(?<![\w.])(?:jsx_text|jsx_attr|text|jsx_format|js_format|tr\(js)\(\s*"((?:[^"\\]|\\.)*)"'
)


def test_the_docs_list_the_fixed_texts_of_the_templates() -> None:
    bindings = Path(__file__).parent.parent / "src" / "appgen" / "bindings"
    templates = {
        match
        for name in ("shared", "react", "nextjs")
        for path in (bindings / name).rglob("*.j2")
        for match in _HELPER_TEXT.findall(path.read_text(encoding="utf-8"))
    }
    docs = (Path(__file__).parent.parent / "docs" / "dsl.md").read_text(encoding="utf-8")
    section = docs[docs.index("### Fixed texts") :]
    section = section[: section.index("\n## ")]
    listed = set(re.findall(r"`([^`]+)`", section.split("\n\n", 2)[2]))
    assert sorted(templates - listed) == []
    assert sorted(listed - templates) == []


def test_a_locale_is_a_language_tag() -> None:
    text = TRANSLATIONS.replace(
        "      text: { Tasks: Tâches }", "      text: { Tasks: Tâches, Title: Titre }"
    )
    swiss = text.replace("    de:\n", "    de_ch:\n")
    assert codes(BASE + swiss) == [
        (
            "translation-locale",
            "translations.languages.de_ch",
            "The code 'de_ch' is not a language tag (BCP 47), and the language has no locale.",
        )
    ]
    definition = load_definition_text(BASE + swiss, "app.yaml")
    assert [d.hint for d in validate_definition(definition)] == [
        "Add a locale, for example 'locale: de-CH'."
    ]
    with_locale = swiss.replace("label: Deutsch\n", "label: Deutsch\n      locale: de-CH\n")
    assert codes(BASE + with_locale) == []
    wrong = text.replace("label: Deutsch\n", "label: Deutsch\n      locale: de_CH\n")
    assert codes(BASE + wrong) == [
        (
            "translation-locale",
            "translations.languages.de",
            "The locale 'de_CH' of 'de' is not a language tag (BCP 47).",
        )
    ]


@pytest.mark.parametrize("binding", [react.BINDING, nextjs.BINDING], ids=["react", "nextjs"])
def test_the_formats_use_the_locale_of_the_selected_language(binding: Binding) -> None:
    text = EXAMPLE.read_text().replace(
        "    de:\n      label: Deutsch\n", "    de:\n      label: Deutsch\n      locale: de-CH\n"
    )
    files = {
        f.path: f.content for f in generate(load_definition_text(text, str(EXAMPLE)), binding).files
    }
    i18n = files["src/shared/lib/i18n.ts"]
    assert '{ code: "en", label: "English", locale: "en" },' in i18n
    assert '{ code: "de", label: "Deutsch", locale: "de-CH" },' in i18n
    assert "document.documentElement.lang = localeOf(language);" in i18n
    formats = files["src/shared/lib/format.ts"]
    assert 'import { getLocale, t } from "@/shared/lib/i18n";' in formats
    assert 'return numberFormat({ style: "currency", currency }).format(Number(value));' in formats
    calendar = files["src/shared/ui/calendar.tsx"]
    assert "weekStartsOn={firstWeekday()}" in calendar
    assert 'labelNext: () => t("Go to the next month"),' in calendar
    assert "item.value.toLocaleString(getLocale())" in files["src/shared/ui/chart.tsx"]
    plain = {f.path: f.content for f in generate(plain_example(), binding).files}
    assert (
        "new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })"
        in plain["src/shared/lib/format.ts"]
    )
    assert (
        'date.toLocaleString("default", { month: "short" })' in plain["src/shared/ui/calendar.tsx"]
    )
    assert "item.value.toLocaleString()" in plain["src/shared/ui/chart.tsx"]


@pytest.mark.parametrize("binding", [react.BINDING, nextjs.BINDING], ids=["react", "nextjs"])
def test_the_calendar_starts_the_week_on_the_first_day_of_the_locale(binding: Binding) -> None:
    room_booking = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"
    text = room_booking.read_text() + dedent(
        """\
        translations:
          default: en
          languages:
            en: { label: English, locale: en-GB }
            de: { label: Deutsch }
        """
    )
    files = {
        f.path: f.content for f in generate(load_definition_text(text, "app.yaml"), binding).files
    }
    grid = files["src/shared/ui/calendar-grid.tsx"]
    assert "return addDays(day, -((day.getDay() - firstWeekday() + 7) % 7));" in grid
    assert "rangeFormat().formatRange(first, addDays(first, 6))" in grid
    assert "{weekdayFormat().format(day)}" in grid
    plain = {f.path: f.content for f in generate(load_definition(room_booking), binding).files}
    assert (
        "return addDays(day, -((day.getDay() + 6) % 7));"
        in plain["src/shared/ui/calendar-grid.tsx"]
    )


def test_finish_adds_t_to_an_import_of_the_module(example: AppDefinition) -> None:
    content = (
        'import { getLocale } from "@/shared/lib/i18n";\n\nexport const a = t("A") + getLocale();\n'
    )
    assert finish("src/a.ts", content, example) == (
        'import { getLocale, t } from "@/shared/lib/i18n";\n\n'
        'export const a = t("A") + getLocale();\n'
    )
    content = 'import { getLocale } from "@/shared/lib/i18n"\n\nexport const a = t("A")\n'
    assert finish("src/a.tsx", content, example).startswith(
        'import { getLocale, t } from "@/shared/lib/i18n"\n'
    )


def test_nextjs_renders_the_language_of_the_request(example: AppDefinition) -> None:
    files = {f.path: f.content for f in generate(example, nextjs.BINDING).files}
    layout = files["app/layout.tsx"]
    assert "const language = await requestLanguage();" in layout
    assert "<html lang={localeOf(language)} suppressHydrationWarning>" in layout
    assert "<Providers language={language}>{children}</Providers>" in layout
    server = files["src/shared/lib/i18n-server.ts"]
    assert "(await cookies()).get(LANGUAGE_COOKIE)?.value" in server
    assert 'matchLanguage((await headers()).get("accept-language"))' in server
    i18n = files["src/shared/lib/i18n.ts"]
    assert 'export const LANGUAGE_COOKIE = "project-tracker-language";' in i18n
    assert "store.enterWith(language);" in i18n
    assert "const translation = messages[active()]?.[text] ?? text;" in i18n
    route = files["app/(app-shell)/projects/page.tsx"]
    assert 'return inRequestLanguage(() => ({ title: t("Projects") }));' in route
    actions = files["src/shared/api/server.ts"]
    assert "return inRequestLanguage(() => attemptAction(body, options));" in actions
    assert 'message: t("The server could not do the operation.")' in actions
    assert "message: issueMessage(issue)," in actions
    assert "router.refresh();" in files["src/features/switch-language/ui/language-switch.tsx"]
    react_files = {f.path: f.content for f in generate(example, react.BINDING).files}
    assert "src/shared/lib/i18n-server.ts" not in react_files
    assert (
        "window.localStorage.setItem(STORAGE_KEY, language);"
        in react_files["src/shared/lib/i18n.ts"]
    )
    plain = {f.path: f.content for f in generate(plain_example(), nextjs.BINDING).files}
    assert '<html lang="en" suppressHydrationWarning>' in plain["app/layout.tsx"]
    assert "src/shared/lib/i18n-server.ts" not in plain


def test_the_nextjs_server_actions_translate_their_messages() -> None:
    room_booking = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"
    text = room_booking.read_text() + dedent(
        """\
        translations:
          default: en
          languages:
            en: { label: English }
            de: { label: Deutsch }
        """
    )
    definition = load_definition_text(text, str(room_booking))
    files = {f.path: f.content for f in generate(definition, nextjs.BINDING).files}
    assert 'super(t("Sign in to do this."));' in files["src/shared/auth/session.ts"]
    assert 'super(t("Your role may not do this operation."));' in files["src/shared/auth/access.ts"]
    sign_in = files["src/shared/auth/actions.ts"]
    assert "await inRequestLanguage(() => t(" in sign_in
    repository = files["src/shared/db/repository.ts"]
    assert "throw new ValidationError(t(rule.message));" in repository
    assert "? t(workflow.message)" in repository
    assert 't("The state of {entity} cannot change from {before} to {after}.", {' in repository
