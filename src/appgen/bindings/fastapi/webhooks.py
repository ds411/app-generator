"""The webhooks of the FastAPI app (ADR 0028).

For each webhook of the definition, the binding writes a package
`app/webhooks/<webhook>/` with the endpoint (`router.py`), the Pydantic
models of the schema of the body (`models.py`), and the extension file
with the logic (`handler_ext.py`). This module gives the values of these
files: the names, the check of the signature, and a valid sample body
for the generated tests.
"""

from dataclasses import dataclass, field
from typing import cast

from appgen.bindings.fastapi.integrations import PyApiModel, python_models
from appgen.bindings.fastapi.pysource import call, from_import, literal, string
from appgen.dsl.model import AppDefinition
from appgen.dsl.openapi import Ref, ScalarSchema, property_chain, resolved, sample
from appgen.dsl.webhooks import Webhook
from appgen.gen.naming import snake

TEST_EVENT_ID = "evt-1"
"""The event ID of the sample body of the generated tests."""


@dataclass(slots=True)
class PyWebhook:
    """A webhook, as a package of the app."""

    name: str
    id: str
    module: str
    """The name of the package, for example `payments`."""
    path: str
    description: str | None
    scheme: str
    """`hmac_sha256` or `stripe`."""
    header: str
    """The header with the signature."""
    prefix: str
    encoding: str
    tolerance: int
    secret_setting: str
    """The attribute of the settings with the secret, for example `payments_secret`."""
    secret_env: str
    event_field: tuple[str, ...]
    """The properties of the body with the event ID, or empty for a header."""
    event_header: str | None
    body_type: str
    """The type of the event: the model of the schema of the body, or `JsonValue`."""
    models: list[PyApiModel] = field(default_factory=list[PyApiModel])
    sample: dict[str, object] = field(default_factory=dict[str, object])
    """A valid body with the event ID `TEST_EVENT_ID`, for the generated tests."""

    @property
    def handler(self) -> str:
        """The function of the extension file, for example `handle_payments`."""
        return f"handle_{self.module}"

    @property
    def endpoint(self) -> str:
        return f"receive_{self.module}"

    @property
    def typed(self) -> bool:
        """True if the body has a schema, so the event has the type of the schema."""
        return bool(self.models)

    @property
    def body_class(self) -> bool:
        """True if the type of the event is a Pydantic model (an object schema)."""
        return any(m.name == self.body_type and m.fields is not None for m in self.models)

    @property
    def sample_event_id(self) -> str:
        """The event ID of the sample body or of the header of the generated tests."""
        if self.event_header:
            return TEST_EVENT_ID
        value: object = self.sample
        for name in self.event_field:
            value = _member(value, name)
        return str(value)

    def model_imports(self) -> list[str]:
        """Return the import lines of `models.py`."""
        types = [m.alias for m in self.models] + [
            f.type for m in self.models for f in (m.fields or [])
        ]
        text = " ".join(types)
        lines = ["import pydantic"]
        for module, prefix in (("datetime as dt", "dt."), ("uuid", "uuid."), ("typing", "typing.")):
            if prefix in text:
                lines.append(f"import {module}")
        return lines

    def router_imports(self) -> list[str]:
        """Return the import lines of `router.py`."""
        names = ["WebhookReceipt", "read_json", "record_event", "require_secret"]
        names.append("check_stripe" if self.scheme == "stripe" else "check_hmac_sha256")
        names.append("event_id_in_header" if self.event_header else "event_id_in_body")
        lines = [
            "from fastapi import APIRouter, Request",
            "from app.core.config import Settings",
            "from app.core.db import SessionDep, commit",
            "from app.core.errors import problem_responses",
            f"from app.webhooks.{self.module}.handler_ext import {self.handler}",
        ]
        if self.typed:
            names.append("read_event")
            lines.append("from pydantic import TypeAdapter")
            lines.append(f"from app.webhooks.{self.module}.models import {self.body_type}")
        lines.append(from_import("app.core.webhooks", set(names)))
        return lines

    def handler_imports(self) -> list[str]:
        """Return the import lines of `handler_ext.py`."""
        lines = [
            "from collections.abc import Mapping",
            "from sqlalchemy.ext.asyncio import AsyncSession",
        ]
        if self.typed:
            lines.append(f"from app.webhooks.{self.module}.models import {self.body_type}")
        else:
            lines.append("from pydantic import JsonValue")
        return lines

    def check_lines(self) -> list[str]:
        """Return the statements of the endpoint that check the signature (indent 4)."""
        secret = f"require_secret(settings.{self.secret_setting}, {string(self.name)})"
        header = f"request.headers.get({string(self.header)})"
        if self.scheme == "stripe":
            args = ["secret", "body", header, f"tolerance={self.tolerance}"]
            check = call("", "check_stripe", args)
        else:
            args = [
                "secret",
                "body",
                header,
                f"prefix={string(self.prefix)}",
                f"encoding={string(self.encoding)}",
            ]
            check = call("", "check_hmac_sha256", args)
        return [f"secret = {secret}", check]

    def event_id_line(self) -> str:
        """Return the statement that reads the event ID (indent 4)."""
        if self.event_header:
            header = f"request.headers.get({string(self.event_header)})"
            return f"event_id = event_id_in_header({header})"
        path = literal(list(self.event_field)).replace("[", "(", 1)
        path = path[:-1] + ("," if len(self.event_field) == 1 else "") + ")"
        return f"event_id = event_id_in_body(data, {path})"

    def sample_line(self, variable: str = "BODY") -> str:
        """Return the constant of the sample body for the tests."""
        return literal(self.sample, f"{variable}: dict[str, object] = ")


def python_webhooks(definition: AppDefinition) -> dict[str, PyWebhook]:
    """Return the model of each webhook of a definition, by name."""
    return {name: _webhook(name, webhook) for name, webhook in definition.webhooks.items()}


def _webhook(name: str, webhook: Webhook) -> PyWebhook:
    signature = webhook.signature
    event_id = webhook.event_id
    module = snake(name)
    py = PyWebhook(
        name=name,
        id=webhook.id,
        module=module,
        path=webhook.path,
        description=webhook.description,
        scheme=signature.scheme,
        header=signature.signature_header,
        prefix=signature.prefix,
        encoding=signature.encoding,
        tolerance=signature.tolerance_seconds,
        secret_setting=signature.secret_env.lower(),
        secret_env=signature.secret_env,
        event_field=event_id.path,
        event_header=event_id.header,
        body_type="JsonValue",
    )
    spec = webhook.spec
    schema_name = webhook.body_schema
    body: dict[str, object] = {}
    if schema_name is not None and spec.schemas:
        py.models = python_models(spec.schemas)
        py.body_type = schema_name
        found = sample(Ref(schema_name), spec)
        body = dict(found) if isinstance(found, dict) else {}
    if event_id.field is not None:
        value: object = TEST_EVENT_ID
        chain = property_chain(Ref(schema_name), event_id.field, spec) if schema_name else None
        if chain:
            last = resolved(chain[-1].schema, spec)
            if isinstance(last, ScalarSchema) and last.type == "integer":
                value = 1
        _set_path(body, event_id.path, value)
    py.sample = body
    return py


def _member(value: object, name: str) -> object:
    """Return a property of an object of a sample, or None."""
    return cast(dict[str, object], value).get(name) if isinstance(value, dict) else None


def _set_path(data: dict[str, object], path: tuple[str, ...], value: object) -> None:
    """Set the value at a path of properties, with an object for each missing step."""
    current = data
    for name in path[:-1]:
        step: object = current.get(name)
        if not isinstance(step, dict):
            step = current[name] = dict[str, object]()
        current = cast(dict[str, object], step)
    current[path[-1]] = value
