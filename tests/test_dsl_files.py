"""Tests of the file fields and the section `storage` in the DSL (ADR 0027)."""

import json
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import minimal, nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.schema import json_schema
from appgen.dsl.storage import (
    DEFAULT_IMAGE_TYPES,
    DEFAULT_MAX_SIZE,
    format_size,
    media_type_of,
    seed_files,
    type_allows,
)
from appgen.gen import GenerationError, generate

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(32))
BASE = dedent(
    """\
    version: 0
    app: { name: issues, title: Issues }
    storage: { kind: local }
    entities:
      Issue:
        crud: true
        display_field: title
        fields:
          title: { type: string, required: true }
          screenshot: { type: image, max_size: 2MB }
          report: { type: file, types: [application/pdf, "text/*"] }
          votes: { type: integer }
    """
)


def codes(text: str, base_dir: Path | None = None) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml", base_dir)
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def messages(text: str, base_dir: Path | None = None) -> list[str]:
    definition = load_definition_text(text, "app.yaml", base_dir)
    return [d.message for d in validate_definition(definition)]


def test_the_file_and_image_types_take_a_size_and_media_types() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(BASE, "app.yaml")
    fields = definition.entities["Issue"].fields
    assert list(definition.entities["Issue"].file_fields) == ["screenshot", "report"]
    assert fields["screenshot"].max_size == 2 * 1024 * 1024
    assert fields["screenshot"].media_types == list(DEFAULT_IMAGE_TYPES)
    assert fields["report"].size_limit == DEFAULT_MAX_SIZE
    assert fields["report"].media_types == ["application/pdf", "text/*"]
    assert not fields["title"].is_file


@pytest.mark.parametrize(
    ("value", "size"),
    [(1000, 1000), ("512B", 512), ("1.5KB", 1536), ("5 MB", 5 * 1024**2), ("1gb", 1024**3)],
)
def test_a_size_is_a_number_of_bytes_or_a_text_with_a_unit(value: object, size: int) -> None:
    text = BASE.replace("max_size: 2MB", f"max_size: {json.dumps(value)}")
    definition = load_definition_text(text, "app.yaml")
    assert definition.entities["Issue"].fields["screenshot"].max_size == size


@pytest.mark.parametrize("value", ['"5 megabytes"', "0", '"MB"'])
def test_a_size_that_is_not_valid_is_an_error(value: str) -> None:
    from appgen.dsl import DefinitionError

    with pytest.raises(DefinitionError) as caught:
        load_definition_text(BASE.replace("2MB", value), "app.yaml")
    assert [d.code for d in caught.value.diagnostics] == ["invalid-value"]


def test_the_storage_has_a_kind_and_the_variables_of_its_settings() -> None:
    definition = load_definition_text(BASE.replace("kind: local", "kind: s3"), "app.yaml")
    assert definition.storage is not None
    assert definition.storage.variables == [
        ("folder_env", "STORAGE_FOLDER"),
        ("bucket_env", "STORAGE_BUCKET"),
        ("region_env", "STORAGE_REGION"),
        ("endpoint_env", "STORAGE_ENDPOINT"),
        ("access_key_env", "STORAGE_ACCESS_KEY_ID"),
        ("secret_key_env", "STORAGE_SECRET_ACCESS_KEY"),
    ]
    local = load_definition_text(BASE, "app.yaml").storage
    assert local is not None and local.variables == [("folder_env", "STORAGE_FOLDER")]


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        pytest.param(
            "max_size: 2MB",
            "types: [application/pdf]",
            ("invalid-value", "entities.Issue.fields.screenshot"),
            id="image-with-another-type",
        ),
        pytest.param(
            '"text/*"',
            "foo/bar",
            ("invalid-value", "entities.Issue.fields.report"),
            id="wrong-media-type",
        ),
        pytest.param(
            '"text/*"',
            "application/pdf",
            ("duplicate-name", "entities.Issue.fields.report"),
            id="duplicate-media-type",
        ),
        pytest.param(
            "max_size: 2MB",
            "required: true",
            ("invalid-option", "entities.Issue.fields.screenshot"),
            id="required",
        ),
        pytest.param(
            "max_size: 2MB",
            "unique: true",
            ("invalid-option", "entities.Issue.fields.screenshot"),
            id="unique",
        ),
        pytest.param(
            "max_size: 2MB",
            "default: logo.png",
            ("invalid-option", "entities.Issue.fields.screenshot"),
            id="default",
        ),
        pytest.param(
            "votes: { type: integer }",
            "votes: { type: integer, max_size: 1KB }",
            ("invalid-option", "entities.Issue.fields.votes"),
            id="max-size-of-another-type",
        ),
        pytest.param(
            "votes: { type: integer }",
            "votes: { type: file, computed: '1' }",
            ("invalid-option", "entities.Issue.fields.votes"),
            id="computed-file-field",
        ),
        pytest.param(
            "votes: { type: integer }",
            "votes: { type: integer, computed: 'screenshot * 2' }",
            ("unsuitable-field", "entities.Issue.fields.votes"),
            id="file-in-a-computed-field",
        ),
        pytest.param(
            "votes: { type: integer }",
            "votes: { type: integer }\n"
            "    rules:\n"
            "      one: { kind: unique, fields: [title, report], message: Taken. }",
            ("unsuitable-field", "entities.Issue.rules.one"),
            id="file-in-a-unique-rule",
        ),
        pytest.param(
            "votes: { type: integer }",
            "votes: { type: integer }\n"
            "    rules:\n"
            "      same: { kind: compare, field: report, op: ne, other: title, message: No. }",
            ("unsuitable-field", "entities.Issue.rules.same"),
            id="file-in-a-compare-rule",
        ),
    ],
)
def test_the_validator_reports_a_wrong_file_field(
    old: str, new: str, expected: tuple[str, str]
) -> None:
    assert old in BASE
    assert codes(BASE.replace(old, new)) == [expected]


def test_a_param_cannot_be_a_file() -> None:
    text = BASE + dedent(
        """\
        operations:
          attach:
            kind: custom
            entity: Issue
            params: { file: { type: file } }
        """
    )
    assert codes(text) == [("invalid-option", "operations.attach.params.file")]


def test_a_file_field_needs_the_storage() -> None:
    assert codes(BASE.replace("storage: { kind: local }", "")) == [
        ("invalid-option", "entities.Issue.fields.screenshot"),
        ("invalid-option", "entities.Issue.fields.report"),
    ]


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        pytest.param(
            "{ kind: table, entity: Issue, columns: { title: {} }, sort: { field: screenshot } }",
            "ui.views.issues.sort",
            id="sort",
        ),
        pytest.param(
            "{ kind: table, entity: Issue, columns: { title: {} },"
            " filters: { shot: { kind: select, field: screenshot } } }",
            "ui.views.issues.filters.shot",
            id="filter",
        ),
    ],
)
def test_a_view_cannot_sort_or_filter_by_a_file(view: str, expected: str) -> None:
    text = BASE + f"ui:\n  views:\n    issues: {view}\n"
    assert codes(text) == [("unsuitable-field", expected)]


def test_a_dashboard_filter_cannot_use_a_file() -> None:
    text = BASE + dedent(
        """\
        ui:
          dashboards:
            home:
              widgets:
                shots:
                  kind: stat
                  entity: Issue
                  aggregate: count
                  filter: { screenshot: x.png }
        """
    )
    assert codes(text) == [("unsuitable-field", "ui.dashboards.home.widgets.shots")]


def test_a_form_field_of_a_file_needs_a_widget() -> None:
    text = BASE.replace("crud: true", "crud: { forms: [create] }")
    assert ("missing-widget", "ui.forms.new_issue.fields.screenshot") in codes(text)


@pytest.mark.parametrize(
    ("storage", "expected"),
    [
        pytest.param(
            "{ kind: local, bucket_env: BUCKET }", ("invalid-option", "storage"), id="s3-key"
        ),
        pytest.param(
            "{ kind: local, folder_env: DATABASE_URL }",
            ("invalid-value", "storage"),
            id="reserved-variable",
        ),
        pytest.param(
            "{ kind: s3, secret_key_env: VITE_SECRET }",
            ("invalid-value", "storage"),
            id="public-secret",
        ),
        pytest.param(
            "{ kind: s3, region_env: STORAGE_BUCKET }",
            ("duplicate-name", "storage"),
            id="same-variable",
        ),
    ],
)
def test_the_validator_reports_a_wrong_storage(storage: str, expected: tuple[str, str]) -> None:
    text = BASE.replace("storage: { kind: local }", f"storage: {storage}")
    assert codes(text) == [expected]


def test_a_storage_variable_cannot_be_the_variable_of_an_api(tmp_path: Path) -> None:
    examples = Path(__file__).parent.parent / "examples" / "project-tracker"
    document = (examples / "apis" / "public-holidays.openapi.yaml").read_text()
    (tmp_path / "holidays.yaml").write_text(document)
    text = BASE.replace(
        "storage: { kind: local }", "storage: { kind: local, folder_env: HOLIDAYS_URL }"
    ) + dedent(
        """\
        apis:
          holidays:
            document: holidays.yaml
            base_url_env: HOLIDAYS_URL
            operations: [getPublicHolidays]
        """
    )
    assert codes(text, tmp_path) == [("duplicate-name", "storage")]


SEED = BASE + dedent(
    """\
    seed:
      Issue:
        records:
          login: { title: The sign-in fails, screenshot: files/login.png }
    """
)


def test_a_seed_record_gives_the_path_of_a_local_file(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "login.png").write_bytes(PNG)
    assert codes(SEED, tmp_path) == []
    definition = load_definition_text(SEED, "app.yaml", tmp_path)
    record = definition.seed["Issue"].records["login"]
    file = record.files["screenshot"]
    assert (file.path, file.name, file.content, file.media_type) == (
        "files/login.png",
        "login.png",
        PNG,
        "image/png",
    )
    assert [f.path for f in seed_files(definition)] == ["files/login.png"]
    assert file.hash.startswith("sha256:")


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        pytest.param(None, b"", "The file 'files/login.png' does not exist.", id="missing"),
        pytest.param(
            "login.png",
            b"x" * (2 * 1024 * 1024 + 1),
            "The file 'files/login.png' has 2 MB, but the field allows 2 MB or less.",
            id="too-large-for-the-field",
        ),
        pytest.param(
            "login.png",
            b"x" * (1024 * 1024 + 1),
            "The file 'files/login.png' has 1 MB. A file of a seed record can have 1 MB or "
            "less, because the apps keep it in their code.",
            id="too-large-for-the-code",
        ),
    ],
)
def test_the_validator_reports_a_wrong_seed_file(
    tmp_path: Path, name: str | None, content: bytes, message: str
) -> None:
    (tmp_path / "files").mkdir()
    if name is not None:
        (tmp_path / "files" / name).write_bytes(content)
    assert messages(SEED, tmp_path) == [message]


def test_the_type_of_a_seed_file_must_suit_the_field(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "login.txt").write_text("text")
    (tmp_path / "files" / "login.xyz").write_text("text")
    text = SEED.replace("files/login.png", "files/login.txt")
    assert messages(text, tmp_path) == [
        "The file 'files/login.txt' has the type 'text/plain', but the field allows only "
        "'image/png', 'image/jpeg', 'image/gif', 'image/webp'."
    ]
    unknown = SEED.replace("files/login.png", "files/login.xyz")
    assert codes(unknown, tmp_path) == [("invalid-value", "seed.Issue.records.login")]


def test_a_seed_file_can_be_in_a_csv_file(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "login.png").write_bytes(PNG)
    (tmp_path / "issues.csv").write_text("key,title,screenshot\nlogin,Login, files/login.png\n")
    text = BASE + "seed:\n  Issue: { file: issues.csv }\n"
    definition = load_definition_text(text, "app.yaml", tmp_path)
    assert validate_definition(definition) == []
    assert definition.seed["Issue"].records["login"].files["screenshot"].content == PNG


def test_the_manifest_records_the_hash_of_each_seed_file(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "login.png").write_bytes(PNG)
    definition = load_definition_text(SEED, "app.yaml", tmp_path)
    result = generate(definition, minimal.BINDING)
    file = definition.seed["Issue"].records["login"].files["screenshot"]
    assert result.documents["files/login.png"] == file.hash


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING])
def test_a_binding_without_file_fields_stops(binding: object) -> None:
    from appgen.gen import Binding

    assert isinstance(binding, Binding)
    definition = load_definition_text(BASE, "app.yaml")
    with pytest.raises(GenerationError, match="does not generate 'image' fields yet"):
        generate(definition, binding)


def test_the_schema_describes_the_file_options_and_the_storage() -> None:
    schema = json_schema()
    field = schema["$defs"]["Field"]["properties"]
    assert {"type": "string", "pattern": field["max_size"]["anyOf"][-1]["pattern"]} in field[
        "max_size"
    ]["anyOf"]
    assert {"file", "image"} <= set(schema["$defs"]["FieldType"]["enum"])
    assert schema["properties"]["storage"]["anyOf"][0] == {"$ref": "#/$defs/Storage"}


def test_the_helpers_give_sizes_and_types() -> None:
    assert [format_size(n) for n in (100, 1536, 5 * 1024**2, 1024**3)] == [
        "100 B",
        "1.5 KB",
        "5 MB",
        "1 GB",
    ]
    assert type_allows([], "application/zip")
    assert type_allows(["image/*"], "image/png")
    assert not type_allows(["image/png"], "image/jpeg")
    assert media_type_of("a/b/Photo.JPG") == "image/jpeg"
    assert media_type_of("archive.tar") is None
