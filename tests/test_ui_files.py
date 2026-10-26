"""Tests of the file fields in the forms, the views, and the React stores (ADR 0027)."""

import re
from pathlib import Path

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen import generate
from appgen.gen.binding import Binding

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "files.yaml"
FORM = "src/features/new-document-form/ui/new-document-form.tsx"
EDIT = "src/features/edit-document-form/ui/edit-document-form.tsx"
TABLE = "src/widgets/document-table/ui/document-table-view.tsx"
CARDS = "src/widgets/document-cards/ui/document-cards-view.tsx"
DETAIL = "src/widgets/document-detail/ui/document-detail-view.tsx"


def files_of(definition: AppDefinition, binding: Binding) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, binding).files}


def api_definition() -> AppDefinition:
    """The fixture with the React data source `api`: the FastAPI app has the records."""
    text = re.sub(r"(?m)^app:\n", "app:\n  x-react-data: api\n", FIXTURE.read_text(), count=1)
    return load_definition_text(text, str(FIXTURE))


@pytest.fixture(scope="module", params=["react", "nextjs"])
def ui(request: pytest.FixtureRequest) -> dict[str, str]:
    binding = react.BINDING if request.param == "react" else nextjs.BINDING
    return files_of(load_definition(FIXTURE), binding)


@pytest.fixture(scope="module")
def mock() -> dict[str, str]:
    return files_of(load_definition(FIXTURE), react.BINDING)


@pytest.fixture(scope="module")
def api() -> dict[str, str]:
    return files_of(api_definition(), react.BINDING)


def test_a_form_field_of_a_file_is_a_file_input_with_the_rule_of_the_field(
    ui: dict[str, str],
) -> None:
    form = ui[FORM]
    assert 'import { FileInput, fileAllowed } from "@/shared/ui/form-widgets/file-input";' in form
    assert "  scan: File | FileValue | null;" in form
    assert (
        'const SCAN_FILE_RULE = { maxSize: 5242880, types: ["application/pdf", "image/*"] };'
        in (form)
    )
    assert (
        '<FileInput id="new-document-scan" value={values.scan} '
        'onChange={(value) => change("scan", value)} rule={SCAN_FILE_RULE}' in form
    )
    assert "values.scan.size > SCAN_FILE_RULE.maxSize) errors.scan ??= " in form
    assert '"The file is larger than 5 MB."' in form
    assert '!fileAllowed(values.scan, SCAN_FILE_RULE.types)) errors.scan ??= "Select a file' in form
    assert 'if (values.cover === null) errors.cover ??= "Select a cover image.";' in form
    assert "src/shared/ui/form-widgets/file-input.tsx" in ui


def test_a_form_uploads_the_files_after_the_save(ui: dict[str, str]) -> None:
    form = ui[FORM]
    # The create takes no file: toInput leaves out the file fields.
    to_input = form[form.index("function toInput(") :].split("\n}\n", 1)[0]
    assert "scan" not in to_input and "cover" not in to_input
    assert "async function saveFiles(id: string, values: Values): Promise<void> {" in form
    assert '    await documentFiles.upload(id, "scan", values.scan);' in form
    assert "        await saveFiles(result.id, values);" in form
    edit = ui[EDIT]
    assert (
        "async function saveFiles(id: string, values: Values, record: Document | undefined)" in edit
    )
    remove = "  } else if (values.scan === null && record?.scan) {\n    await documentFiles.remove("
    assert remove + 'id, "scan");' in edit
    assert "scan: record ? (record.scan ?? null) : null," in edit


def test_the_views_show_images_file_links_and_avatars(ui: dict[str, str]) -> None:
    table = ui[TABLE]
    assert "cell: ({ row: { original: row } }) => <ImageValue file={row.cover} />," in table
    assert "cell: ({ row: { original: row } }) => <FileLink file={row.scan} />," in table
    # A view does not sort by a file.
    cover = table[table.index('id: "cover"') :].split("},", 1)[0]
    assert "enableSorting: false" in cover
    cards = ui[CARDS]
    assert '<ImageValue file={row.cover} size="cover" />' in cards
    assert 'image={lookups.person.get(row.ownerId ?? "")?.avatar?.url} />' in cards
    detail = ui[DETAIL]
    assert '<ImageValue file={record.cover} size="lg" />' in detail
    assert "<FileLink file={record.scan} />" in detail
    people = ui["src/widgets/person-table/ui/person-table-view.tsx"]
    assert '<AvatarValue name={String(row.name ?? "")} image={row.avatar?.url} />' in people
    assert "export function fileSize(size: number): string {" in ui["src/shared/lib/format.ts"]


def test_the_next_js_app_shows_the_images_with_img(ui: dict[str, str]) -> None:
    value = ui["src/shared/ui/values/file-value.tsx"]
    assert "<img" in value
    lint = "// eslint-disable-next-line @next/next/no-img-element"
    assert (lint in value) == ("next.config.ts" in ui)


def test_the_mock_store_keeps_the_files_as_object_urls(mock: dict[str, str]) -> None:
    api = mock["src/entities/document/api/document-api.ts"]
    assert (
        "export const documentFiles: FileApi<Document, DocumentFileField> = "
        "documentApi.files<DocumentFileField>(" in api
    )
    assert '    scan: { maxSize: 5242880, types: ["application/pdf", "image/*"] },' in api
    assert '  () => requireOperation("update_document"),' in api
    store = mock["src/shared/api/mock-store.ts"]
    assert "url: URL.createObjectURL(file)" in store
    assert "export class FileError extends Error {" in store
    data = mock["src/entities/document/api/document-mock-data.ts"]
    assert '"url": "data:application/pdf;base64,JVBERi0' in data
    assert '"avatar": null' in mock["src/entities/person/api/person-mock-data.ts"]
    assert "  documentFiles,\n" in mock["src/entities/document/index.ts"]


def test_the_http_store_sends_the_files_to_the_fastapi_endpoints(api: dict[str, str]) -> None:
    entity = api["src/entities/document/api/document-api.ts"]
    assert 'documentApi.files<DocumentFileField>({\n  scan: "scan",' in entity
    # The FastAPI app does not sort by a file.
    assert '  sorts: ["title"],' in entity
    store = api["src/shared/api/http-store.ts"]
    assert "const body = new FormData();" in store
    http = api["src/shared/api/http.ts"]
    assert (
        "body: body === undefined || body instanceof FormData ? body : JSON.stringify(body),"
        in (http)
    )


def test_the_fastapi_app_has_no_sort_key_for_a_file_column() -> None:
    files = files_of(load_definition(FIXTURE), fastapi.BINDING)
    sortable = files["app/features/documents/list_documents.py"].split("SORTABLE = {", 1)[1]
    sortable = sortable.split("\n}\n", 1)[0]
    assert '"title": Document.title,' in sortable
    assert '"cover"' not in sortable and '"scan"' not in sortable


def test_the_storage_is_an_element_that_the_react_binding_covers() -> None:
    assert "storage" in react.BINDING.covers
