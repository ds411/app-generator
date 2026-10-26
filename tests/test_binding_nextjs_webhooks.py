"""The Next.js binding writes a route handler with a signature check for each webhook (ADR 0028)."""

from pathlib import Path

import pytest

from appgen.bindings.nextjs.webhooks import ts_webhooks, zod
from appgen.dsl import load_definition, load_definition_text
from appgen.dsl.openapi import ArraySchema, MapSchema, Ref, ScalarSchema, UnionSchema
from appgen.gen import GenerationResult, find_binding, generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "webhooks.yaml"
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def result() -> GenerationResult:
    return generate(load_definition(FIXTURE), find_binding("nextjs"))


@pytest.fixture(scope="module")
def files(result: GenerationResult) -> dict[str, str]:
    return _files(result)


def test_each_webhook_gets_a_route_handler_and_a_feature_slice(files: dict[str, str]) -> None:
    routes = {
        "payments": "app/webhooks/payments/route.ts",
        "shipping": "app/webhooks/shipping/events/route.ts",
        "chat": "app/webhooks/chat/route.ts",
    }
    for name, route in routes.items():
        assert "export async function POST(request: Request)" in files[route]
        slice_ = f"src/features/{name}-webhook"
        for path in ("index.ts", f"api/{name}-webhook.gen.ts", f"api/{name}-webhook.ext.ts"):
            assert f"{slice_}/{path}" in files
    # Only a webhook with a schema of the body has the types of the event.
    assert "src/features/payments-webhook/model/event.ts" in files
    assert "src/features/shipping-webhook/model/event.ts" not in files
    for module in ("index", "receive", "signature"):
        assert f"src/shared/webhooks/{module}.ts" in files
    route = files["app/webhooks/payments/route.ts"]
    assert 'import { receivePaymentsWebhook } from "@/features/payments-webhook";' in route
    assert "return receivePaymentsWebhook(request);" in route


def test_an_app_without_webhooks_has_no_webhook_files() -> None:
    text = (
        "version: 0\napp: { name: notes, title: Notes }\n"
        "entities:\n  Note:\n    fields:\n      title: { type: string }\n"
    )
    files = _files(generate(load_definition_text(text), find_binding("nextjs")))

    assert not [path for path in files if "webhook" in path]
    assert "webhook-events" not in files["src/shared/db/schema/index.ts"]


def test_the_logic_is_a_gap_with_the_typed_event(result: GenerationResult) -> None:
    by_path = {f.path: f for f in result.files}
    payments = by_path["src/features/payments-webhook/api/payments-webhook.ext.ts"]
    chat = by_path["src/features/chat-webhook/api/chat-webhook.ext.ts"]

    assert payments.kind == "extension"
    assert "// @trace:gap webhooks.payments file" in payments.content
    assert "TODO(appgen)" in payments.content
    assert 'import type { Event } from "../model/event";' in payments.content
    assert (
        "export async function handlePayments(_event: Event, _headers: Headers): Promise<void>"
        in payments.content
    )
    assert 'throw new WebhookError(501, "Not implemented yet: webhooks.payments");' in (
        payments.content
    )
    assert "handleChat(_event: unknown, _headers: Headers)" in chat.content
    assert "../model/event" not in chat.content
    # The binding covers the webhooks: no gap file of the kind.
    assert result.gaps == []


def test_the_endpoint_checks_the_signature_of_its_scheme(files: dict[str, str]) -> None:
    api = "src/features/{0}-webhook/api/{0}-webhook.gen.ts"
    payments = files[api.format("payments")]
    shipping = files[api.format("shipping")]
    chat = files[api.format("chat")]

    assert "// @trace webhooks.payments file" in payments
    assert "secret: process.env.PAYMENTS_WEBHOOK_SECRET," in payments
    assert (
        'checkStripe(secret, body, headers.get("Stripe-Signature"), { tolerance: 600 })' in payments
    )
    assert 'eventId: (data, _headers) => eventIdInBody(data, ["id"]),' in payments
    assert "schema: EventSchema as z.ZodType<Event>," in payments
    assert "handle: handlePayments," in payments
    assert (
        'checkHmacSha256(secret, body, headers.get("X-Shipping-Hmac"), '
        '{ prefix: "", encoding: "base64" })' in shipping
    )
    assert 'eventIdInHeader(headers.get("X-Shipping-Event"))' in shipping
    assert "schema:" not in shipping
    assert '{ prefix: "sha256=", encoding: "hex" }' in chat
    assert 'eventIdInBody(data, ["message", "id"])' in chat


def test_the_event_has_the_types_and_the_zod_schemas_of_the_document(
    files: dict[str, str],
) -> None:
    event = files["src/features/payments-webhook/model/event.ts"]

    assert "export interface Event {" in event
    assert '  type: "checkout.session.completed" | "invoice.paid";' in event
    assert "  customer_email?: string | null;" in event
    assert "export const EventSchema: z.ZodType = z.object({" in event
    assert '  type: z.literal(["checkout.session.completed", "invoice.paid"]),' in event
    assert "  created: z.int()," in event
    assert "  data: z.lazy(() => EventDataSchema)," in event
    assert "  customer_email: z.union([z.email(), z.null()]).optional()," in event
    index = files["src/features/payments-webhook/index.ts"]
    assert 'export type { Event } from "./model/event";' in index


def test_zod_gives_the_schema_of_each_form() -> None:
    assert zod(Ref("Payment")) == "z.lazy(() => PaymentSchema)"
    assert zod(ScalarSchema("string", "uuid")) == "z.uuid()"
    assert zod(ScalarSchema("string", "date-time")) == "z.string()"
    assert zod(ScalarSchema("number")) == "z.number()"
    assert zod(ScalarSchema("boolean")) == "z.boolean()"
    assert zod(ScalarSchema("null")) == "z.null()"
    assert zod(ArraySchema(ScalarSchema("integer"))) == "z.array(z.int())"
    assert zod(MapSchema(ScalarSchema("string"))) == "z.record(z.string(), z.string())"
    union = UnionSchema((ScalarSchema("string"), ScalarSchema("integer")))
    assert zod(union) == "z.union([z.string(), z.int()])"


def test_the_app_has_the_table_of_the_events_and_the_secrets(files: dict[str, str]) -> None:
    table = files["src/shared/db/schema/webhook-events.ts"]
    assert 'export const webhookEventsTable = pgTable(\n  "webhook_events",' in table
    assert 'unique("uq_webhook_events_webhook_event_id").on(t.webhook, t.eventId)' in table
    assert 'export * from "./webhook-events";' in files["src/shared/db/schema/index.ts"]
    receive = files["src/shared/webhooks/receive.ts"]
    assert "onConflictDoNothing()" in receive
    signature = files["src/shared/webhooks/signature.ts"]
    assert "timingSafeEqual(" in signature
    for env in ("PAYMENTS", "SHIPPING", "CHAT"):
        assert f"{env}_WEBHOOK_SECRET=" in files[".env.example"]
        assert f"{env}_WEBHOOK_SECRET=" in files["deploy/kubernetes/secret.example.env"]


def test_the_knative_service_reads_the_secrets_of_the_webhooks() -> None:
    text = FIXTURE.read_text().replace(
        "  title: Webhooks\n", "  title: Webhooks\n  x-nextjs-deploy: knative\n"
    )
    files = _files(generate(load_definition_text(text, str(FIXTURE)), find_binding("nextjs")))

    service = files["deploy/knative/service.yaml"]
    assert "- name: PAYMENTS_WEBHOOK_SECRET\n" in service
    assert "name: webhooks-web-payments-webhook-secret\n" in service


def test_the_model_reads_the_event_id_and_the_route() -> None:
    webhooks = ts_webhooks(load_definition(FIXTURE))

    shipping = webhooks["shipping"]
    assert shipping.route_file == "app/webhooks/shipping/events/route.ts"
    assert shipping.slice == "shipping-webhook"
    assert shipping.event_header == "X-Shipping-Event"
    assert shipping.body_type == "unknown"
    assert not shipping.typed
    assert webhooks["chat"].event_field == ("message", "id")
    assert webhooks["payments"].body_type == "Event"


def test_the_example_receives_the_commits_in_its_extension_file() -> None:
    result = generate(load_definition(EXAMPLE), find_binding("nextjs"))
    files = _files(result)

    route = files["app/webhooks/commits/route.ts"]
    assert "receiveCommitsWebhook(request)" in route
    ext = ROOT / "examples" / "project-tracker" / "extensions" / "nextjs"
    logic = ext / "src" / "features" / "commits-webhook" / "api" / "commits-webhook.ext.ts"
    content = logic.read_text()
    assert "// @trace:manual webhooks.commits" in content
    assert "export async function handleCommits(" in content
