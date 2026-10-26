"""The `webhooks` section: the model, the loader, and the checks of the validator (ADR 0028)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.dsl import (
    DefinitionError,
    Diagnostic,
    load_definition,
    load_definition_text,
    validate_definition,
)
from appgen.dsl.schema import json_schema

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "webhooks.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: shop, title: Shop }
    entities:
      Order:
        fields:
          reference: { type: string }
    operations:
      list_orders: { kind: list, entity: Order }
    pages:
      order: { path: "/orders/{id}", title: Order, entity: Order }
    apis:
      pets:
        document: pets.yaml
        base_url_env: PETS_API_URL
        operations: [getPet]
    webhooks:
    """
)

PETS = dedent(
    """\
    openapi: 3.1.0
    info: { title: Pets, version: "1" }
    paths:
      /pets/{id}:
        get:
          operationId: getPet
          parameters: [{ name: id, in: path, required: true, schema: { type: string } }]
          responses: { "200": { description: A pet. } }
    """
)

EVENTS = dedent(
    """\
    openapi: 3.1.0
    info: { title: Events, version: "1" }
    components:
      schemas:
        Event:
          type: object
          required: [id]
          properties:
            id: { type: string }
            data:
              type: object
              properties:
                order: { type: string }
    """
)

PAYMENTS = """\
  payments:
    path: /webhooks/payments
    signature: { scheme: stripe, secret_env: PAYMENTS_SECRET }
"""


def load(tmp_path: Path, webhooks: str) -> list[Diagnostic]:
    """Return the diagnostics of the base definition with these webhooks."""
    (tmp_path / "pets.yaml").write_text(PETS)
    (tmp_path / "events.yaml").write_text(EVENTS)
    try:
        definition = load_definition_text(BASE + webhooks, str(tmp_path / "app.yaml"))
    except DefinitionError as error:
        return error.diagnostics
    return validate_definition(definition)


def codes(tmp_path: Path, webhooks: str) -> list[tuple[str, str | None]]:
    return [(d.code, d.element_id) for d in load(tmp_path, webhooks)]


def test_the_fixture_is_valid_and_has_the_defaults() -> None:
    definition = load_definition(FIXTURE)

    assert validate_definition(definition) == []
    payments = definition.webhooks["payments"]
    assert payments.id == "webhooks.payments"
    assert payments.signature.signature_header == "Stripe-Signature"
    assert payments.signature.tolerance_seconds == 600
    assert payments.event_id.path == ("id",)
    assert payments.body_schema == "Event"
    assert {s.name for s in payments.spec.schemas} == {"Event", "EventData", "Payment"}
    shipping = definition.webhooks["shipping"]
    assert shipping.signature.signature_header == "X-Shipping-Hmac"
    assert shipping.signature.encoding == "base64"
    assert shipping.event_id.header == "X-Shipping-Event"
    assert shipping.body is None
    assert definition.webhooks["chat"].event_id.path == ("message", "id")


def test_the_json_schema_has_the_section() -> None:
    schema = json_schema()

    assert "webhooks" in schema["properties"]
    assert "webhooks" not in schema.get("required", [])


def test_a_valid_webhook_gives_no_diagnostic(tmp_path: Path) -> None:
    webhook = PAYMENTS + "    body: { document: events.yaml, schema: Event }\n"

    assert load(tmp_path, webhook) == []


def test_the_secret_variable_is_required(tmp_path: Path) -> None:
    webhook = """\
  payments:
    path: /webhooks/payments
    signature: { scheme: stripe }
"""
    assert codes(tmp_path, webhook) == [("missing-key", "webhooks.payments.signature")]


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/orders/1", "duplicate-path"),
        ("/orders", "duplicate-path"),
        ("/orders/1/paid", "duplicate-path"),
        ("/auth/hooks", "reserved-name"),
        ("/apis/pets", "reserved-name"),
        ("/docs", "reserved-name"),
        ("/health", "reserved-name"),
    ],
)
def test_the_path_cannot_be_a_path_of_a_page_an_entity_or_the_apps(
    tmp_path: Path, path: str, code: str
) -> None:
    webhook = PAYMENTS.replace("/webhooks/payments", path)

    assert codes(tmp_path, webhook) == [(code, "webhooks.payments")]


def test_the_path_is_unique(tmp_path: Path) -> None:
    other = PAYMENTS.replace("payments:", "refunds:").replace("PAYMENTS_", "REFUNDS_")

    assert codes(tmp_path, PAYMENTS + other) == [("duplicate-path", "webhooks.refunds")]


def test_the_path_has_lowercase_segments(tmp_path: Path) -> None:
    webhook = PAYMENTS.replace("/webhooks/payments", "/Webhooks/payments")

    assert codes(tmp_path, webhook) == [("invalid-value", "webhooks.payments")]


@pytest.mark.parametrize(
    "env", ["DATABASE_URL", "NEXT_PUBLIC_PAYMENTS_SECRET", "VITE_PAYMENTS_SECRET"]
)
def test_the_secret_variable_is_not_reserved_or_public(tmp_path: Path, env: str) -> None:
    webhook = PAYMENTS.replace("PAYMENTS_SECRET", env)

    assert codes(tmp_path, webhook) == [("reserved-name", "webhooks.payments")]


def test_the_secret_variable_is_not_a_variable_of_an_api_or_another_webhook(
    tmp_path: Path,
) -> None:
    api = PAYMENTS.replace("PAYMENTS_SECRET", "PETS_API_URL")
    other = PAYMENTS.replace("payments", "refunds")

    assert codes(tmp_path, api) == [("duplicate-name", "webhooks.payments")]
    assert codes(tmp_path, PAYMENTS + other) == [("duplicate-name", "webhooks.refunds")]


def test_the_scheme_hmac_needs_a_header_and_takes_no_tolerance(tmp_path: Path) -> None:
    webhook = """\
  chat:
    path: /webhooks/chat
    signature: { scheme: hmac_sha256, secret_env: CHAT_SECRET, tolerance_seconds: 60 }
"""
    found = load(tmp_path, webhook)

    assert [(d.code, d.element_id) for d in found] == [
        ("missing-key", "webhooks.chat"),
        ("invalid-option", "webhooks.chat"),
    ]
    assert "'header'" in found[0].message
    assert "'tolerance_seconds'" in found[1].message


def test_the_scheme_stripe_has_a_fixed_header(tmp_path: Path) -> None:
    webhook = PAYMENTS.replace(
        "secret_env: PAYMENTS_SECRET", "secret_env: PAYMENTS_SECRET, header: X-Sig, prefix: v1="
    )

    assert codes(tmp_path, webhook) == [
        ("invalid-option", "webhooks.payments"),
        ("invalid-option", "webhooks.payments"),
    ]


def test_the_event_id_has_one_location(tmp_path: Path) -> None:
    both = PAYMENTS + "    event_id: { field: id, header: X-Event }\n"
    none = PAYMENTS + "    event_id: {}\n"

    assert codes(tmp_path, both) == [("invalid-option", "webhooks.payments")]
    assert codes(tmp_path, none) == [("missing-key", "webhooks.payments")]


def test_the_schema_and_the_event_id_are_in_the_document(tmp_path: Path) -> None:
    unknown = PAYMENTS + "    body: { document: events.yaml, schema: Events }\n"
    field = PAYMENTS + (
        "    body: { document: events.yaml, schema: Event }\n    event_id: { field: data.number }\n"
    )
    nested = PAYMENTS + (
        "    body: { document: events.yaml, schema: Event }\n    event_id: { field: data.order }\n"
    )

    found = load(tmp_path, unknown)
    assert [(d.code, d.element_id) for d in found] == [("unknown-reference", "webhooks.payments")]
    assert "Event" in (found[0].hint or "")
    assert codes(tmp_path, field) == [("unknown-reference", "webhooks.payments")]
    assert load(tmp_path, nested) == []


def test_the_document_is_a_valid_local_file(tmp_path: Path) -> None:
    missing = PAYMENTS + "    body: { document: missing.yaml, schema: Event }\n"
    remote = PAYMENTS + "    body: { document: https://example.com/events.yaml, schema: Event }\n"

    assert codes(tmp_path, missing) == [("invalid-document", "webhooks.payments")]
    assert codes(tmp_path, remote) == [("invalid-document", "webhooks.payments")]
