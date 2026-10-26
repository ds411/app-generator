"""Tests of the translatable fields: the values of a field in each language (ADR 0026)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"
BASE = dedent(
    """\
    version: 0
    app: { name: notes, title: Notes }
    entities:
      Note:
        crud: true
        display_field: title
        fields:
          title: { type: string, required: true, max_length: 80, translatable: true }
          body: { type: text, translatable: true }
          pages: { type: integer }
    translations:
      default: en
      languages:
        en: { label: English }
        de: { label: Deutsch, text: { Notes: Notizen } }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(definition: AppDefinition, binding: Binding = fastapi.BINDING) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_string_or_text_field_can_be_translatable() -> None:
    assert codes(BASE) == []
    fields = load_definition_text(BASE, "app.yaml").entities["Note"].fields
    assert [name for name, field in fields.items() if field.translatable] == ["title", "body"]


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        pytest.param(
            "translations:",
            "x-translations:",
            ("invalid-option", "entities.Note.fields.title"),
            id="without-translations",
        ),
        pytest.param(
            "{ type: integer }",
            "{ type: integer, translatable: true }",
            ("invalid-option", "entities.Note.fields.pages"),
            id="integer",
        ),
        pytest.param(
            "{ type: integer }",
            "{ type: string, computed: \"title + '!'\", translatable: true }",
            ("invalid-option", "entities.Note.fields.pages"),
            id="computed",
        ),
        pytest.param(
            "pages: { type: integer }",
            "title_translations: { type: json }",
            ("duplicate-name", "entities.Note.fields.title_translations"),
            id="name-of-the-values",
        ),
    ],
)
def test_the_validator_reports_a_translatable_field_that_cannot_be(
    old: str, new: str, expected: tuple[str, str]
) -> None:
    text = BASE.replace(old, new, 1)

    assert expected in codes(text)


def test_a_param_cannot_be_translatable() -> None:
    operation = dedent(
        """\
        operations:
          rename_note:
            kind: custom
            entity: Note
            params:
              title: { type: string, translatable: true }
            returns: Note
        """
    )

    assert codes(BASE + operation) == [
        ("invalid-option", "operations.rename_note.params.title"),
    ]


def test_the_fastapi_app_stores_the_values_of_each_language() -> None:
    files = files_of(load_definition_text(BASE, "app.yaml"))

    models = files["app/features/notes/models.py"]
    assert "    title_translations: Mapped[dict[str, str] | None] = mapped_column(JSON_TYPE)\n" in (
        models
    )
    assert "pages_translations" not in models
    assert '"title_translations",' in files["migrations/versions/0001_schema.py"]
    schemas = files["app/features/notes/schemas.py"]
    assert "TitleText = Annotated[str, Field(max_length=80)]\n" in schemas
    assert "    title_translations: dict[Language, TitleText | None] | None = None\n" in schemas
    assert "    body_translations: dict[Language, str | None] | None = None\n" in schemas
    assert "    title_translations: dict[str, str] | None = None\n" in schemas
    assert 'return translated(self, "title", "body")' in schemas
    assert 'return reject_empty_default(self, "title")' in schemas
    repository = files["app/features/notes/repository.py"]
    assert 'store_translations(record, values, "title", "body", created=created)' in repository
    router = files["app/features/notes/router.py"]
    assert "read_note.router, dependencies=[Depends(translations_query)]" in router
    assert "delete_note.router)" in router
    list_notes = files["app/features/notes/list_notes.py"]
    assert (
        'translations: Literal["all"] | None = Field(default=None, description=TRANSLATIONS)'
        in (list_notes)
    )
    assert "show_translations(query.translations)" in list_notes
    i18n = files["app/core/i18n.py"]
    assert 'type Language = Literal["en", "de"]' in i18n
    assert "def store_translations(" in i18n
    assert "tests/features/notes/test_translations.py" in files
    readme = files["README.md"]
    assert (
        "These fields have a value in each language:\n\n- `Note.title`\n- `Note.body`\n" in readme
    )


def test_an_api_without_translatable_fields_has_no_values_in_each_language() -> None:
    files = files_of(load_definition_text(BASE.replace(", translatable: true", ""), "app.yaml"))

    assert "def store_translations(" not in files["app/core/i18n.py"]
    assert "_translations" not in files["app/features/notes/models.py"]
    assert "Depends" not in files["app/features/notes/router.py"]
    assert "tests/features/notes/test_translations.py" not in files


def test_the_generated_tests_change_the_values_of_the_tasks_of_the_example() -> None:
    files = files_of(load_definition(EXAMPLE))

    tests = files["tests/features/tasks/test_translations.py"]
    assert 'FIELD = "title"' in tests
    assert "async def test_a_read_gives_the_value_of_the_language_of_the_request(" in tests
    assert "async def test_a_change_sets_the_value_of_the_language_of_the_request(" in tests
    assert "async def test_a_new_record_takes_the_value_of_the_request_as_its_default(" in tests
    assert "async def test_a_list_gives_the_values_of_the_language_of_the_request(" in tests
    assert "tests/features/projects/test_translations.py" not in files


def test_the_mock_records_have_a_value_in_each_language() -> None:
    code = "code: { type: string, pattern: '^[a-z]+$', translatable: true }\n      "
    text = BASE.replace("max_length: 80", "max_length: 20").replace("body:", code + "body:")
    records = mock_data(load_definition_text(text, "app.yaml"))["Note"]

    for record in records:
        title = record["title_translations"]["de"]
        assert title.endswith(" (Deutsch)") and len(title) <= 20
        assert title.removesuffix(" (Deutsch)") in record["title"]
        # A value of a pattern keeps its form.
        assert record["code_translations"] == {"de": record["code"]}
        assert record["body"] is None or record["body_translations"] == {
            "de": record["body"] + " (Deutsch)"
        }


def test_the_front_ends_keep_the_values_of_each_language() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    next_files = files_of(definition, nextjs.BINDING)
    react_files = files_of(definition, react.BINDING)

    types = react_files["src/entities/note/model/types.ts"]
    assert "  titleTranslations: Partial<Record<string, string | null>> | null;" in types
    schema = next_files["src/entities/note/model/schema.ts"]
    values = "z.record(z.string(), z.string().max(80).nullable())"
    assert f"  titleTranslations: {values}.nullable().optional()," in schema
    assert (
        '    "titleTranslations": {\n      "de": '
        in react_files["src/entities/note/api/note-mock-data.ts"]
    )
    assert '  ["title", "body"],' in react_files["src/entities/note/api/note-api.ts"]
    store = react_files["src/shared/api/mock-store.ts"]
    assert "storeTranslations(this.defaults, input, this.translatable, true)" in store
    assert "export function translateRecord<" in react_files["src/shared/lib/i18n.ts"]
    table = next_files["src/shared/db/schema/note.ts"]
    assert (
        'titleTranslations: jsonb("title_translations").$type<Record<string, string>>(),' in table
    )
    assert (
        '  translatable: ["title", "body"],'
        in next_files["src/entities/note/api/note-repository.ts"]
    )
    assert "titleTranslations: {" in next_files["src/shared/db/seed-data.ts"]
    assert "translateRecord(" in next_files["src/shared/db/repository.ts"]


def test_the_react_api_client_asks_for_the_values_of_all_languages() -> None:
    text = BASE.replace("title: Notes }", "title: Notes, x-react-data: api }")
    files = files_of(load_definition_text(text, "app.yaml"), react.BINDING)

    api = files["src/entities/note/api/note-api.ts"]
    assert '    "title_translations": "titleTranslations",' in api
    assert "  translations: true," in api
    assert 'search.set("translations", "all");' in files["src/shared/api/http-store.ts"]


def test_a_form_edits_the_value_of_each_language() -> None:
    files = files_of(load_definition(EXAMPLE), react.BINDING)

    form = files["src/features/edit-task-form/ui/edit-task-form.tsx"]
    assert "  titleTranslations: Record<string, string>;" in form
    assert (
        'title: record ? String(record.titleTranslations?.["en"] ?? record.title ?? "") : "",'
        in form
    )
    assert (
        'titleTranslations: { "de": record ? String(record.titleTranslations?.["de"] ?? "") : "" },'
        in form
    )
    assert (
        'titleTranslations: { "en": values.title.trim() || null, '
        '"de": values.titleTranslations["de"]?.trim() || null },' in form
    )
    assert 'id="edit-task-title-de" lang="de" dir="ltr" type="text"' in form
    assert 't("{field} ({language})", { field: t("Title"), language: "Deutsch" })' in form
    assert 'errors["titleTranslations.de"]' in form
    assert "function issueKey(" in files["src/shared/lib/form.ts"]


def test_an_app_without_translatable_fields_has_no_code_for_them() -> None:
    files = files_of(
        load_definition_text(BASE.replace(", translatable: true", ""), "app.yaml"), react.BINDING
    )

    assert "translateRecord" not in files["src/shared/lib/i18n.ts"]
    assert "Translations" not in files["src/entities/note/model/types.ts"]
    assert "storeTranslations" not in files["src/shared/api/mock-store.ts"]
