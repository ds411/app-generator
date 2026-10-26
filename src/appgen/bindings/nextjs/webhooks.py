"""The webhooks of the Next.js app (ADR 0028).

For each webhook of the definition, the binding writes a route handler
`app/<path>/route.ts` and a feature slice `src/features/<webhook>-webhook/`:
the function that receives a request (`api/<webhook>-webhook.gen.ts`), the
extension file with the logic (`api/<webhook>-webhook.ext.ts`), and, with
a schema of the body, the TypeScript types and the zod schemas of the
event (`model/event.ts`). `src/shared/webhooks/` checks the signatures and
keeps the event IDs. This module gives the values of these files.
"""

import json
from dataclasses import dataclass, field

from appgen.bindings.shared.integrations import TsType, ts_key, ts_types
from appgen.dsl.model import AppDefinition
from appgen.dsl.openapi import (
    ArraySchema,
    MapSchema,
    NamedSchema,
    ObjectSchema,
    Ref,
    ScalarSchema,
    Schema,
    UnionSchema,
)
from appgen.dsl.webhooks import Webhook
from appgen.gen.naming import kebab, pascal

_STRING_FORMATS = {"uuid": "z.uuid()", "email": "z.email()", "binary": "z.instanceof(Blob)"}
_SCALARS = {"integer": "z.int()", "number": "z.number()", "boolean": "z.boolean()"}


@dataclass(frozen=True, slots=True)
class ZodConst:
    """A named schema, as a constant with its zod schema."""

    name: str
    """The name of the constant, for example `CommitEventSchema`."""
    expression: str
    """The zod schema of a type alias, or `z.object` for an interface."""
    keys: tuple[str, ...] | None = None
    """The keys of `z.object` with their zod schemas, or None for a type alias."""


@dataclass(slots=True)
class TsWebhook:
    """A webhook, as a route handler and a feature slice of the app."""

    name: str
    id: str
    slice: str
    """The feature slice, for example `commits-webhook`."""
    path: str
    description: str | None
    scheme: str
    """`hmac_sha256` or `stripe`."""
    header: str
    """The header with the signature."""
    prefix: str
    encoding: str
    tolerance: int
    secret_env: str
    event_field: tuple[str, ...]
    """The properties of the body with the event ID, or empty for a header."""
    event_header: str | None
    body_type: str
    """The TypeScript type of the event: the type of the schema of the body, or `unknown`."""
    types: list[TsType] = field(default_factory=list[TsType])
    schemas: list[ZodConst] = field(default_factory=list[ZodConst])

    @property
    def route_file(self) -> str:
        """The route handler, for example `app/webhooks/commits/route.ts`."""
        return f"app/{self.path.strip('/')}/route.ts"

    @property
    def handler(self) -> str:
        """The function of the extension file, for example `handleCommits`."""
        return "handle" + pascal(self.name)

    @property
    def receive(self) -> str:
        """The function that receives a request, for example `receiveCommitsWebhook`."""
        return f"receive{pascal(self.name)}Webhook"

    @property
    def typed(self) -> bool:
        """True if the body has a schema, so the event has the type of the schema."""
        return bool(self.types)

    def check_call(self) -> str:
        """Return the call that checks the signature of the body."""
        header = f"headers.get({json.dumps(self.header)})"
        if self.scheme == "stripe":
            return f"checkStripe(secret, body, {header}, {{ tolerance: {self.tolerance} }})"
        options = f"{{ prefix: {json.dumps(self.prefix)}, encoding: {json.dumps(self.encoding)} }}"
        return f"checkHmacSha256(secret, body, {header}, {options})"

    def event_id_call(self) -> str:
        """Return the call that reads the event ID of the body or of a header."""
        if self.event_header:
            return f"eventIdInHeader(headers.get({json.dumps(self.event_header)}))"
        return f"eventIdInBody(data, {json.dumps(list(self.event_field))})"


def ts_webhooks(definition: AppDefinition) -> dict[str, TsWebhook]:
    """Return the model of each webhook of a definition, by name."""
    return {name: _webhook(name, webhook) for name, webhook in definition.webhooks.items()}


def _webhook(name: str, webhook: Webhook) -> TsWebhook:
    signature = webhook.signature
    ts = TsWebhook(
        name=name,
        id=webhook.id,
        slice=f"{kebab(name)}-webhook",
        path=webhook.path,
        description=webhook.description,
        scheme=signature.scheme,
        header=signature.signature_header,
        prefix=signature.prefix,
        encoding=signature.encoding,
        tolerance=signature.tolerance_seconds,
        secret_env=signature.secret_env,
        event_field=webhook.event_id.path,
        event_header=webhook.event_id.header,
        body_type="unknown",
    )
    schema_name = webhook.body_schema
    schemas = webhook.spec.schemas
    if schema_name is not None and schemas:
        ts.body_type = schema_name
        ts.types = ts_types(schemas)
        ts.schemas = sorted((_const(s) for s in schemas), key=lambda c: c.name)
    return ts


def _const(named: NamedSchema) -> ZodConst:
    schema = named.schema
    if isinstance(schema, ObjectSchema):
        keys = tuple(
            f"{ts_key(p.name)}: {zod(p.schema)}{'' if p.required else '.optional()'}"
            for p in schema.properties
        )
        return ZodConst(named.name + "Schema", "z.object", keys)
    return ZodConst(named.name + "Schema", zod(schema))


def zod(schema: Schema) -> str:
    """Return the zod schema of a schema of the normal form, with the type of `ts_type`."""
    match schema:
        case Ref(name):
            # A reference can go to a schema later in the module, or to the schema itself.
            return f"z.lazy(() => {name}Schema)"
        case ScalarSchema(_, _, enum) if enum:
            return f"z.literal({json.dumps(list(enum), ensure_ascii=False)})"
        case ScalarSchema("string", text_format):
            return _STRING_FORMATS.get(text_format or "", "z.string()")
        case ScalarSchema(kind):
            return _SCALARS.get(kind, "z.null()")
        case ArraySchema(items):
            return f"z.array({zod(items)})"
        case MapSchema(values):
            return f"z.record(z.string(), {zod(values)})"
        case UnionSchema(options):
            return "z.union([" + ", ".join(zod(option) for option in options) + "])"
        case _:
            return "z.unknown()"
