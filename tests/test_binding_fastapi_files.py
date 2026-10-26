"""Tests of the file fields in the FastAPI binding (ADR 0027)."""

import base64
import re
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi
from appgen.bindings.shared.mock_data import mock_data
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen import GenerationError, generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "files.yaml"
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
    """
)


def files_of(definition: AppDefinition) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


@pytest.fixture(scope="module")
def library() -> dict[str, str]:
    return files_of(load_definition(FIXTURE))


def test_a_file_field_is_a_json_column_and_a_file_in_the_read_schema() -> None:
    files = files_of(load_definition_text(BASE, "app.yaml"))

    models = files["app/features/issues/models.py"]
    assert "    screenshot: Mapped[StoredFile | None] = mapped_column(JSON_TYPE)\n" in models
    assert "from app.core.types import StoredFile" in models
    migration = files["migrations/versions/0001_schema.py"]
    assert '            "screenshot",\n            sa.JSON().with_variant(' in migration
    schemas = files["app/features/issues/schemas.py"]
    read = schemas[schemas.index("class IssueRead") :]
    assert "    screenshot: FileRead | None\n" in read
    # The create and the change take no file: the endpoints of the file upload it.
    assert "screenshot" not in schemas[: schemas.index("class IssueRead")]
    assert "class StoredFile(TypedDict):" in files["app/core/types.py"]


def test_each_file_field_has_an_upload_and_a_delete_endpoint() -> None:
    files = files_of(load_definition_text(BASE, "app.yaml"))

    module = files["app/features/issues/files.py"]
    assert "SCREENSHOT = FileRule(\n    max_size=2097152,\n    types=(" in module
    assert 'REPORT = FileRule(max_size=10485760, types=("application/pdf", "text/*"))' in module
    assert '    "/{id}/screenshot",\n' in module
    assert 'operation_id="upload_issue_screenshot",' in module
    assert 'operation_id="delete_issue_report",' in module
    assert 'stored = await upload(storage, file, SCREENSHOT, f"issues/{id}/screenshot")' in module
    assert "router.include_router(files.router)" in files["app/features/issues/router.py"]
    assert (
        "await repository.delete(session, record, storage)"
        in (files["app/features/issues/delete_issue.py"])
    )
    repository = files["app/features/issues/repository.py"]
    assert "files = [record.screenshot, record.report]" in repository
    assert "await delete_files(storage, files)" in repository
    assert '("put", "/issues/{id}/screenshot"),' in files["tests/test_openapi.py"]
    assert '("get", "/file-links/{token}"),' in files["tests/test_openapi.py"]


def test_the_storage_module_keeps_the_files_in_the_folder_or_the_bucket(
    library: dict[str, str],
) -> None:
    local = files_of(load_definition_text(BASE, "app.yaml"))

    assert "class BucketStorage" not in local["app/core/storage.py"]
    assert "boto3" not in local["pyproject.toml"]
    storage = library["app/core/storage.py"]
    assert "class BucketStorage:" in storage
    assert "    if settings.library_bucket:\n        return BucketStorage(settings)" in storage
    pyproject = library["pyproject.toml"]
    assert '"boto3>=' in pyproject
    assert '"moto[s3]>=' in pyproject
    assert '"types-boto3-lite[s3]>=' in pyproject
    config = library["app/core/config.py"]
    assert '    storage_folder: str = "uploads"\n' in config
    assert '    library_bucket: str = ""\n' in config
    assert '    storage_link_secret: str = ""\n' in config
    assert "    public_url: str = " in config
    main = library["app/main.py"]
    assert "app.state.storage = make_storage(settings)" in main
    assert "app.add_middleware(FileLinkMiddleware, links=links, public_url=" in main
    assert "app.include_router(storage_router)" in main
    assert "LIBRARY_BUCKET=" in library[".env.example"]
    assert "STORAGE_LINK_SECRET=" in library["deploy/kubernetes/secret.example.env"]
    assert "## Files" in library["README.md"]


def test_the_endpoints_of_the_files_need_the_update_operation_else_the_create_operation(
    library: dict[str, str],
) -> None:
    access = library["app/core/access.py"]

    assert '    "upload_document_scan": "update_document",\n' in access
    assert '    "delete_person_avatar": "update_person",\n' in access
    assert '    "upload_note_attachment": "create_note",\n' in access
    documents = library["app/features/documents/files.py"]
    assert 'Scope = Annotated[RecordScope | None, Depends(scope_of("change"))]' in documents
    assert "record = await repository.get(session, id, scope)" in documents
    notes = library["app/features/notes/files.py"]
    # A note embeds its document, which a record rule can hide.
    assert "await repository.hide(session, [result], scope)" in notes


def test_an_entity_without_a_change_or_a_create_has_no_endpoints_of_files() -> None:
    text = BASE.replace("crud: true", "crud: [read, list]")
    files = files_of(load_definition_text(text, "app.yaml"))

    assert "app/features/issues/files.py" not in files
    assert "tests/features/issues/test_files.py" not in files
    assert "screenshot: FileRead | None" in files["app/features/issues/schemas.py"]


def test_an_operation_with_the_id_of_an_endpoint_of_a_file_stops_the_generation() -> None:
    text = BASE + dedent(
        """\
        operations:
          upload_issue_screenshot: { kind: custom, entity: Issue }
        """
    )

    with pytest.raises(GenerationError, match="operation ID 'upload_issue_screenshot'"):
        generate(load_definition_text(text, "app.yaml"), fastapi.BINDING)


def test_the_seed_keeps_the_files_of_the_seed_records_in_the_code(
    library: dict[str, str],
) -> None:
    definition = load_definition(FIXTURE)
    content = (ROOT / "tests" / "fixtures" / "files" / "guide.pdf").read_bytes()

    seed_files = library["app/core/seed_files.py"]
    key = re.search(r'"(documents/[0-9a-f-]+/scan/seed-[0-9a-f]{12})"', seed_files)
    assert key is not None
    chunks = seed_files[seed_files.index(key.group(0)) :].split("),", 1)[0]
    encoded = "".join(re.findall(r'^\s+"([A-Za-z0-9+/=]+)"$', chunks, re.MULTILINE))
    assert base64.b64decode(encoded) == content
    rows = library["app/core/seed_data.py"]
    assert f'"key": {key.group(0)},' in rows
    assert f'"size": {len(content)},' in rows
    assert '"type": "application/pdf",' in rows
    assert '"avatar": None,' in rows
    assert "storage=storage" in library["app/core/seed.py"] or (
        "storage: Storage | None = None" in library["app/core/seed.py"]
    )
    assert (
        "seed_database(session, settings.seed_password, storage=app.state.storage)"
        in (library["app/main.py"])
    )
    assert definition.seed["Document"].records["guide"].files["scan"].content == content


def test_the_generated_records_have_no_files() -> None:
    records = mock_data(load_definition(FIXTURE))

    assert records["Person"][0]["avatar"] == "files/ada.png"
    assert {record["attachment"] for record in records["Note"]} == {None}


def test_the_generated_tests_upload_a_file_that_the_field_allows(library: dict[str, str]) -> None:
    documents = library["tests/features/documents/test_files.py"]

    assert 'SAMPLE = ("sample.png", PNG, "image/png")' in documents
    assert 'other = ("page.html", b"<script>alert(1)</script>", "text/html")' in documents
    assert '("/cover", ("sample.png", PNG, "image/png")),' in documents
    notes = library["tests/features/notes/test_files.py"]
    # A field that allows all types has no test of a type that it does not allow.
    assert "def test_a_type_that_the_field_does_not_allow_gives_415" not in notes
    assert (
        "def test_the_seed_saves_the_files_of_the_new_seed_records("
        in (library["tests/test_seed.py"])
    )
    assert (
        "async def test_the_bucket_saves_reads_and_deletes_a_file()"
        in (library["tests/test_storage.py"])
    )


def test_the_storage_is_an_element_that_the_binding_covers() -> None:
    assert "storage" in fastapi.BINDING.covers
