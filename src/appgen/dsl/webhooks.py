"""The webhooks of an app: the requests that other systems send to it (ADR 0028).

A webhook is an endpoint of the server apps. The apps check the
signature of each request with a secret, keep the ID of each event, and
call a gap function with the body one time for each event ID. The
loader reads the optional OpenAPI document of the body from the folder
of the definition, as for the `apis` (ADR 0019).
"""

from pathlib import Path
from typing import Annotated, Literal

import pydantic
from pydantic import BaseModel, ConfigDict, PrivateAttr, StringConstraints

from appgen.dsl.apis import EnvName
from appgen.dsl.element import Element, Text
from appgen.dsl.openapi import ClientSpec, DocumentError, OpenApiDocument, read_document

WEBHOOK_PATH_PATTERN = r"^(/[a-z0-9][a-z0-9._~-]*)+$"
HEADER_PATTERN = r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$"
STRIPE_HEADER = "Stripe-Signature"
"""The header of the signature of the `stripe` scheme."""

type WebhookPath = Annotated[str, StringConstraints(pattern=WEBHOOK_PATH_PATTERN)]
"""The path of a webhook: one or more fixed segments in lower case, for example
`/webhooks/payments`."""
type HeaderName = Annotated[str, StringConstraints(pattern=HEADER_PATTERN)]
"""The name of an HTTP header, for example `X-Signature`."""


class WebhookSignature(BaseModel):
    """How the app checks that a request comes from the sender: a signature with a secret."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scheme: Literal["hmac_sha256", "stripe"]
    """`hmac_sha256`: a header has the HMAC-SHA256 of the body. `stripe`: the header
    `Stripe-Signature` has a time and the HMAC-SHA256 of the time and the body."""
    secret_env: EnvName
    """The environment variable that holds the secret of the signatures."""
    header: HeaderName | None = None
    """`hmac_sha256`: the header with the signature, for example `X-Signature-256`."""
    prefix: str = ""
    """`hmac_sha256`: the text before the signature in the header, for example `sha256=`."""
    encoding: Literal["hex", "base64"] = "hex"
    """`hmac_sha256`: the encoding of the signature."""
    tolerance_seconds: Annotated[int, pydantic.Field(ge=1, le=86400)] = 300
    """`stripe`: the age of a signature, in seconds, after which the app refuses it."""

    @property
    def signature_header(self) -> str:
        """The header with the signature."""
        return STRIPE_HEADER if self.scheme == "stripe" else self.header or ""


class WebhookEventId(BaseModel):
    """Where the ID of the event is: a property of the JSON body, or a header."""

    model_config = ConfigDict(extra="forbid", strict=True)

    field: Text | None = None
    """The property of the body with the ID, for example `id`. A dot goes into an object, for
    example `data.id`."""
    header: HeaderName | None = None
    """The header with the ID, for example `X-Delivery-ID`."""

    @property
    def path(self) -> tuple[str, ...]:
        """The names of the properties of `field`, or none for a header."""
        return tuple(self.field.split(".")) if self.field else ()


class WebhookBody(BaseModel):
    """The schema of the body: a component schema of an OpenAPI document."""

    model_config = ConfigDict(extra="forbid", strict=True)

    document: Text
    """The path of the OpenAPI document (3.0 or 3.1, YAML or JSON), from the folder of the
    definition."""
    schema_name: Text = pydantic.Field(alias="schema")
    """The name of a schema in `components.schemas` of the document."""


class Webhook(Element):
    """An endpoint that another system sends events to, for example a payment service."""

    path: WebhookPath
    """The path of the endpoint, for example `/webhooks/payments`. The method is POST."""
    description: Text | None = None
    signature: WebhookSignature
    """The check of the signature of each request."""
    event_id: WebhookEventId = pydantic.Field(
        default_factory=lambda: WebhookEventId(field="id"),
        json_schema_extra={"default": {"field": "id"}},
    )
    """Where the ID of the event is. The default is the property `id` of the body."""
    body: WebhookBody | None = None
    """The schema of the body. Without it, the body is any JSON value."""

    _openapi: OpenApiDocument | None = PrivateAttr(default=None)
    _error: str | None = PrivateAttr(default=None)
    _spec: ClientSpec | None = PrivateAttr(default=None)

    @property
    def openapi(self) -> OpenApiDocument | None:
        """The document of the body, or None if it has none or the document is not valid."""
        return self._openapi

    @property
    def document_error(self) -> str | None:
        """Why the document cannot be read, or None."""
        return self._error

    @property
    def spec(self) -> ClientSpec:
        """The schema of the body and the schemas that it needs. Empty without a valid
        document, or if the document has no such schema."""
        if self._spec is None:
            found = (
                self._openapi.select_schemas([self.body.schema_name])
                if self._openapi is not None and self.body is not None
                else None
            )
            self._spec = found if found is not None else ClientSpec((), ())
        return self._spec

    @property
    def body_schema(self) -> str | None:
        """The name of the schema of the body in the normal form, or None for any JSON."""
        if self.body is None or self._openapi is None:
            return None
        return self._openapi.schema_name(self.body.schema_name)

    def read_document(self, base_dir: Path) -> None:
        """Read the document of the body from a folder. Keep the error of a document that is
        not valid, for the validator."""
        self._openapi, self._error, self._spec = None, None, None
        if self.body is None:
            return
        if "://" in self.body.document:
            self._error = "The document must be a local file, not a URL."
            return
        try:
            self._openapi = read_document(base_dir / self.body.document)
        except DocumentError as error:
            self._error = str(error)
