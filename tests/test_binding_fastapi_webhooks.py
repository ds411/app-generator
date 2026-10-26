"""The FastAPI binding writes an endpoint with a signature check for each webhook (ADR 0028)."""

import ast
import hashlib
from pathlib import Path

import pytest

from appgen.bindings.fastapi.webhooks import TEST_EVENT_ID, python_webhooks
from appgen.dsl import load_definition, load_definition_text
from appgen.gen import GenerationResult, find_binding, generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "webhooks.yaml"
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def result() -> GenerationResult:
    return generate(load_definition(FIXTURE), find_binding("fastapi"))


@pytest.fixture(scope="module")
def files(result: GenerationResult) -> dict[str, str]:
    return _files(result)


def test_each_webhook_gets_a_package_and_tests(files: dict[str, str]) -> None:
    for module in ("payments", "shipping", "chat"):
        for name in ("__init__.py", "router.py", "handler_ext.py"):
            assert f"app/webhooks/{module}/{name}" in files
        assert f"tests/webhooks/test_{module}.py" in files
    # Only a webhook with a schema of the body has models.
    assert "app/webhooks/payments/models.py" in files
    assert "app/webhooks/shipping/models.py" not in files
    assert "app/core/webhooks.py" in files
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, path)


def test_an_app_without_webhooks_has_no_webhook_files() -> None:
    text = (
        "version: 0\napp: { name: notes, title: Notes }\n"
        "entities:\n  Note:\n    fields:\n      title: { type: string }\n"
    )
    files = _files(generate(load_definition_text(text), find_binding("fastapi")))

    assert not [path for path in files if "webhook" in path]
    assert "WebhookEvent" not in files["app/models.py"]
    assert "webhook_events" not in files["migrations/versions/0001_schema.py"]


def test_the_logic_is_a_gap_with_the_typed_event(result: GenerationResult) -> None:
    by_path = {f.path: f for f in result.files}
    payments = by_path["app/webhooks/payments/handler_ext.py"]
    shipping = by_path["app/webhooks/shipping/handler_ext.py"]

    assert payments.kind == "extension"
    assert "# @trace:gap webhooks.payments file" in payments.content
    assert "TODO(appgen)" in payments.content
    assert "async def handle_payments(" in payments.content
    assert "event: Event," in payments.content
    assert 'raise NotImplementedError("webhooks.payments")' in payments.content
    assert "    event: JsonValue,\n" in shipping.content


def test_the_endpoint_checks_the_signature_of_its_scheme(files: dict[str, str]) -> None:
    payments = files["app/webhooks/payments/router.py"]
    shipping = files["app/webhooks/shipping/router.py"]
    chat = files["app/webhooks/chat/router.py"]

    assert '@router.post(\n    "/webhooks/payments",' in payments
    assert "# @trace webhooks.payments" in payments
    assert "body = await request.body()" in payments
    assert "check_stripe(" in payments
    assert "tolerance=600" in payments
    assert 'request.headers.get("Stripe-Signature")' in payments
    assert "check_hmac_sha256(" in shipping
    assert 'request.headers.get("X-Shipping-Hmac")' in shipping
    assert 'encoding="base64"' in shipping
    assert 'event_id = event_id_in_header(request.headers.get("X-Shipping-Event"))' in shipping
    assert 'prefix="sha256="' in chat
    assert 'event_id = event_id_in_body(data, ("message", "id"))' in chat
    for router in (payments, shipping, chat):
        # The signature comes before the JSON, and the event ID before the logic.
        assert router.index("check_") < router.index("read_json(") < router.index("record_event(")
        assert router.index("record_event(") < router.index("await handle_")


def test_the_app_has_the_table_of_the_events_and_the_secrets(files: dict[str, str]) -> None:
    core = files["app/core/webhooks.py"]
    assert '__tablename__ = "webhook_events"' in core
    assert "hmac.compare_digest(" in core
    assert "def check_stripe(" in core
    assert "def check_hmac_sha256(" in core
    assert "import base64" in core
    assert "WebhookEvent" in files["app/models.py"]
    migration = files["migrations/versions/0001_schema.py"]
    assert '"webhook_events",' in migration
    assert 'sa.UniqueConstraint("webhook", "event_id"' in migration
    assert 'op.drop_table("webhook_events")' in migration
    config = files["app/core/config.py"]
    for setting in ("payments", "shipping", "chat"):
        assert f'    {setting}_webhook_secret: str = ""\n' in config
        assert f"{setting.upper()}_WEBHOOK_SECRET=" in files[".env.example"]


def test_the_app_includes_the_webhooks_before_the_hand_written_routers(
    files: dict[str, str],
) -> None:
    main = files["app/main.py"]

    assert "from app.webhooks.payments.router import router as payments_webhook" in main
    assert main.index("app.include_router(chat_webhook)") < main.index("for router in ROUTERS:")
    assert main.index("app.include_router(orders_router)") < main.index(
        "app.include_router(chat_webhook)"
    )


def test_a_scheme_without_base64_has_no_base64_code() -> None:
    text = FIXTURE.read_text().replace("encoding: base64", "encoding: hex")
    files = _files(generate(load_definition_text(text, str(FIXTURE)), find_binding("fastapi")))

    assert "base64" not in files["app/core/webhooks.py"]


def test_the_tests_get_a_valid_sample_with_the_event_id() -> None:
    webhooks = python_webhooks(load_definition(FIXTURE))

    payments = webhooks["payments"]
    assert payments.sample["id"] == TEST_EVENT_ID
    assert set(payments.sample) >= {"id", "type", "created", "data"}
    assert payments.sample_event_id == TEST_EVENT_ID
    assert webhooks["chat"].sample == {"message": {"id": TEST_EVENT_ID}}
    assert webhooks["shipping"].sample == {}
    assert webhooks["shipping"].sample_event_id == TEST_EVENT_ID


def test_an_integer_event_id_gets_an_integer_sample(tmp_path: Path) -> None:
    document = (FIXTURE.parent / "webhooks" / "payments.openapi.yaml").read_text()
    folder = tmp_path / "webhooks"
    folder.mkdir()
    (folder / "payments.openapi.yaml").write_text(document)
    text = FIXTURE.read_text().replace(
        "schema: Event }", "schema: Event }\n    event_id: { field: created }"
    )

    webhooks = python_webhooks(load_definition_text(text, str(tmp_path / "app.yaml")))

    assert webhooks["payments"].sample["created"] == 1
    assert webhooks["payments"].sample_event_id == "1"


def test_the_manifest_has_the_hash_of_the_document(result: GenerationResult) -> None:
    document = FIXTURE.parent / "webhooks" / "payments.openapi.yaml"
    digest = hashlib.sha256(document.read_bytes()).hexdigest()

    assert result.documents["webhooks/payments.openapi.yaml"] == f"sha256:{digest}"


def test_the_front_ends_leave_out_the_webhooks() -> None:
    definition = load_definition(EXAMPLE)

    react = generate(definition, find_binding("react"))
    nextjs = generate(definition, find_binding("nextjs"))

    assert "webhook" in react.excluded_kinds
    assert "webhooks.commits" not in {gap.element_id for gap in react.gaps}
    gaps = {gap.element_id: gap for gap in nextjs.gaps}
    assert gaps["webhooks.commits"].path == "src/gaps/webhooks.commits.ext.ts"
