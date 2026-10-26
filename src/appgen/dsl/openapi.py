"""Read an OpenAPI document, and select the operations that an app calls (ADR 0019).

The reader knows the parts of OpenAPI 3.0 and 3.1 that the clients of
the bindings need: the paths and their operations, the parameters, the
bodies of the requests (JSON, forms, and multipart forms) and of the
answers (JSON, text, and binary data), the schemas, the examples, and
the security schemes. It resolves the local `$ref`s, and it rejects
a remote `$ref`, so that the generator reads only local files.

`OpenApiDocument.select` gives the selected operations with the schemas
that they need, in a normal form: each object schema has a name, so that
a binding writes one class or one interface for it. The other schemas of
the document are not in the result, so a large document gives a small
client.
"""

import datetime
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from pydantic import JsonValue

from appgen.dsl.diagnostics import DefinitionError
from appgen.dsl.source import DataPath, SourceMap, read_yaml

SUPPORTED_VERSIONS = ("3.0", "3.1")
HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")
SCHEMAS_PREFIX = "#/components/schemas/"
FORM_MEDIA = "application/x-www-form-urlencoded"
MULTIPART_MEDIA = "multipart/form-data"
EXAMPLE_TEXT = "appgen example"
"""The example of a text answer without an example, and the content of the example of a binary
answer: the mocks send its UTF-8 bytes."""

type ParameterLocation = Literal["path", "query", "header", "cookie"]
type BodyKind = Literal["json", "form", "multipart"]
"""How the client sends a body: as JSON, as a form (`application/x-www-form-urlencoded`), or
as a multipart form (`multipart/form-data`)."""
type AnswerKind = Literal["json", "text", "binary"]
"""How the client reads an answer: as JSON, as text (`text/*`), or as binary data."""
type ScalarType = Literal["string", "integer", "number", "boolean", "null"]
type Scalar = str | int | float | bool | None


class DocumentError(Exception):
    """The document cannot be read, or it is not a valid OpenAPI document."""


@dataclass(frozen=True, slots=True)
class Ref:
    """A named schema of the client (`ClientSpec.schemas`)."""

    name: str


@dataclass(frozen=True, slots=True)
class ScalarSchema:
    """A string, a number, a boolean, or null, with its format and its allowed values."""

    type: ScalarType
    format: str | None = None
    enum: tuple[Scalar, ...] = ()
    """The allowed values. Empty: all values of the type."""


@dataclass(frozen=True, slots=True)
class ArraySchema:
    items: Schema


@dataclass(frozen=True, slots=True)
class MapSchema:
    """An object with any keys, and values of one schema (`additionalProperties`)."""

    values: Schema


@dataclass(frozen=True, slots=True)
class UnionSchema:
    """A value of one of the options (`oneOf`, `anyOf`, a type list, or `nullable`)."""

    options: tuple[Schema, ...]


@dataclass(frozen=True, slots=True)
class AnySchema:
    """Any JSON value: a schema that the reader cannot express in the normal form."""


@dataclass(frozen=True, slots=True)
class Property:
    name: str
    """The name in the JSON object."""
    schema: Schema
    required: bool
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectSchema:
    """An object with named properties. Only a named schema has this form."""

    properties: tuple[Property, ...]


type Schema = Ref | ScalarSchema | ArraySchema | MapSchema | UnionSchema | AnySchema | ObjectSchema


@dataclass(frozen=True, slots=True)
class NamedSchema:
    name: str
    """The name in Pascal case, for example `PublicHoliday`."""
    source: str
    """Where the schema comes from: a pointer into the document."""
    schema: Schema
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    location: ParameterLocation
    required: bool
    schema: Schema
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Operation:
    """A selected operation of the document, in the normal form."""

    id: str
    method: str
    """The HTTP method in lower case, for example `get`."""
    path: str
    """The path template, for example `/PublicHolidays/{year}/{countryCode}`."""
    summary: str | None
    description: str | None
    parameters: tuple[Parameter, ...]
    body: Schema | None
    """The body of the request, or None. A form body is an object."""
    body_required: bool
    status: str
    """The status of the answer that the client reads, for example `200`."""
    result: Schema | None
    """The body of the answer, or None for an answer without a body. A text answer is a string,
    and a binary answer is a string with the format `binary`."""
    example: JsonValue
    """The example answer of the document, or a sample of the result schema. The example of a
    binary answer is `EXAMPLE_TEXT`."""
    body_kind: BodyKind = "json"
    answer: AnswerKind = "json"
    answer_media: str = "application/json"
    """The media type of the answer, for the header `Accept`, for example `text/csv`."""


@dataclass(frozen=True, slots=True)
class SecurityScheme:
    name: str
    type: str
    """`apiKey`, `http`, `oauth2`, `openIdConnect`, or `mutualTLS`."""
    scheme: str | None = None
    """The scheme of the type `http` in lower case, for example `bearer`."""
    location: str | None = None
    """Where an `apiKey` goes: `header`, `query`, or `cookie`."""
    parameter: str | None = None
    """The name of the header or the query parameter of an `apiKey`."""
    flows: tuple[str, ...] = ()
    """The flows of an `oauth2` scheme, for example `clientCredentials`."""
    token_url: str | None = None
    """The token URL of the client credentials flow. A path (`/oauth/token`) is under the base
    URL of the API."""
    scopes: tuple[str, ...] = ()
    """The scopes of the client credentials flow."""

    @property
    def supported(self) -> bool:
        """True for an API key in a header or a query parameter, for a bearer token, and for
        OAuth 2.0 with the client credentials flow."""
        if self.type == "apiKey":
            return self.location in ("header", "query") and bool(self.parameter)
        if self.type == "oauth2":
            return self.token_url is not None
        return self.type == "http" and self.scheme == "bearer"


@dataclass(frozen=True, slots=True)
class ClientSpec:
    """The selected operations of a document, and the schemas that they need."""

    operations: tuple[Operation, ...]
    schemas: tuple[NamedSchema, ...]
    """The named schemas, sorted by name."""
    problems: tuple[tuple[str, str], ...] = ()
    """The operations that a client cannot call: the operation ID and the reason."""

    def schema(self, name: str) -> NamedSchema:
        """Return the named schema with a name."""
        return next(s for s in self.schemas if s.name == name)


@dataclass(slots=True)
class OpenApiDocument:
    """An OpenAPI document that the reader checked."""

    path: Path
    hash: str
    """The SHA-256 hash of the file, as the output manifest records it."""
    version: str
    title: str
    base_url: str
    """The URL of the first server, with the defaults of its variables. Empty if it has none."""
    security_schemes: Mapping[str, SecurityScheme]
    _data: dict[str, object]
    _operations: dict[str, tuple[str, str, dict[str, object]]]
    """The path, the method, and the data of each operation, by ID."""
    _source: SourceMap | None = None

    @property
    def operation_ids(self) -> tuple[str, ...]:
        """The IDs of all operations of the document, in document order."""
        return tuple(self._operations)

    def select(self, operation_ids: Iterable[str]) -> ClientSpec:
        """Return the operations with these IDs, and the schemas that they need.

        An ID that the document does not have gives no operation.
        """
        builder = _Builder(self._data)
        operations: list[Operation] = []
        for operation_id in operation_ids:
            found = self._operations.get(operation_id)
            if found is not None:
                operations.append(builder.operation(operation_id, *found))
        return ClientSpec(
            operations=tuple(operations),
            schemas=tuple(sorted(builder.schemas.values(), key=lambda s: s.name)),
            problems=tuple(builder.problems),
        )

    @property
    def schema_keys(self) -> tuple[str, ...]:
        """The names of the schemas in `components.schemas`, in document order."""
        components = self._data.get("components")
        if not isinstance(components, dict):
            return ()
        found = cast(dict[str, object], components).get("schemas")
        return tuple(cast(dict[str, object], found)) if isinstance(found, dict) else ()

    def select_schemas(self, keys: Iterable[str]) -> ClientSpec:
        """Return the component schemas with these names, and the schemas that they need.

        A name that the document does not have gives no schema. The result
        has no operations.
        """
        builder = _Builder(self._data)
        known = set(self.schema_keys)
        for key in keys:
            if key in known:
                builder.component(key)
        return ClientSpec((), tuple(sorted(builder.schemas.values(), key=lambda s: s.name)))

    def schema_name(self, key: str) -> str | None:
        """Return the name of a component schema in the normal form, or None if the document
        has no schema with the name."""
        if key not in self.schema_keys:
            return None
        return _Builder(self._data).component(key)


def read_document(path: Path) -> OpenApiDocument:
    """Read an OpenAPI document (YAML or JSON). Raise DocumentError if it is not valid."""
    try:
        content = path.read_bytes()
    except OSError as error:
        raise DocumentError(f"Cannot read the document: {error.strerror or error}.") from None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise DocumentError("The document is not UTF-8 text.") from None
    source: SourceMap | None = None
    try:
        document = read_yaml(text, str(path))
        data, source = document.data, document.source_map
    except DefinitionError as error:
        try:
            data = json.loads(text)
        except ValueError:
            problem = error.diagnostics[0]
            raise DocumentError(
                f"{problem.location}: the document is not YAML or JSON: {problem.message}"
            ) from None
    reader = _Reader(path, source)
    return reader.read(_plain(data), "sha256:" + hashlib.sha256(content).hexdigest())


def sample(schema: Schema, spec: ClientSpec) -> JsonValue:
    """Return a valid sample value of a schema, the same each time."""
    return _sample(schema, spec, ())


def _sample(schema: Schema, spec: ClientSpec, seen: tuple[str, ...]) -> JsonValue:
    match schema:
        case Ref(name):
            if name in seen:
                return None
            return _sample(spec.schema(name).schema, spec, (*seen, name))
        case ScalarSchema(type_, format_, enum):
            if enum:
                return enum[0]
            return _scalar_sample(type_, format_)
        case ArraySchema(items):
            return [_sample(items, spec, seen)]
        case MapSchema():
            return {}
        case UnionSchema(options):
            return _sample(options[0], spec, seen)
        case ObjectSchema(properties):
            return {p.name: _sample(p.schema, spec, seen) for p in properties if p.required}
        case AnySchema():
            return None


def _scalar_sample(type_: ScalarType, format_: str | None) -> JsonValue:
    match type_:
        case "string":
            return {
                "date": "2026-01-01",
                "date-time": "2026-01-01T00:00:00Z",
                "uuid": "00000000-0000-4000-8000-000000000000",
                "email": "user@example.com",
                "uri": "https://example.com",
            }.get(format_ or "", "string")
        case "integer":
            return 0
        case "number":
            return 0.0
        case "boolean":
            return False
        case "null":
            return None


def _plain(value: object) -> object:
    """Return the data with each date as text, as JSON gives it."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in cast(dict[object, object], value).items()}
    if isinstance(value, list):
        return [_plain(item) for item in cast(list[object], value)]
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _pointer(path: DataPath) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in path)


def _unescape(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


class _Reader:
    """Check the structure of a document, and find its operations and security schemes."""

    def __init__(self, path: Path, source: SourceMap | None) -> None:
        self.path = path
        self.source = source

    def error(self, at: DataPath, message: str) -> DocumentError:
        where = _pointer(at) if at else "/"
        if self.source is not None:
            return DocumentError(f"{self.source.value(at)} ({where}): {message}")
        return DocumentError(f"{self.path} ({where}): {message}")

    def read(self, data: object, digest: str) -> OpenApiDocument:
        if not isinstance(data, dict):
            raise self.error((), "An OpenAPI document is a mapping.")
        root = cast(dict[str, object], data)
        version = root.get("openapi")
        if version is None:
            if "swagger" in root:
                raise self.error(("swagger",), "Swagger 2.0 is not supported. Use OpenAPI 3.")
            raise self.error((), "The key 'openapi' is missing.")
        if not isinstance(version, str) or not re.match(r"^3\.[01]\.\d+$", version):
            raise self.error(
                ("openapi",),
                f"The OpenAPI version {version!r} is not supported. Use 3.0 or 3.1.",
            )
        info = self.mapping(root, ("info",), required=True)
        title = info.get("title")
        if not isinstance(title, str):
            raise self.error(("info",), "The key 'title' is missing.")
        self.check_refs(root, root, ())
        operations: dict[str, tuple[str, str, dict[str, object]]] = {}
        paths = self.mapping(root, ("paths",))
        for path, value in paths.items():
            item = self.resolved(root, value, ("paths", path))
            if not path.startswith("/"):
                raise self.error(("paths", path), "A path must start with '/'.")
            for method, value in item.items():
                if method not in HTTP_METHODS:
                    continue
                at = ("paths", path, method)
                operation = self.resolved(root, value, at)
                self.mapping(operation, (*at, "responses"), required=True, data_at=at)
                operation_id = operation.get("operationId")
                if operation_id is None:
                    continue
                if not isinstance(operation_id, str):
                    raise self.error((*at, "operationId"), "The operation ID must be a string.")
                if operation_id in operations:
                    raise self.error(
                        (*at, "operationId"), f"The operation ID '{operation_id}' is not unique."
                    )
                merged = {**operation, "parameters": self.parameters(root, item, operation, at)}
                operations[operation_id] = (path, method, merged)
        schemes: dict[str, SecurityScheme] = {}
        components = self.mapping(root, ("components",))
        security = self.mapping(components, ("components", "securitySchemes"), data_at=())
        for name, value in security.items():
            at = ("components", "securitySchemes", name)
            scheme = self.resolved(root, value, at)
            kind = scheme.get("type")
            if not isinstance(kind, str):
                raise self.error((*at, "type"), "A security scheme needs a 'type'.")
            http = scheme.get("scheme")
            flows = scheme.get("flows")
            flows = cast(dict[str, object], flows) if isinstance(flows, dict) else {}
            client = flows.get("clientCredentials")
            client = cast(dict[str, object], client) if isinstance(client, dict) else {}
            scopes = client.get("scopes")
            schemes[name] = SecurityScheme(
                name=name,
                type=kind,
                scheme=http.lower() if isinstance(http, str) else None,
                location=_text(scheme.get("in")),
                parameter=_text(scheme.get("name")),
                flows=tuple(flows),
                token_url=_text(client.get("tokenUrl")) if kind == "oauth2" else None,
                scopes=tuple(cast(dict[str, object], scopes)) if isinstance(scopes, dict) else (),
            )
        return OpenApiDocument(
            path=self.path,
            hash=digest,
            version=version,
            title=title,
            base_url=self.base_url(root),
            security_schemes=MappingProxyType(schemes),
            _data=root,
            _operations=operations,
            _source=self.source,
        )

    def mapping(
        self,
        parent: dict[str, object],
        at: DataPath,
        *,
        required: bool = False,
        data_at: DataPath | None = None,
    ) -> dict[str, object]:
        """Return the mapping at the last key of `at` in `parent`, or an empty mapping."""
        value = parent.get(str(at[-1]))
        if value is None:
            if required:
                where = data_at if data_at is not None else at[:-1]
                raise self.error(where, f"The key '{at[-1]}' is missing.")
            return {}
        if not isinstance(value, dict):
            raise self.error(at, f"The value of '{at[-1]}' must be a mapping.")
        return cast(dict[str, object], value)

    def resolved(self, root: dict[str, object], value: object, at: DataPath) -> dict[str, object]:
        """Return a mapping, after its `$ref` if it has one."""
        seen: set[str] = set()
        while isinstance(value, dict) and "$ref" in value:
            ref = cast(dict[str, object], value)["$ref"]
            if not isinstance(ref, str) or ref in seen:
                raise self.error(at, f"The $ref {ref!r} cannot be resolved.")
            seen.add(ref)
            value = _follow(root, ref)
        if not isinstance(value, dict):
            raise self.error(at, "Expected a mapping.")
        return cast(dict[str, object], value)

    def check_refs(self, root: dict[str, object], value: object, at: DataPath) -> None:
        """Check that each `$ref` is local and resolves."""
        if isinstance(value, list):
            for index, item in enumerate(cast(list[object], value)):
                self.check_refs(root, item, (*at, index))
            return
        if not isinstance(value, dict):
            return
        node = cast(dict[str, object], value)
        ref = node.get("$ref")
        if isinstance(ref, str) and not (at and at[-1] == "properties"):
            if not ref.startswith("#"):
                raise self.error(
                    (*at, "$ref"),
                    f"The $ref '{ref}' is not local. appgen reads only one local file: "
                    "copy the parts of the other file into the document.",
                )
            if _follow(root, ref) is None:
                raise self.error((*at, "$ref"), f"The $ref '{ref}' does not resolve.")
        for key, item in node.items():
            # An example is data: a key `$ref` in it is not a reference.
            if key != "example":
                self.check_refs(root, item, (*at, key))

    def parameters(
        self,
        root: dict[str, object],
        item: dict[str, object],
        operation: dict[str, object],
        at: DataPath,
    ) -> list[object]:
        """Return the parameters of the path and of the operation. The operation wins."""
        found: dict[tuple[str, str], dict[str, object]] = {}
        for owner, where in ((item, at[:-1]), (operation, at)):
            values = owner.get("parameters", [])
            if not isinstance(values, list):
                raise self.error((*where, "parameters"), "The parameters must be a list.")
            for index, value in enumerate(cast(list[object], values)):
                parameter = self.resolved(root, value, (*where, "parameters", index))
                name, location = parameter.get("name"), parameter.get("in")
                if not isinstance(name, str) or not isinstance(location, str):
                    raise self.error(
                        (*where, "parameters", index), "A parameter needs 'name' and 'in'."
                    )
                found[(name, location)] = parameter
        return list(found.values())

    def base_url(self, root: dict[str, object]) -> str:
        """Return the URL of the first server, with the defaults of its variables, or ''."""
        servers = root.get("servers")
        if not isinstance(servers, list) or not servers:
            return ""
        first = cast(list[object], servers)[0]
        if not isinstance(first, dict):
            return ""
        server = cast(dict[str, object], first)
        url = server.get("url")
        if not isinstance(url, str):
            return ""
        defaults: dict[str, str] = {}
        variables = server.get("variables")
        if isinstance(variables, dict):
            for name, value in cast(dict[str, object], variables).items():
                default = (
                    cast(dict[str, object], value).get("default")
                    if isinstance(value, dict)
                    else None
                )
                if isinstance(default, str):
                    defaults[name] = default
        resolved = re.sub(r"\{([^}]+)\}", lambda m: defaults.get(m.group(1), m.group(0)), url)
        return resolved.rstrip("/") if re.match(r"^https?://[^{}\s]+$", resolved) else ""


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _follow(root: object, ref: str) -> object:
    """Return the value at a local `$ref`, or None if it does not exist."""
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return None
    value = root
    for part in ref[2:].split("/"):
        key = _unescape(part)
        if isinstance(value, dict):
            mapping = cast(dict[str, object], value)
            if key not in mapping:
                return None
            value = mapping[key]
        elif isinstance(value, list):
            items = cast(list[object], value)
            if not key.isdigit() or int(key) >= len(items):
                return None
            value = items[int(key)]
        else:
            return None
    return value


def type_name(text: str) -> str:
    """Return a Pascal case name for a schema name or an operation ID: `public_holiday` gives
    `PublicHoliday`, and `getHolidays` gives `GetHolidays`."""
    parts = re.findall(r"[A-Za-z0-9]+", text)
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if not name or name[0].isdigit():
        name = "Schema" + name
    return name


_JSON = re.compile(r"^application/(?:[\w.+-]+\+)?json(?:;.*)?$")


def _media_type(key: str) -> str:
    """Return a media type in lower case, without its parameters."""
    return key.split(";")[0].strip().lower()


class _Builder:
    """Convert the selected operations and their schemas to the normal form."""

    def __init__(self, root: dict[str, object]) -> None:
        self.root = root
        self.schemas: dict[str, NamedSchema] = {}
        self.components: dict[str, str] = {}
        """The name of each component schema that the client uses, by its name in the document."""
        self.problems: list[tuple[str, str]] = []

    def operation(
        self, operation_id: str, path: str, method: str, data: dict[str, object]
    ) -> Operation:
        base = type_name(operation_id)
        parameters: list[Parameter] = []
        for value in cast(list[dict[str, object]], data.get("parameters", [])):
            name, location = str(value["name"]), str(value["in"])
            if location not in ("path", "query", "header", "cookie"):
                self.problems.append(
                    (
                        operation_id,
                        f"The parameter '{name}' is in a {location}. "
                        "The clients send only path, query, header, and cookie parameters.",
                    )
                )
                continue
            schema = self.schema(value.get("schema", {}), base + type_name(name))
            if location == "cookie" and not query_value(schema, self.spec(), item=True):
                self.problems.append(
                    (
                        operation_id,
                        f"The cookie parameter '{name}' is not a text, a number, or a boolean. "
                        "The clients send only such cookie parameters.",
                    )
                )
                continue
            parameters.append(
                Parameter(
                    name=name,
                    location=location,
                    required=location == "path" or value.get("required") is True,
                    schema=schema,
                    description=_text(value.get("description")),
                )
            )
        body: Schema | None = None
        body_required = False
        body_kind: BodyKind = "json"
        request = data.get("requestBody")
        if request is not None:
            request_data = self.resolve(request)
            found = self.request_media(request_data.get("content"))
            if found is None:
                self.problems.append(
                    (
                        operation_id,
                        "The request body is not JSON, a form, or a multipart form. The clients "
                        "send only these bodies.",
                    )
                )
            else:
                body_kind, media = found
                body = self.schema(media.get("schema", {}), base + "Body")
                body_required = request_data.get("required") is True
                problem = self.form_problem(body, body_kind)
                if problem is not None:
                    self.problems.append((operation_id, problem))
                    body = None
        status, response = self.success(data.get("responses"))
        result: Schema | None = None
        example: JsonValue = None
        answer: AnswerKind = "json"
        answer_media = "application/json"
        if response is not None:
            content = response.get("content")
            if isinstance(content, dict) and content:
                answer, answer_media, media = self.answer_media(cast(dict[str, object], content))
                if answer == "json":
                    result = self.schema(media.get("schema", {}), base + "Result")
                    example = self.example(media)
                elif answer == "text":
                    result = ScalarSchema("string")
                    found_example = self.example(media)
                    example = found_example if isinstance(found_example, str) else EXAMPLE_TEXT
                else:
                    result = ScalarSchema("string", "binary")
                    example = EXAMPLE_TEXT
        if result is not None and example is None:
            example = sample(result, self.spec())
        return Operation(
            id=operation_id,
            method=method,
            path=path,
            summary=_text(data.get("summary")),
            description=_text(data.get("description")),
            parameters=tuple(parameters),
            body=body,
            body_required=body_required,
            status=status,
            result=result,
            example=example,
            body_kind=body_kind,
            answer=answer,
            answer_media=answer_media,
        )

    def spec(self) -> ClientSpec:
        """Return the named schemas so far, to resolve a `Ref`."""
        return ClientSpec((), tuple(self.schemas.values()))

    def form_problem(self, body: Schema, kind: BodyKind) -> str | None:
        """Return why a client cannot send a body as a form, or None."""
        if kind == "json":
            return None
        spec = self.spec()
        properties = object_properties(body, spec)
        label = "form" if kind == "form" else "multipart form"
        if properties is None:
            return f"The {label} body is not an object with properties."
        if kind == "multipart":
            return None
        for prop in properties:
            if not query_value(prop.schema, spec) or is_file(prop.schema, spec):
                return (
                    f"The property '{prop.name}' of the form body is not a text, a number, a "
                    "boolean, or a list of these. Send a file or an object in a multipart form."
                )
        return None

    def resolve(self, value: object) -> dict[str, object]:
        seen: set[str] = set()
        while isinstance(value, dict):
            data = cast(dict[str, object], value)
            ref = data.get("$ref")
            if not isinstance(ref, str):
                return data
            if ref in seen:
                return {}
            seen.add(ref)
            value = _follow(self.root, ref)
        return {}

    def request_media(self, content: object) -> tuple[BodyKind, dict[str, object]] | None:
        """Return the kind and the media of the body that the client sends: JSON first, then a
        form, then a multipart form."""
        if not isinstance(content, dict):
            return None
        media = {_media_type(key): value for key, value in cast(dict[str, object], content).items()}
        for key, value in media.items():
            if _JSON.match(key):
                return "json", self.resolve(value)
        for kind, key in (("form", FORM_MEDIA), ("multipart", MULTIPART_MEDIA)):
            if key in media:
                return cast(BodyKind, kind), self.resolve(media[key])
        return None

    def answer_media(self, content: dict[str, object]) -> tuple[AnswerKind, str, dict[str, object]]:
        """Return the kind, the media type, and the media of the answer that the client reads:
        JSON first, then text, then binary data."""
        for key, value in content.items():
            if _JSON.match(_media_type(key)):
                return "json", key, self.resolve(value)
        for key, value in content.items():
            if _media_type(key).startswith("text/"):
                return "text", key, self.resolve(value)
        key, value = next(iter(content.items()))
        return "binary", key, self.resolve(value)

    def success(self, responses: object) -> tuple[str, dict[str, object] | None]:
        """Return the status and the data of the first success answer."""
        codes = cast(dict[str, object], responses) if isinstance(responses, dict) else {}
        for code in sorted(codes):
            if re.match(r"^2(\d\d|XX)$", code):
                return code, self.resolve(codes[code])
        if "default" in codes:
            return "200", self.resolve(codes["default"])
        return "200", None

    def example(self, media: dict[str, object]) -> JsonValue:
        if "example" in media:
            return cast(JsonValue, media["example"])
        examples = media.get("examples")
        if isinstance(examples, dict):
            for value in cast(dict[str, object], examples).values():
                found = self.resolve(value)
                if "value" in found:
                    return cast(JsonValue, found["value"])
        schema = self.resolve(media.get("schema", {}))
        if "example" in schema:
            return cast(JsonValue, schema["example"])
        listed = schema.get("examples")
        if isinstance(listed, list) and listed:
            return cast(JsonValue, cast(list[object], listed)[0])
        return None

    def name(self, wanted: str) -> str:
        name = wanted
        number = 2
        while name in self.schemas:
            name = f"{wanted}{number}"
            number += 1
        return name

    def component(self, key: str) -> str:
        """Return the name of a component schema, and add it to the client the first time."""
        found = self.components.get(key)
        if found is not None:
            return found
        name = self.name(type_name(key))
        self.components[key] = name
        source = SCHEMAS_PREFIX + key.replace("~", "~0").replace("/", "~1")
        data = self.resolve(_follow(self.root, source))
        # A placeholder, so that a schema that refers to itself finds its name.
        self.schemas[name] = NamedSchema(name, source, AnySchema())
        self.schemas[name] = NamedSchema(
            name, source, self.body(data, name), _text(data.get("description"))
        )
        return name

    def body(self, data: dict[str, object], name: str) -> Schema:
        """Return the schema of a named schema: an object keeps its properties."""
        merged = self.merged(data)
        if merged is not None and isinstance(merged.get("properties"), dict):
            return self.object(merged, name)
        return self.schema(data, name, named=True)

    def schema(self, value: object, context: str, *, named: bool = False) -> Schema:
        """Return the normal form of a schema. `context` names an inline object."""
        if value is True or value == {}:
            return AnySchema()
        if not isinstance(value, dict):
            return AnySchema()
        data = cast(dict[str, object], value)
        ref = data.get("$ref")
        if isinstance(ref, str):
            schema: Schema
            key = ref.removeprefix(SCHEMAS_PREFIX)
            if ref.startswith(SCHEMAS_PREFIX) and "/" not in key:
                schema = Ref(self.component(_unescape(key)))
            else:
                schema = self.schema(self.resolve(data), context)
            return self.nullable(schema, data)
        parts = data.get("allOf")
        if isinstance(parts, list):
            items = cast(list[object], parts)
            if len(items) == 1 and not data.get("properties"):
                # A common form to add a description to a reference.
                return self.nullable(self.schema(items[0], context, named=named), data)
            merged = self.merged(data)
            if merged is None:
                return AnySchema()
            return self.nullable(self.schema(merged, context, named=named), data)
        for key in ("oneOf", "anyOf"):
            options = data.get(key)
            if isinstance(options, list) and options:
                found: list[Schema] = []
                for index, option in enumerate(cast(list[object], options)):
                    found.append(self.schema(option, f"{context}Option{index + 1}"))
                return self.nullable(_union(found), data)
        if "const" in data:
            return self.nullable(_enum([data["const"]]), data)
        enum = data.get("enum")
        if isinstance(enum, list) and enum:
            return self.nullable(_enum(cast(list[object], enum)), data)
        types = data.get("type")
        names: list[str]
        if isinstance(types, str):
            names = [types]
        elif isinstance(types, list):
            names = [t for t in cast(list[object], types) if isinstance(t, str)]
        elif "properties" in data or "additionalProperties" in data:
            names = ["object"]
        elif "items" in data:
            names = ["array"]
        else:
            return AnySchema()
        options = [self.typed(data, t, context, named) for t in names]
        return self.nullable(_union(options), data)

    def typed(self, data: dict[str, object], kind: str, context: str, named: bool) -> Schema:
        match kind:
            case "object":
                if isinstance(data.get("properties"), dict) and data["properties"]:
                    if named:
                        return self.object(data, context)
                    name = self.name(context)
                    self.schemas[name] = NamedSchema(name, "", AnySchema())
                    self.schemas[name] = NamedSchema(
                        name, "", self.object(data, name), _text(data.get("description"))
                    )
                    return Ref(name)
                extra = data.get("additionalProperties")
                if isinstance(extra, dict) and extra:
                    return MapSchema(self.schema(cast(object, extra), context + "Value"))
                return MapSchema(AnySchema())
            case "array":
                return ArraySchema(self.schema(data.get("items", {}), context + "Item"))
            case "string" if "contentMediaType" in data and "contentEncoding" not in data:
                # OpenAPI 3.1 gives the media type of binary data in place of a format.
                return ScalarSchema("string", "binary")
            case "string" | "integer" | "number" | "boolean" | "null":
                return ScalarSchema(kind, _text(data.get("format")))
            case _:
                return AnySchema()

    def object(self, data: dict[str, object], name: str) -> ObjectSchema:
        required = data.get("required")
        names = set(cast(list[str], required)) if isinstance(required, list) else set[str]()
        properties: list[Property] = []
        for key, value in cast(dict[str, object], data.get("properties", {})).items():
            schema = self.schema(value, name + type_name(key))
            described = self.resolve(value)
            properties.append(
                Property(key, schema, key in names, _text(described.get("description")))
            )
        return ObjectSchema(tuple(properties))

    def merged(self, data: dict[str, object]) -> dict[str, object] | None:
        """Return the schema with its `allOf` merged, or None if the parts cannot merge."""
        parts = data.get("allOf")
        if not isinstance(parts, list):
            return data
        resolved = [self.resolve(part) for part in cast(list[object], parts)]
        rest = {k: v for k, v in data.items() if k != "allOf"}
        properties: dict[str, object] = {}
        required: list[str] = []
        for item in [*resolved, rest]:
            part = self.merged(item)
            if part is None:
                return None
            if part.get("type") not in (None, "object") or "oneOf" in part or "anyOf" in part:
                return None
            found = part.get("properties", {})
            if isinstance(found, dict):
                properties.update(cast(dict[str, object], found))
            names = part.get("required", [])
            if isinstance(names, list):
                required += [str(r) for r in cast(list[object], names) if str(r) not in required]
        merged: dict[str, object] = {
            **{k: v for k, v in rest.items() if k not in ("properties", "required")},
            "type": "object",
            "properties": properties,
        }
        if required:
            merged["required"] = required
        return merged

    def nullable(self, schema: Schema, data: dict[str, object]) -> Schema:
        if data.get("nullable") is True:
            return _union([schema, ScalarSchema("null")])
        return schema


def _enum(values: list[object]) -> Schema:
    scalars = [v for v in values if v is None or isinstance(v, str | int | float | bool)]
    if not scalars:
        return AnySchema()
    options: list[Schema] = []
    for kind in ("string", "boolean", "integer", "number"):
        matching = tuple(v for v in scalars if _scalar_type(v) == kind)
        if matching:
            options.append(ScalarSchema(cast(ScalarType, kind), None, matching))
    if None in scalars:
        options.append(ScalarSchema("null"))
    return _union(options)


def _scalar_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string" if isinstance(value, str) else "null"


def _union(options: list[Schema]) -> Schema:
    flat: list[Schema] = []
    for option in options:
        for item in option.options if isinstance(option, UnionSchema) else (option,):
            if item not in flat:
                flat.append(item)
    if any(isinstance(o, AnySchema) for o in flat):
        return AnySchema()
    return flat[0] if len(flat) == 1 else UnionSchema(tuple(flat))


def query_value(schema: Schema, spec: ClientSpec, *, item: bool = False) -> bool:
    """Return True if a query parameter can hold a value of the schema.

    A query parameter holds a text: a scalar, an enum value, any value as
    text, or a list of these. An object or a map cannot be a query value.
    """
    match schema:
        case Ref(name):
            return query_value(spec.schema(name).schema, spec, item=item)
        case ScalarSchema() | AnySchema():
            return True
        case ArraySchema(items):
            return not item and query_value(items, spec, item=True)
        case UnionSchema(options):
            return all(query_value(option, spec, item=item) for option in options)
        case MapSchema() | ObjectSchema():
            return False


def is_file(schema: Schema, spec: ClientSpec) -> bool:
    """Return True for binary data (a string with the format `binary`), or a list of it: a file
    of a multipart form."""
    match resolved(schema, spec):
        case ScalarSchema("string", "binary"):
            return True
        case ArraySchema(items):
            return is_file(items, spec)
        case _:
            return False


def accepts(schema: Schema, value: Scalar, spec: ClientSpec) -> bool:
    """Return True if a scalar is a valid value of a schema, or an item of a list schema.

    An integer is also a valid number.
    """
    match schema:
        case Ref(name):
            return accepts(spec.schema(name).schema, value, spec)
        case ScalarSchema(type_, _, enum):
            kind = _scalar_type(value)
            if enum:
                return any(_scalar_type(v) == kind and v == value for v in enum)
            return kind == type_ or (type_ == "number" and kind == "integer")
        case ArraySchema(items):
            return accepts(items, value, spec)
        case UnionSchema(options):
            return any(accepts(option, value, spec) for option in options)
        case AnySchema():
            return True
        case MapSchema() | ObjectSchema():
            return False


def resolved(schema: Schema, spec: ClientSpec) -> Schema:
    """Return a schema without its `Ref`, and without `null` in a union of one other option.

    The result is the schema of a value that is not null.
    """
    seen: set[str] = set()
    while True:
        match schema:
            case Ref(name) if name not in seen:
                seen.add(name)
                schema = spec.schema(name).schema
            case UnionSchema(options):
                others = [o for o in options if not _is_null(o)]
                if len(others) != 1:
                    return schema
                schema = others[0]
            case _:
                return schema


def nullable(schema: Schema, spec: ClientSpec) -> bool:
    """Return True if a value of the schema can be null."""
    seen: set[str] = set()
    while isinstance(schema, Ref) and schema.name not in seen:
        seen.add(schema.name)
        schema = spec.schema(schema.name).schema
    return isinstance(schema, UnionSchema) and any(_is_null(o) for o in schema.options)


def _is_null(schema: Schema) -> bool:
    return isinstance(schema, ScalarSchema) and schema.type == "null"


def object_properties(schema: Schema, spec: ClientSpec) -> tuple[Property, ...] | None:
    """Return the properties of an object schema, or None if the schema is not an object."""
    found = resolved(schema, spec)
    return found.properties if isinstance(found, ObjectSchema) else None


def property_chain(schema: Schema, path: str, spec: ClientSpec) -> list[Property] | None:
    """Return the property of each segment of a path (`address.city`), or None if one is missing."""
    chain: list[Property] = []
    current = schema
    for part in path.split("."):
        properties = object_properties(current, spec)
        found = next((p for p in properties or () if p.name == part), None)
        if found is None:
            return None
        chain.append(found)
        current = found.schema
    return chain


def list_items(schema: Schema, spec: ClientSpec) -> Schema | None:
    """Return the schema of the items of a list schema, or None if the schema is not a list."""
    found = resolved(schema, spec)
    return found.items if isinstance(found, ArraySchema) else None


def walk(schema: Schema) -> Iterator[Schema]:
    """Yield a schema and each schema in it, without following a `Ref`."""
    yield schema
    match schema:
        case ArraySchema(items):
            yield from walk(items)
        case MapSchema(values):
            yield from walk(values)
        case UnionSchema(options):
            for option in options:
                yield from walk(option)
        case ObjectSchema(properties):
            for prop in properties:
                yield from walk(prop.schema)
        case _:
            pass
