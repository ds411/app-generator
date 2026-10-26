"""The TypeScript clients of the third-party APIs, for the Next.js and the React apps (ADR 0019).

Each API of the definition gets a folder `src/shared/api/<api>/` with
the TypeScript types of the schemas that the selected operations use
(`types.ts`) and a `fetch` client with one method for each operation
(`client.ts`). This module turns the normal form of `appgen.dsl.openapi`
into the parts of these files. Both bindings use it, so that the
clients of the two apps agree.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from appgen.dsl.apis import Api
from appgen.dsl.model import AppDefinition
from appgen.dsl.openapi import (
    AnySchema,
    ArraySchema,
    MapSchema,
    NamedSchema,
    ObjectSchema,
    Operation,
    Ref,
    ScalarSchema,
    Schema,
    UnionSchema,
)
from appgen.gen.naming import camel, constant, kebab, pascal

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# The modules of `src/shared/api/` that the apps have: the folder of an
# API cannot have their names.
_RESERVED_FOLDERS = frozenset(
    {"client", "errors", "http", "http-store", "index", "mock-store", "query", "server"}
    | {"third-party", "types"}
)
# The names of the members of a client class that a method cannot have.
_RESERVED_METHODS = frozenset({"constructor", "http", "timeoutMs"})
# The characters of a path that a regular expression must escape.
_REGEX_SPECIAL = re.compile(r"[\\^$.|?*+()[\]{}/]")
_SCALARS = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}
# The location of each kind of parameter, and its key in the request parts.
_PART_KEYS = (("path", "path"), ("query", "query"), ("header", "headers"), ("cookie", "cookies"))


def exposed_prefix(api: str) -> str:
    """Return the path of the endpoints of an exposed API in the FastAPI app (`expose`)."""
    return "/apis/" + kebab(api)


def ts_key(name: str) -> str:
    """Return a JSON name as a key of a TypeScript object type, in quotes if it needs them."""
    return name if _IDENTIFIER.match(name) else json.dumps(name)


def _doc(text: str | None) -> str | None:
    """Return a text as one line for a JSDoc comment, or None."""
    if not text:
        return None
    return " ".join(text.split()).replace("*/", "*\\/")


@dataclass(frozen=True, slots=True)
class TsProperty:
    """A property of an object schema, as a key of a TypeScript interface."""

    name: str
    type: str
    required: bool
    description: str | None

    def line(self) -> str:
        return f"{ts_key(self.name)}{'' if self.required else '?'}: {self.type};"


@dataclass(frozen=True, slots=True)
class TsType:
    """A named schema, as a TypeScript interface or a type alias."""

    name: str
    description: str | None
    properties: tuple[TsProperty, ...] | None
    """The keys of an interface, or None for a type alias."""
    alias: str = ""


@dataclass(frozen=True, slots=True)
class TsParameter:
    """A parameter of an operation, as a key of the params object of its method."""

    name: str
    location: str
    type: str
    required: bool
    description: str | None

    def line(self) -> str:
        return f"{ts_key(self.name)}{'' if self.required else '?'}: {self.type};"

    @property
    def access(self) -> str:
        """The expression that reads the value from the params object."""
        if _IDENTIFIER.match(self.name):
            return f"params.{self.name}"
        return f"params[{json.dumps(self.name)}]"


@dataclass(frozen=True, slots=True)
class TsMethod:
    """An operation of the document, as a method of the client."""

    name: str
    operation_id: str
    id: str
    """The element ID of the operation."""
    method: str
    path: str
    summary: str | None
    description: str | None
    parameters: tuple[TsParameter, ...]
    params_type: str | None
    """The interface of the params object, or None for an operation without parameters."""
    body_type: str | None
    body_required: bool
    result_type: str | None
    status: str
    example: object
    """The example answer of the document."""
    endpoint: str = ""
    """The path of the endpoint of the FastAPI app for an exposed API, for example
    `/apis/holidays/get-public-holidays`."""
    body_kind: str = "json"
    """`json`, `form`, or `multipart`."""
    answer: str = "json"
    """`json`, `text`, or `binary`."""
    answer_media: str = "application/json"

    @property
    def params_optional(self) -> bool:
        return not any(p.required for p in self.parameters)

    @property
    def path_pattern(self) -> str:
        """A TypeScript regular expression that matches the end of the path of a request."""
        parts = re.split(r"(\{[^}]+\})", self.path)
        text = "".join(
            "[^/]+" if p.startswith("{") else _REGEX_SPECIAL.sub(r"\\\g<0>", p) for p in parts
        )
        return f"/{text}$/"

    @property
    def mock_status(self) -> int:
        """The status of the example answer, 200 for a `default` answer."""
        return int(self.status) if self.status.isdigit() else 200

    @property
    def example_json(self) -> str:
        """The example answer, as JSON text."""
        return json.dumps(self.example, indent=2, ensure_ascii=False)

    def arguments(self) -> str:
        """Return the parameters of the method."""
        args: list[str] = []
        if self.params_type is not None:
            default = " = {}" if self.params_optional else ""
            args.append(f"params: {self.params_type}{default}")
        if self.body_type is not None:
            optional = "" if self.body_required else "?"
            args.append(f"body{optional}: {self.body_type}")
        return ", ".join(args)

    @property
    def returns(self) -> str:
        return self.result_type or "void"

    def request_lines(self, exposed: bool = False) -> list[str]:
        """Return the keys of the request parts object, one on each line.

        The endpoint of an exposed API (`exposed`) takes all parameters in its query.
        """
        lines: list[str] = []
        if exposed and self.parameters:
            items = ", ".join(f"{ts_key(p.name)}: {p.access}" for p in self.parameters)
            lines.append(f"query: {{ {items} }},")
        for location, key in _PART_KEYS:
            found = [p for p in self.parameters if p.location == location]
            if found and not exposed:
                items = ", ".join(f"{ts_key(p.name)}: {p.access}" for p in found)
                lines.append(f"{key}: {{ {items} }},")
        if self.body_type is not None:
            match self.body_kind:
                case "form":
                    lines.append("form: body,")
                case "multipart":
                    lines.append("form: body,")
                    lines.append("multipart: true,")
                case _:
                    lines.append("body,")
        if self.answer != "json" and self.result_type is not None:
            lines.append(f"answer: {json.dumps(self.answer)},")
            lines.append(f"accept: {json.dumps(self.answer_media)},")
        return lines

    @property
    def mock_media(self) -> str | None:
        """The content type of the mock answer of a text or a binary answer, or None for JSON."""
        if self.result_type is None or self.answer == "json":
            return None
        if "*" not in self.answer_media:
            return self.answer_media
        return "text/plain" if self.answer == "text" else "application/octet-stream"

    @property
    def cookie_parameter(self) -> str | None:
        """The name of the first cookie parameter, or None."""
        return next((p.name for p in self.parameters if p.location == "cookie"), None)

    def doc_lines(self) -> list[str]:
        """Return the lines of the JSDoc comment of the method, without the comment markers."""
        lines = [self.summary or self.description or f"Call the operation {self.operation_id}."]
        if self.summary and self.description and self.description != self.summary:
            lines += ["", self.description]
        lines += ["", f"`{self.method.upper()} {self.path}`"]
        return lines


@dataclass(slots=True)
class TsApi:
    """A third-party API, as a folder of `src/shared/api/`."""

    name: str
    id: str
    folder: str
    """The folder in `src/shared/api/`, for example `exchange-rates`."""
    title: str
    description: str | None
    client: str
    """The class name of the client, for example `HolidaysClient`."""
    factory: str
    """The function that creates a client with the settings, for example `holidaysClient`."""
    base_url_const: str
    base_url: str
    url_env: str
    secret_env: str | None
    """The environment variable of the API key, the token, or the client secret."""
    credential: str | None
    """`header`, `query`, `bearer`, `oauth2` (the client credentials flow), or `user` (the
    authorization code flow: the token of a user, ADR 0033)."""
    credential_name: str | None
    types: list[TsType] = field(default_factory=list[TsType])
    methods: list[TsMethod] = field(default_factory=list[TsMethod])
    exposed: bool = False
    """True: the FastAPI app has an endpoint for each operation (`apis.<api>.expose`)."""
    prefix: str = ""
    """The path of the endpoints of an exposed API in the FastAPI app."""
    client_id_env: str | None = None
    """OAuth 2.0: the environment variable of the client ID."""
    token_url: str = ""
    """OAuth 2.0: the token URL of the flow. A path is under the base URL."""
    scopes: tuple[str, ...] = ()
    """OAuth 2.0: the scopes of the access token."""
    authorization_url: str = ""
    """The authorization code flow: the page where the user allows the access."""
    refresh_url: str = ""
    """The authorization code flow: the URL that gives a new access token for a refresh token."""

    @property
    def user(self) -> bool:
        """True for the authorization code flow: the client sends the token of a user."""
        return self.credential == "user"

    @property
    def connection_name(self) -> str:
        """The name of the API in the paths of the connections, for example `exchange-rates`."""
        return kebab(self.name)

    @property
    def client_for(self) -> str:
        """The function that returns a client with the token of a user, for example
        `calendarClientFor`."""
        return self.factory + "For"

    @property
    def cookie_method(self) -> TsMethod | None:
        """The first method with a cookie parameter, or None."""
        return next((m for m in self.methods if m.cookie_parameter), None)

    @property
    def browser(self) -> bool:
        """True if a browser can call the API: it has no secret and no cookie parameter."""
        return self.secret_env is None and self.cookie_method is None

    @property
    def server_reason(self) -> str:
        """Why only a server can call the API, as the end of a sentence."""
        if self.secret_env is not None:
            return f"has a secret (`{self.secret_env}`), and a browser app cannot keep a secret"
        method = self.cookie_method
        if method is None:
            return ""
        return (
            f"sends the cookie parameter `{method.cookie_parameter}` in the operation "
            f"`{method.operation_id}`, and a browser cannot set a cookie for another site"
        )

    @property
    def browser_env(self) -> str:
        """The build variable of the base URL in a Vite app, which the browser code can read."""
        return "VITE_" + self.url_env

    @property
    def type_names(self) -> list[str]:
        return [t.name for t in self.types] + [m.params_type for m in self.methods if m.params_type]

    def used_types(self) -> list[str]:
        """Return the names of the types that the methods of the client use, sorted."""
        text = " ".join(
            t or "" for m in self.methods for t in (m.params_type, m.body_type, m.result_type)
        )
        found = set(re.findall(r"\b[A-Z][A-Za-z0-9]*\b", text))
        return sorted(found & set(self.type_names))

    def credentials(self) -> str | None:
        """Return the HTTP option of the secret, or None for an API without a secret."""
        if self.credential == "bearer":
            return "headers: options.secret ? { Authorization: `Bearer ${options.secret}` } : {},"
        if self.credential == "header":
            key = ts_key(self.credential_name or "")
            return f"headers: options.secret ? {{ {key}: options.secret }} : {{}},"
        if self.credential == "query":
            key = ts_key(self.credential_name or "")
            return f"query: options.secret ? {{ {key}: options.secret }} : {{}},"
        return None

    @property
    def token_const(self) -> str:
        """The constant of the token URL of an API with OAuth 2.0."""
        return self.base_url_const.removesuffix("_BASE_URL") + "_TOKEN_URL"

    @property
    def examples_json(self) -> str:
        """The example answer of each operation, as JSON text."""
        data = {m.operation_id: m.example for m in self.methods}
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


def ts_features(apis: Mapping[str, TsApi]) -> frozenset[str]:
    """Return what the HTTP client of the apps needs for the methods of these APIs: `form`,
    `multipart`, `text`, `binary`, `cookie`, `oauth2`, and `user`."""
    found: set[str] = set()
    for api in apis.values():
        if api.credential in ("oauth2", "user"):
            found.add(api.credential)
        for m in api.methods:
            if m.body_type is not None and m.body_kind != "json":
                found.add(m.body_kind)
            if m.result_type is not None and m.answer != "json":
                found.add(m.answer)
            if m.cookie_parameter:
                found.add("cookie")
    return frozenset(found)


def ts_connections(apis: Mapping[str, TsApi]) -> list[TsApi]:
    """Return the APIs with the authorization code flow (ADR 0033): a user connects an account
    of each one."""
    return [api for api in apis.values() if api.user]


def ts_apis(definition: AppDefinition) -> dict[str, TsApi]:
    """Return the model of each API of a definition, by API name."""
    return {name: _api(name, api) for name, api in definition.apis.items()}


def _api(name: str, api: Api) -> TsApi:
    spec = api.spec
    document = api.openapi
    scheme = (
        document.security_schemes.get(api.security.scheme)
        if document is not None and api.security is not None
        else None
    )
    credential: str | None = None
    if scheme is not None:
        credential = {"http": "bearer", "oauth2": "oauth2"}.get(scheme.type, scheme.location)
    code = scheme.authorization_code if scheme is not None and api.user_flow else None
    if code is not None:
        credential = "user"
    security = api.security
    folder = kebab(name)
    ts = TsApi(
        name=name,
        id=api.id,
        folder=folder + "-api" if folder in _RESERVED_FOLDERS else folder,
        title=api.label,
        description=_doc(api.description),
        client=pascal(name) + "Client",
        factory=camel(name) + "Client",
        base_url_const=constant(name) + "_BASE_URL",
        base_url=document.base_url if document is not None else "",
        url_env=api.base_url_env,
        secret_env=security.secret_env if security else None,
        credential=credential,
        credential_name=scheme.parameter if scheme is not None else None,
        exposed=api.expose,
        prefix=exposed_prefix(name) if api.expose else "",
        client_id_env=security.client_id_env if security else None,
        token_url=(scheme.token_url or "") if scheme is not None else "",
        scopes=tuple(security.scopes) if security else (),
    )
    if code is not None:
        ts.token_url = code.token_url
        ts.authorization_url = code.authorization_url
        ts.refresh_url = code.refresh_url or code.token_url
    taken = {s.name for s in spec.schemas}
    ts.types = ts_types(spec.schemas)
    methods: set[str] = set()
    for operation in spec.operations:
        description = api.operations[operation.id].description or operation.description
        method = _method(api, operation, description, taken, methods)
        if api.expose:
            method = replace(method, endpoint=f"{ts.prefix}/{kebab(operation.id)}")
        ts.methods.append(method)
    return ts


def ts_types(schemas: Iterable[NamedSchema]) -> list[TsType]:
    """Return the TypeScript types of named schemas of the normal form, sorted by name."""
    return sorted((_named(s) for s in schemas), key=lambda t: t.name)


def _named(named: NamedSchema) -> TsType:
    description = _doc(named.description)
    schema = named.schema
    if not isinstance(schema, ObjectSchema):
        return TsType(named.name, description, None, ts_type(schema))
    properties = tuple(
        TsProperty(p.name, ts_type(p.schema), p.required, _doc(p.description))
        for p in schema.properties
    )
    return TsType(named.name, description, properties)


def _method(
    api: Api, operation: Operation, description: str | None, taken: set[str], methods: set[str]
) -> TsMethod:
    name = camel(operation.id)
    base = name
    number = 2
    while name in methods or name in _RESERVED_METHODS:
        name = f"{base}{number}"
        number += 1
    methods.add(name)
    params_type = None
    if operation.parameters:
        params_type = _unique(pascal(operation.id) + "Params", taken)
    return TsMethod(
        name=name,
        operation_id=operation.id,
        id=api.operations[operation.id].id,
        method=operation.method,
        path=operation.path,
        summary=_doc(operation.summary),
        description=_doc(description),
        parameters=tuple(
            TsParameter(p.name, p.location, ts_type(p.schema), p.required, _doc(p.description))
            for p in operation.parameters
        ),
        params_type=params_type,
        body_type=ts_type(operation.body) if operation.body is not None else None,
        body_required=operation.body_required,
        result_type=ts_type(operation.result) if operation.result is not None else None,
        status=operation.status,
        example=operation.example,
        body_kind=operation.body_kind,
        answer=operation.answer,
        answer_media=operation.answer_media,
    )


def _unique(name: str, taken: set[str]) -> str:
    result = name
    number = 2
    while result in taken:
        result = f"{name}{number}"
        number += 1
    taken.add(result)
    return result


def _union_parts(schema: Schema) -> list[str]:
    """Return the members of the union type of a schema, or the type as one member."""
    match schema:
        case UnionSchema(options):
            return [p for option in options for p in _union_parts(option)]
        case ScalarSchema(_, _, enum) if enum:
            return [json.dumps(v, ensure_ascii=False) for v in enum]
        case _:
            return [ts_type(schema)]


def ts_type(schema: Schema) -> str:
    """Return the TypeScript type of a schema of the normal form."""
    match schema:
        case Ref(name):
            return name
        case ScalarSchema(kind, _, enum) if enum:
            return " | ".join(json.dumps(v, ensure_ascii=False) for v in enum)
        case ScalarSchema("string", "binary"):
            return "Blob"
        case ScalarSchema(kind):
            return _SCALARS.get(kind, "null")
        case ArraySchema(items):
            inner = ts_type(items)
            return f"({inner})[]" if " | " in inner else f"{inner}[]"
        case MapSchema(values):
            return f"Record<string, {ts_type(values)}>"
        case UnionSchema(options):
            parts: list[str] = []
            for part in (p for option in options for p in _union_parts(option)):
                if part not in parts:
                    parts.append(part)
            return " | ".join(parts)
        case AnySchema() | ObjectSchema():
            return "unknown"
