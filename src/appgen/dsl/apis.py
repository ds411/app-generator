"""The third-party APIs of an app: their OpenAPI documents and the operations that it calls.

The loader reads each document from the folder of the definition (ADR
0019). The validator reports a document that is not valid, an operation
ID that the document does not have, and a security scheme that it does
not declare. The bindings generate a typed client from `Api.spec`.
"""

from pathlib import Path
from typing import Annotated, Any, cast

import pydantic
from pydantic import BaseModel, BeforeValidator, ConfigDict, PrivateAttr, StringConstraints

from appgen.dsl.diagnostics import Diagnostic
from appgen.dsl.element import Element, Text
from appgen.dsl.openapi import ClientSpec, DocumentError, OpenApiDocument, read_document
from appgen.dsl.source import SourceMap

OPERATION_ID_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
ENV_NAME_PATTERN = r"^[A-Z][A-Z0-9_]*$"
RESERVED_ENV_NAMES = frozenset(
    {
        "API_URL",
        "AUTH_SECRET",
        "CORS_ORIGINS",
        "DATABASE_MIGRATE",
        "DATABASE_SEED",
        "DATABASE_URL",
        "HOSTNAME",
        "LOG_JSON",
        "LOG_LEVEL",
        "NODE_ENV",
        "PATH",
        "PORT",
        "RATE_LIMIT_PER_MINUTE",
        "SEED_PASSWORD",
        "TEST_DATABASE_URL",
    }
)
"""The environment variables that the generated apps use for their own settings."""

type OperationId = Annotated[str, StringConstraints(pattern=OPERATION_ID_PATTERN)]
"""The operation ID of an OpenAPI operation. A trace segment has only letters, digits, and `_`."""
type EnvName = Annotated[str, StringConstraints(pattern=ENV_NAME_PATTERN)]
"""The name of an environment variable, in upper case, for example `HOLIDAYS_API_URL`."""


class ApiSecurity(BaseModel):
    """The credential that the client sends with each request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scheme: Text
    """A key of `components.securitySchemes` of the document: an API key or a bearer token."""
    env: EnvName
    """The environment variable that holds the secret."""


class ApiOperation(Element):
    """An operation of the document that the app calls. Its name is the operation ID."""

    description: Text | None = None
    """What the app does with the operation. The default is the summary of the document."""


def _operations_input(value: object) -> object:
    """Return the mapping form of a list of operation IDs."""
    if not isinstance(value, list):
        return value
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        return items
    return {str(item): cast(dict[str, object], {}) for item in items}


def _operations_schema(schema: dict[str, Any]) -> None:
    """Add the short form (a list of operation IDs) to the JSON Schema of the key."""
    names = {"type": "array", "items": {"type": "string", "pattern": OPERATION_ID_PATTERN}}
    mapping = {k: v for k, v in schema.items() if k not in ("minLength", "title")}
    schema["anyOf"] = [{**names, "minItems": 1}, {**mapping, "minProperties": 1}]
    for key in ("type", "additionalProperties", "propertyNames", "minLength"):
        schema.pop(key, None)


class Api(Element):
    """A third-party API that an OpenAPI document describes (ADR 0019)."""

    document: Text
    """The path of the OpenAPI document (3.0 or 3.1, YAML or JSON), from the folder of the
    definition."""
    base_url_env: EnvName
    """The environment variable of the base URL. The default is the first server of the
    document."""
    title: Text | None = None
    """The name of the API in the docs of the apps. The default is the title of the document."""
    description: Text | None = None
    security: ApiSecurity | None = None
    """The credential of the requests. Without it, the requests have no credential."""
    operations: Annotated[
        dict[OperationId, ApiOperation],
        BeforeValidator(_operations_input),
        pydantic.Field(min_length=1, json_schema_extra=_operations_schema),
    ]
    """The operations that the app calls: a list of operation IDs, or a mapping."""

    _openapi: OpenApiDocument | None = PrivateAttr(default=None)
    _error: str | None = PrivateAttr(default=None)
    _spec: ClientSpec | None = PrivateAttr(default=None)

    @property
    def openapi(self) -> OpenApiDocument | None:
        """The document, or None if the loader did not read it or it is not valid."""
        return self._openapi

    @property
    def document_error(self) -> str | None:
        """Why the document cannot be read, or None."""
        return self._error

    @property
    def spec(self) -> ClientSpec:
        """The selected operations and their schemas. Empty if the document is not valid."""
        if self._spec is None:
            self._spec = (
                self._openapi.select(self.operations)
                if self._openapi is not None
                else ClientSpec((), ())
            )
        return self._spec

    def read_document(self, base_dir: Path) -> None:
        """Read the document from a folder. Keep the error of a document that is not valid, for
        the validator."""
        self._openapi, self._error, self._spec = None, None, None
        if "://" in self.document:
            self._error = "The document must be a local file, not a URL."
            return
        try:
            self._openapi = read_document(base_dir / self.document)
        except DocumentError as error:
            self._error = str(error)

    @property
    def label(self) -> str:
        """The title of the API, or of its document, or its name."""
        if self.title is not None:
            return self.title
        if self._openapi is not None:
            return self._openapi.title
        return self.id.rpartition(".")[2]


def expand_operations(data: object, source_map: SourceMap) -> list[Diagnostic]:
    """Point the source map of each operation in a list of operation IDs to its item.

    The model turns the list into a mapping (see `_operations_input`). The
    function reports an operation ID that occurs twice in a list.
    """
    diagnostics: list[Diagnostic] = []
    apis = cast(dict[str, object], data).get("apis") if isinstance(data, dict) else None
    if not isinstance(apis, dict):
        return diagnostics
    for name, api in cast(dict[str, object], apis).items():
        if not isinstance(api, dict):
            continue
        operations = cast(dict[str, object], api).get("operations")
        if not isinstance(operations, list):
            continue
        seen: set[str] = set()
        for index, item in enumerate(cast(list[object], operations)):
            if not isinstance(item, str):
                continue
            location = source_map.value(("apis", name, "operations", index))
            if item in seen:
                diagnostics.append(
                    Diagnostic(
                        code="duplicate-name",
                        message=f"The operation '{item}' occurs more than one time.",
                        location=location,
                        element_id=f"apis.{name}",
                    )
                )
                continue
            seen.add(item)
            source_map.keys[("apis", name, "operations", item)] = location
    return diagnostics
