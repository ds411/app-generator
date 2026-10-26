"""Forms, files, text and binary answers, cookies, and OAuth 2.0 in the clients (ADR 0019)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from appgen.bindings.shared.integrations import ts_apis, ts_features
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.dsl.openapi import (
    EXAMPLE_TEXT,
    ArraySchema,
    AuthorizationCodeFlow,
    ObjectSchema,
    Ref,
    ScalarSchema,
    is_file,
    read_document,
)
from appgen.dsl.validator import validate_definition
from appgen.gen import GenerationResult, find_binding, generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

BASE = """\
version: 0
app: { name: shop, title: Shop }
entities:
  Order:
    crud: true
    fields:
      number: { type: string }
"""

FILE = {"type": "string", "format": "binary"}

DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Files", "version": "1"},
    "servers": [{"url": "https://files.example.com"}],
    "paths": {
        "/upload": {
            "post": {
                "operationId": "upload",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file"],
                                "properties": {
                                    "file": FILE,
                                    "pages": {"type": "array", "items": FILE},
                                    "meta": {
                                        "type": "object",
                                        "properties": {"title": {"type": "string"}},
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {"204": {"description": "Uploaded."}},
            }
        },
        "/feedback": {
            "post": {
                "operationId": "feedback",
                "requestBody": {
                    "content": {
                        "application/x-www-form-urlencoded; charset=utf-8": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "message": {"type": "string"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                },
                            }
                        },
                        "text/plain": {},
                    }
                },
                "responses": {"204": {"description": "Sent."}},
            }
        },
        "/export": {
            "get": {
                "operationId": "export",
                "parameters": [
                    {"name": "session", "in": "cookie", "required": True, "schema": {}},
                    {"name": "debug", "in": "cookie", "schema": {"type": "boolean"}},
                ],
                "responses": {
                    "200": {
                        "description": "A CSV file.",
                        "content": {"text/csv": {"example": "a,b\n1,2\n"}},
                    }
                },
            }
        },
        "/report": {
            "get": {
                "operationId": "report",
                "responses": {
                    "200": {"description": "A PDF file.", "content": {"application/pdf": {}}}
                },
            }
        },
        "/note": {
            "get": {
                "operationId": "note",
                "responses": {
                    "200": {
                        "description": "A note in JSON or text.",
                        "content": {
                            "text/plain": {},
                            "application/problem+json": {"schema": {"type": "string"}},
                        },
                    }
                },
            }
        },
    },
    "components": {
        "securitySchemes": {
            "oauth": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": "https://files.example.com/authorize",
                        "tokenUrl": "https://files.example.com/token",
                        "scopes": {"files:write": "Write."},
                    },
                    "clientCredentials": {
                        "tokenUrl": "/oauth/token",
                        "scopes": {"files:read": "Read.", "files:write": "Write."},
                    },
                },
            },
            "login": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": "https://files.example.com/authorize",
                        "tokenUrl": "https://files.example.com/token",
                        "scopes": {},
                    }
                },
            },
        }
    },
}

FILES = """\
apis:
  files:
    document: files.json
    base_url_env: FILES_API_URL
    operations: [upload, feedback, export, report]
"""

OAUTH = """\
    security:
      scheme: oauth
      client_id_env: FILES_CLIENT_ID
      client_secret_env: FILES_CLIENT_SECRET
      scopes: [files:read]
"""


def write_document(folder: Path, data: object) -> Path:
    path = folder / "files.json"
    path.write_text(json.dumps(data))
    return path


def definition(folder: Path, apis: str, document: object = DOCUMENT) -> AppDefinition:
    write_document(folder, document)
    return load_definition_text(BASE + apis, str(folder / "app.yaml"))


def codes(found: AppDefinition) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in validate_definition(found)]


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def test_a_body_is_json_a_form_or_a_multipart_form_with_files(tmp_path: Path) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["upload", "feedback"])

    assert spec.problems == ()
    upload, feedback = spec.operations
    assert (upload.body_kind, upload.body, upload.body_required) == (
        "multipart",
        Ref("UploadBody"),
        True,
    )
    body = spec.schema("UploadBody").schema
    assert isinstance(body, ObjectSchema)
    by_name = {p.name: p.schema for p in body.properties}
    assert by_name["file"] == ScalarSchema("string", "binary")
    assert by_name["pages"] == ArraySchema(ScalarSchema("string", "binary"))
    assert [name for name, schema in by_name.items() if is_file(schema, spec)] == ["file", "pages"]
    # A media type with parameters is still a form.
    assert feedback.body_kind == "form"


def test_a_json_answer_comes_first_then_a_text_answer_then_a_binary_answer(
    tmp_path: Path,
) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["export", "report", "note"])

    export, report, note = spec.operations
    assert (export.answer, export.answer_media, export.result) == (
        "text",
        "text/csv",
        ScalarSchema("string"),
    )
    assert export.example == "a,b\n1,2\n"
    assert (report.answer, report.answer_media, report.result) == (
        "binary",
        "application/pdf",
        ScalarSchema("string", "binary"),
    )
    assert report.example == EXAMPLE_TEXT
    assert (note.answer, note.answer_media) == ("json", "application/problem+json")


def test_a_content_media_type_of_openapi_3_1_is_binary_data(tmp_path: Path) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["openapi"] = "3.1.0"
    properties = document["paths"]["/upload"]["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]["properties"]
    properties["file"] = {"type": "string", "contentMediaType": "image/png"}
    properties["text"] = {
        "type": "string",
        "contentMediaType": "image/png",
        "contentEncoding": "base64",
    }
    spec = read_document(write_document(tmp_path, document)).select(["upload"])

    body = spec.schema("UploadBody").schema
    assert isinstance(body, ObjectSchema)
    by_name = {p.name: p.schema for p in body.properties}
    assert by_name["file"] == ScalarSchema("string", "binary")
    assert by_name["text"] == ScalarSchema("string")


def test_a_cookie_parameter_is_a_text_a_number_or_a_boolean(tmp_path: Path) -> None:
    spec = read_document(write_document(tmp_path, DOCUMENT)).select(["export"])

    assert [(p.name, p.location, p.required) for p in spec.operations[0].parameters] == [
        ("session", "cookie", True),
        ("debug", "cookie", False),
    ]


@pytest.mark.parametrize(
    ("media", "schema", "problem"),
    [
        (
            "application/x-www-form-urlencoded",
            {"type": "array", "items": {"type": "string"}},
            "The form body is not an object with properties.",
        ),
        (
            "multipart/form-data",
            {"type": "object"},
            "The multipart form body is not an object with properties.",
        ),
        (
            "application/x-www-form-urlencoded",
            {"type": "object", "properties": {"file": FILE}},
            "The property 'file' of the form body is not a text, a number, a boolean, or a "
            "list of these. Send a file or an object in a multipart form.",
        ),
        (
            "application/x-www-form-urlencoded",
            {"type": "object", "properties": {"meta": {"type": "object", "properties": {}}}},
            "The property 'meta' of the form body is not a text, a number, a boolean, or a "
            "list of these. Send a file or an object in a multipart form.",
        ),
    ],
)
def test_a_form_body_is_an_object_and_a_simple_form_has_no_files(
    tmp_path: Path, media: str, schema: object, problem: str
) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["paths"]["/feedback"]["post"]["requestBody"]["content"] = {media: {"schema": schema}}
    spec = read_document(write_document(tmp_path, document)).select(["feedback"])

    assert spec.problems == (("feedback", problem),)
    assert spec.operations[0].body is None


def test_the_reader_gives_the_flows_of_an_oauth_scheme(tmp_path: Path) -> None:
    schemes = read_document(write_document(tmp_path, DOCUMENT)).security_schemes

    oauth, login = schemes["oauth"], schemes["login"]
    assert oauth.flows == ("authorizationCode", "clientCredentials")
    assert (oauth.token_url, oauth.scopes) == ("/oauth/token", ("files:read", "files:write"))
    assert oauth.supported
    assert login.token_url is None
    # The authorization code flow calls the API in the name of a user (ADR 0033).
    assert login.supported
    assert login.authorization_code == AuthorizationCodeFlow(
        authorization_url="https://files.example.com/authorize",
        token_url="https://files.example.com/token",
        refresh_url=None,
        scopes=(),
    )


def test_an_oauth_scheme_without_a_supported_flow_is_unsuitable(tmp_path: Path) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["components"]["securitySchemes"]["legacy"] = {
        "type": "oauth2",
        "flows": {"implicit": {"authorizationUrl": "https://files.example.com/a", "scopes": {}}},
    }
    security = OAUTH.replace("scheme: oauth", "scheme: legacy")

    [diagnostic] = validate_definition(definition(tmp_path, FILES + security, document))

    assert (diagnostic.code, diagnostic.element_id) == ("unsuitable-security", "apis.files")
    assert "Its flows are 'implicit'." in diagnostic.message


def test_the_operations_of_the_example_need_no_hand_written_code(tmp_path: Path) -> None:
    assert codes(definition(tmp_path, FILES)) == []
    assert codes(definition(tmp_path, FILES + OAUTH)) == []


@pytest.mark.parametrize(
    ("security", "code", "text"),
    [
        (
            "    security: { scheme: oauth, client_secret_env: FILES_CLIENT_SECRET }\n",
            "missing-key",
            "needs the key 'client_id_env'",
        ),
        (
            "    security: { scheme: oauth, env: FILES_TOKEN, client_id_env: FILES_CLIENT_ID,"
            " client_secret_env: FILES_CLIENT_SECRET }\n",
            "invalid-option",
            "The key 'env' does not suit the scheme 'oauth' (OAuth 2.0).",
        ),
        (
            OAUTH.replace("[files:read]", "[files:raed]"),
            "unknown-reference",
            "has no scope 'files:raed'",
        ),
        (
            OAUTH.replace("scheme: oauth", "scheme: login").replace("[files:read]", "[]"),
            "unsuitable-security",
            "needs the sign-in of the users ('auth')",
        ),
        (OAUTH.replace("FILES_CLIENT_ID", "FILES_API_URL"), "duplicate-name", "FILES_API_URL"),
        (
            OAUTH.replace("FILES_CLIENT_SECRET", "VITE_FILES_SECRET"),
            "reserved-name",
            "VITE_FILES_SECRET",
        ),
    ],
)
def test_the_security_of_oauth_needs_its_keys_and_the_scopes_of_the_flow(
    tmp_path: Path, security: str, code: str, text: str
) -> None:
    found = definition(tmp_path, FILES + security)

    [diagnostic] = validate_definition(found)
    assert (diagnostic.code, diagnostic.element_id) == (code, "apis.files")
    assert text in diagnostic.message


def test_a_public_client_id_is_not_a_secret(tmp_path: Path) -> None:
    found = definition(tmp_path, FILES + OAUTH.replace("FILES_CLIENT_ID", "VITE_FILES_CLIENT"))

    assert codes(found) == []


def test_an_api_key_does_not_take_the_keys_of_oauth(tmp_path: Path) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["components"]["securitySchemes"]["key"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Key",
    }
    security = "    security: { scheme: key, env: FILES_KEY, scopes: [files:read] }\n"
    found = definition(tmp_path, FILES + security, document)

    [diagnostic] = validate_definition(found)
    assert diagnostic.code == "invalid-option"
    assert diagnostic.message == (
        "The key 'scopes' does not suit the scheme 'key' (an API key or a bearer token)."
    )
    assert diagnostic.hint == "Use 'env'."


def test_an_exposed_operation_has_a_json_body_and_a_json_answer(tmp_path: Path) -> None:
    found = definition(tmp_path, FILES + "    expose: true\n")

    messages = [d.message for d in validate_definition(found)]
    assert messages == [
        "The FastAPI app cannot expose the operation 'upload': its body is a form. Its endpoint "
        "takes a JSON body.",
        "The FastAPI app cannot expose the operation 'feedback': its body is a form. Its "
        "endpoint takes a JSON body.",
        "The FastAPI app cannot expose the operation 'export': its answer is text/csv, not "
        "JSON. Its endpoint gives JSON.",
        "The FastAPI app cannot expose the operation 'report': its answer is application/pdf, "
        "not JSON. Its endpoint gives JSON.",
    ]


@pytest.fixture(scope="module")
def nextjs() -> dict[str, str]:
    return _files(generate(load_definition(EXAMPLE), find_binding("nextjs")))


@pytest.fixture(scope="module")
def fastapi() -> dict[str, str]:
    return _files(generate(load_definition(EXAMPLE), find_binding("fastapi")))


def test_the_typescript_client_sends_forms_and_cookies_and_reads_text_and_blobs(
    nextjs: dict[str, str],
) -> None:
    documents = nextjs["src/shared/api/documents/client.ts"]
    assert '"POST", "/attachments", {\n      form: body,\n      multipart: true,\n' in documents
    assert '"POST", "/feedback", {\n      form: body,\n    });' in documents
    assert '      answer: "text",\n      accept: "text/csv",\n' in documents
    assert "async downloadReport(params: DownloadReportParams): Promise<Blob> {" in documents
    assert '      answer: "binary",\n      accept: "application/pdf",\n' in documents
    assert "  file: Blob;\n" in nextjs["src/shared/api/documents/types.ts"]
    finance = nextjs["src/shared/api/finance/client.ts"]
    assert "      cookies: { tenant: params.tenant },\n" in finance
    third_party = nextjs["src/shared/api/third-party.ts"]
    assert 'headers.set("Cookie", ' in third_party
    assert "function multipartBody(" in third_party


def test_the_typescript_client_gets_a_token_with_the_client_credentials_flow(
    nextjs: dict[str, str],
) -> None:
    finance = nextjs["src/shared/api/finance/client.ts"]
    assert 'export const FINANCE_TOKEN_URL = "/oauth/token";' in finance
    assert (
        '        ? clientCredentials("finance", {\n'
        "            tokenUrl: tokenUrl(FINANCE_TOKEN_URL, baseUrl),\n"
        '            clientId: options.clientId ?? "",\n'
        "            clientSecret: options.secret,\n"
        '            scopes: ["budgets:read"],\n'
    ) in finance
    assert "    clientId: process.env.FINANCE_CLIENT_ID,\n" in finance
    assert "    secret: process.env.FINANCE_CLIENT_SECRET,\n" in finance
    third_party = nextjs["src/shared/api/third-party.ts"]
    assert "class ClientCredentials implements TokenSource {" in third_party
    assert 'grant_type: "client_credentials"' in third_party
    assert "FINANCE_CLIENT_ID=\n" in nextjs[".env.example"]
    assert "FINANCE_CLIENT_ID=\n" in nextjs["deploy/kubernetes/config.env"]
    assert "FINANCE_CLIENT_ID" not in nextjs["deploy/kubernetes/secret.example.env"]
    assert "`FINANCE_CLIENT_ID` (client ID), `FINANCE_CLIENT_SECRET`" in nextjs["README.md"]


def test_the_shared_client_has_only_the_code_that_the_apis_need(tmp_path: Path) -> None:
    assert ts_features(ts_apis(load_definition(EXAMPLE))) == {
        "binary",
        "cookie",
        "form",
        "multipart",
        "oauth2",
        "text",
    }
    found = definition(tmp_path, FILES.replace("[upload, feedback, export, report]", "[report]"))
    assert ts_features(ts_apis(found)) == {"binary"}
    third_party = _files(generate(found, find_binding("nextjs")))["src/shared/api/third-party.ts"]
    assert "ClientCredentials" not in third_party
    assert "multipartBody" not in third_party
    assert "Cookie" not in third_party


def test_the_python_client_sends_forms_and_cookies_and_reads_text_and_bytes(
    fastapi: dict[str, str],
) -> None:
    documents = fastapi["app/integrations/documents/client.py"]
    assert '"POST", "/attachments", form=body, multipart=True)' in documents
    assert 'await self.request("POST", "/feedback", form=body)' in documents
    assert "async def export_tasks(self, project: str) -> str:" in documents
    assert '        return await self.request_text(\n            "GET",\n' in documents
    assert '            accept="text/csv",\n' in documents
    assert "async def download_report(self, project: str) -> bytes:" in documents
    assert "    file: ApiFile\n" in fastapi["app/integrations/documents/models.py"]
    finance = fastapi["app/integrations/finance/client.py"]
    assert '            cookies={"tenant": tenant},\n' in finance
    http = fastapi["app/integrations/http.py"]
    assert "class ApiFile:" in http
    assert 'headers["Cookie"] = "; ".join(cookies)' in http


def test_the_python_client_gets_a_token_with_the_client_credentials_flow(
    fastapi: dict[str, str],
) -> None:
    finance = fastapi["app/integrations/finance/client.py"]
    assert 'TOKEN_URL = "/oauth/token"' in finance
    assert 'SCOPES = ["budgets:read"]' in finance
    assert (
        "client_credentials(self.api, base_url, TOKEN_URL, client_id, client_secret, SCOPES)"
    ) in finance
    assert "        settings.finance_client_id,\n        settings.finance_client_secret,\n" in (
        finance
    )
    config = fastapi["app/core/config.py"]
    assert '    finance_client_id: str = ""\n' in config
    http = fastapi["app/integrations/http.py"]
    assert "class ClientCredentials:" in http
    assert "def clear_tokens() -> None:" in http
    assert "FINANCE_CLIENT_ID=\n" in fastapi[".env.example"]
    tests = fastapi["tests/integrations/test_finance.py"]
    assert "def test_the_client_gets_one_token_for_the_requests_at_the_same_time" in tests
    assert "def test_an_answer_with_the_status_401_gets_a_new_token_one_time" in tests


def test_without_oauth_the_python_client_has_no_token_code(tmp_path: Path) -> None:
    found = definition(tmp_path, FILES)
    http = _files(generate(found, find_binding("fastapi")))["app/integrations/http.py"]
    assert "ClientCredentials" not in http
    assert "import asyncio" not in http


COOKIE = """\
apis:
  files:
    document: files.json
    base_url_env: FILES_API_URL
    operations: [export]
"""


def test_in_the_react_app_an_api_with_a_cookie_parameter_is_a_gap(tmp_path: Path) -> None:
    result = generate(definition(tmp_path, COOKIE), find_binding("react"))

    files = _files(result)
    assert "src/shared/api/files/client.ts" not in files
    gap = files["src/shared/api/files/client.ext.ts"]
    assert "// @trace:gap apis.files.operations.export file" in gap
    assert (
        " * The API `files` (Files) sends the cookie parameter `session` in the\n"
        " * operation `export`, and a browser cannot set a cookie for another site.\n"
    ) in gap
    [warning] = result.warnings
    assert warning.startswith(
        "The API 'files' sends the cookie parameter session in the operation export, and a "
        "browser cannot set a cookie for another site, so the React app has no client for it."
    )


def test_in_the_react_app_an_exposed_api_with_a_cookie_parameter_has_a_client(
    tmp_path: Path,
) -> None:
    result = generate(definition(tmp_path, COOKIE + "    expose: true\n"), find_binding("react"))

    files = _files(result)
    assert (
        "      cookies: { session: params.session, debug: params.debug },\n"
        in (files["src/shared/api/files/client.ts"])
    )
    assert result.warnings == []
