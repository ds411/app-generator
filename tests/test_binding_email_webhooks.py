"""The FastAPI and the Next.js apps read the inbound emails of each mail service (ADR 0030)."""

import ast
from pathlib import Path

import pytest

from appgen.dsl import load_definition, load_definition_text
from appgen.gen import GenerationResult, find_binding, generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "inbound-email.yaml"
WEBHOOKS = FIXTURE.parent / "webhooks.yaml"


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def fastapi() -> GenerationResult:
    return generate(load_definition(FIXTURE), find_binding("fastapi"))


@pytest.fixture(scope="module")
def nextjs() -> GenerationResult:
    return generate(load_definition(FIXTURE), find_binding("nextjs"))


def test_the_fastapi_app_has_a_reader_for_each_mail_service(fastapi: GenerationResult) -> None:
    files = _files(fastapi)
    module = files["app/core/inbound_email.py"]

    for provider in ("mailgun", "postmark", "sendgrid"):
        assert f"def read_{provider}(" in module
    assert "class InboundEmail(BaseModel):" in module
    assert "def email_event_id(" in module
    core = files["app/core/webhooks.py"]
    assert "def check_mailgun(" in core
    assert "def check_basic(" in core
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, path)


def test_a_json_app_has_no_email_code() -> None:
    files = _files(generate(load_definition(WEBHOOKS), find_binding("fastapi")))

    assert "app/core/inbound_email.py" not in files
    assert "def check_basic(" not in files["app/core/webhooks.py"]
    next_files = _files(generate(load_definition(WEBHOOKS), find_binding("nextjs")))
    assert "src/shared/webhooks/email.ts" not in next_files
    assert "receiveEmail" not in next_files["src/shared/webhooks/index.ts"]


def test_the_fastapi_endpoint_checks_the_signature_before_the_email(
    fastapi: GenerationResult,
) -> None:
    files = _files(fastapi)
    mailgun = files["app/webhooks/mailgun/router.py"]
    postmark = files["app/webhooks/postmark/router.py"]
    sendgrid = files["app/webhooks/sendgrid/router.py"]

    assert mailgun.index("form = await read_form(request)") < mailgun.index(
        "check_mailgun(secret, form, tolerance=600)"
    )
    assert mailgun.index("check_mailgun(") < mailgun.index("event = read_mailgun(form)")
    assert 'check_basic(secret, request.headers.get("Authorization"))' in postmark
    assert postmark.index("check_basic(") < postmark.index("event = read_postmark(read_json(body))")
    assert sendgrid.index("check_basic(") < sendgrid.index("event = read_sendgrid(form)")
    for router in (mailgun, postmark, sendgrid):
        assert "event_id = email_event_id(event, body)" in router
        assert router.index("email_event_id(") < router.index("record_event(")


def test_the_fastapi_logic_is_a_gap_with_the_email(fastapi: GenerationResult) -> None:
    by_path = {f.path: f for f in fastapi.files}
    handler = by_path["app/webhooks/postmark/handler_ext.py"]

    assert handler.kind == "extension"
    assert "# @trace:gap webhooks.postmark file" in handler.content
    assert "from app.core.inbound_email import InboundEmail" in handler.content
    assert "    event: InboundEmail,\n" in handler.content
    assert "app/webhooks/postmark/models.py" not in by_path
    tests = by_path["tests/webhooks/test_mailgun.py"].content
    assert "def signed(secret: str = SECRET, at: int | None = None)" in tests
    assert "test_an_email_without_a_message_id_gets_the_hash_of_the_body" in tests


def test_the_nextjs_slice_receives_the_email(nextjs: GenerationResult) -> None:
    files = _files(nextjs)
    gen = files["src/features/mailgun-webhook/api/mailgun-webhook.gen.ts"]
    ext = files["src/features/postmark-webhook/api/postmark-webhook.ext.ts"]

    assert "return receiveEmail(request, {" in gen
    assert '    provider: "mailgun",\n    scheme: "mailgun",\n    tolerance: 600,\n' in gen
    assert 'import { type InboundEmail, WebhookError } from "@/shared/webhooks";' in ext
    assert "handlePostmark(_event: InboundEmail, _headers: Headers)" in ext
    assert "src/features/postmark-webhook/model/event.ts" not in files
    email = files["src/shared/webhooks/email.ts"]
    for reader in ("readMailgun", "readPostmark", "readSendgrid"):
        assert f"function {reader}(" in email
    assert 'provider: "mailgun" | "postmark" | "sendgrid";' in email
    index = files["src/shared/webhooks/index.ts"]
    assert "  receiveEmail,\n" in index
    assert "checkBasic" in index


def test_the_nextjs_app_reads_only_the_mail_services_of_its_webhooks() -> None:
    text = FIXTURE.read_text()
    postmark = text[: text.index("  mailgun:\n")]
    files = _files(generate(load_definition_text(postmark, str(FIXTURE)), find_binding("nextjs")))

    email = files["src/shared/webhooks/email.ts"]
    assert "function readPostmark(" in email
    assert "readMailgun" not in email
    assert "readForm" not in email
    assert 'provider: "postmark";' in email


def test_the_readmes_and_the_env_files_describe_the_secrets(
    fastapi: GenerationResult, nextjs: GenerationResult
) -> None:
    for result in (fastapi, nextjs):
        files = _files(result)
        readme = files["README.md"]
        assert "| `postmark` | `POST /webhooks/postmark` | HTTP Basic (`Authorization`) |" in readme
        assert "Mailgun (the fields `timestamp`, `token`, and `signature`)" in readme
        env = files[".env.example"]
        assert "# The signing key of Mailgun for the webhook mailgun" in env
        assert "as <user name>:<password>." in env
