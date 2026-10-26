"""Tests of the file fields in the Next.js binding (ADR 0027)."""

import base64
import re
from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import nextjs
from appgen.bindings.nextjs.model import UPLOAD_MARGIN
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
          test_report: { type: file, types: [application/pdf, "text/*"] }
    """
)


def files_of(definition: AppDefinition) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, nextjs.BINDING).files}


@pytest.fixture(scope="module")
def library() -> dict[str, str]:
    return files_of(load_definition(FIXTURE))


@pytest.fixture(scope="module")
def issues() -> dict[str, str]:
    return files_of(load_definition_text(BASE, "app.yaml"))


def test_a_file_field_is_a_jsonb_column_and_a_file_value_in_the_record(
    issues: dict[str, str],
) -> None:
    schema = issues["src/shared/db/schema/issue.ts"]
    assert '  screenshot: jsonb("screenshot").$type<StoredFile>(),\n' in schema
    assert 'import type { StoredFile } from "@/shared/storage";' in schema
    types = issues["src/entities/issue/model/types.ts"]
    record = types[types.index("export type Issue =") : types.index("export type IssueInput")]
    assert "  screenshot: FileValue | null;" in record
    assert "  testReport: FileValue | null;" in record
    # The create and the change take no file: the upload comes after the create.
    rest = types[types.index("export type IssueInput") :]
    assert "screenshot" not in rest.split("export type IssueFileField")[0]
    assert 'export type IssueFileField = "screenshot" | "testReport";' in types
    assert "screenshot" not in issues["src/entities/issue/model/schema.ts"]
    assert "export type FileValue = {" in issues["src/shared/api/types.ts"]


def test_the_server_actions_upload_and_delete_the_files(issues: dict[str, str]) -> None:
    actions = issues["src/entities/issue/api/issue-actions.ts"]
    assert "export async function uploadIssueFileAction(" in actions
    assert "export async function removeIssueFileAction(" in actions
    assert "  screenshot: { maxSize: 2097152, types: [" in actions
    assert '  testReport: { maxSize: 10485760, types: ["application/pdf", "text/*"] },' in actions
    assert 'uploadFile(data.get("file"), rule, `issue/${recordId}/${field}`, field)' in actions
    api = issues["src/entities/issue/api/issue-api.ts"]
    assert "export const issueFiles: FileApi<Issue, IssueFileField> = createFileApi(" in api
    assert "  issueFiles,\n" in issues["src/entities/issue/index.ts"]
    assert "export function createFileApi<" in issues["src/shared/api/client.ts"]


def test_the_route_of_the_files_checks_the_access_of_the_read(library: dict[str, str]) -> None:
    route = library["app/files/document/[id]/[field]/route.ts"]
    assert 'await requireOperation("read_document");' in route
    assert 'const scope = await recordScope("Document", "read");' in route
    assert "documentRepository.storedFile(id, key, scope)" in route
    assert '  "scan": "scan",' in route
    repository = library["src/entities/document/api/document-repository.ts"]
    assert '    cover: "/files/document/{id}/cover",' in repository


def test_the_upload_needs_the_update_else_the_create(library: dict[str, str]) -> None:
    documents = library["src/entities/document/api/document-actions.ts"]
    upload = documents[documents.index("export async function uploadDocumentFileAction") :]
    assert '{ changes: true, operation: "update_document" }' in upload
    assert 'const scope = await recordScope("Document", "change");' in upload
    notes = library["src/entities/note/api/note-actions.ts"]
    upload = notes[notes.index("export async function uploadNoteFileAction") :]
    assert '{ changes: true, operation: "create_note" }' in upload


def test_the_storage_keeps_the_files_in_the_folder_or_the_bucket(
    issues: dict[str, str], library: dict[str, str]
) -> None:
    local = issues["src/shared/storage/storage.ts"]
    assert "class BucketStorage" not in local
    assert "@aws-sdk/client-s3" not in issues["package.json"]
    storage = library["src/shared/storage/storage.ts"]
    assert "export class BucketStorage implements Storage {" in storage
    assert "  if (env.LIBRARY_BUCKET) {\n    return new BucketStorage(env);" in storage
    assert '"@aws-sdk/client-s3": "' in library["package.json"]
    assert 'import "server-only";' in library["src/shared/storage/upload.ts"]
    # The seed runs outside Next.js, so the storage module has no `server-only`.
    assert "server-only" not in storage
    assert "LIBRARY_BUCKET=" in library[".env.example"]
    assert "STORAGE_FOLDER: /app/uploads" in library["compose.yaml"]
    assert "RUN install -d -o node -g node /app/uploads" in library["Dockerfile"]
    assert "## Files" in library["README.md"]


def test_the_server_actions_take_bodies_with_the_largest_file(issues: dict[str, str]) -> None:
    small = BASE.replace('types: [application/pdf, "text/*"]', "max_size: 1MB")
    config = files_of(load_definition_text(small, "app.yaml"))["next.config.ts"]
    assert f"serverActions: {{ bodySizeLimit: {2 * 1024 * 1024 + UPLOAD_MARGIN} }}" in config
    # The proxy reads bodies of 10 MB by default.
    assert "proxyClientMaxBodySize" not in config
    large = 10 * 1024 * 1024 + UPLOAD_MARGIN
    assert f"proxyClientMaxBodySize: {large}," in issues["next.config.ts"]


def test_a_local_storage_has_a_volume_in_kubernetes(issues: dict[str, str]) -> None:
    assert "  - files-volume.yaml\n" in issues["deploy/kubernetes/kustomization.yaml"]
    assert "claimName: issues-web-files" in issues["deploy/kubernetes/deployment.yaml"]
    assert "ReadWriteMany" in issues["deploy/kubernetes/files-volume.yaml"]


def test_the_seed_saves_the_files_of_the_seed_records(library: dict[str, str]) -> None:
    definition = load_definition(FIXTURE)
    content = (ROOT / "tests" / "fixtures" / "files" / "guide.pdf").read_bytes()

    seed_files = library["src/shared/db/seed-files.ts"]
    key = re.search(r'"(document/[0-9a-f-]+/scan/seed-[0-9a-f]{12})"', seed_files)
    assert key is not None
    chunk = seed_files[seed_files.index(key.group(0)) :].split("},", 1)[0]
    encoded = "".join(re.findall(r'^\s+"([A-Za-z0-9+/=]+)"(?: \+|,)$', chunk, re.MULTILINE))
    assert base64.b64decode(encoded) == content
    rows = library["src/shared/db/seed-data.ts"]
    assert f'scan: {{ key: {key.group(0)}, name: "guide.pdf", size: {len(content)},' in rows
    seed = library["src/shared/db/seed.ts"]
    assert (
        "export async function seedDatabase(db: Database, storage: Storage = getStorage())" in seed
    )
    assert 'await storage.save(file.key, Buffer.from(file.content, "base64"), file.type);' in seed
    assert definition.seed["Document"].records["guide"].files["scan"].content == content


def test_a_definition_without_seed_files_has_no_seed_file_module(issues: dict[str, str]) -> None:
    assert "src/shared/db/seed-files.ts" not in issues
    assert "storage" not in issues["src/shared/db/seed.ts"]


def test_the_forms_and_the_views_do_not_show_files_yet() -> None:
    text = BASE + dedent(
        """\
        pages:
          issues: { path: /issues, title: Issues, content: { view: issue_table } }
        ui:
          views:
            issue_table: { kind: table, entity: Issue, columns: { screenshot: {} } }
        """
    )
    with pytest.raises(GenerationError, match="The views do not show 'image' fields yet"):
        generate(load_definition_text(text, "app.yaml"), nextjs.BINDING)


def test_the_storage_is_an_element_that_the_binding_covers() -> None:
    assert "storage" in nextjs.BINDING.covers
