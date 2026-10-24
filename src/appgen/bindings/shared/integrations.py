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
from dataclasses import dataclass, field

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

    def request_lines(self) -> list[str]:
        """Return the keys of the request parts object, one on each line."""
        lines: list[str] = []
        for location, key in (("path", "path"), ("query", "query"), ("header", "headers")):
            found = [p for p in self.parameters if p.location == location]
            if found:
                items = ", ".join(f"{ts_key(p.name)}: {p.access}" for p in found)
                lines.append(f"{key}: {{ {items} }},")
        if self.body_type is not None:
            lines.append("body,")
        return lines

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
    credential: str | None
    """`header`, `query`, or `bearer`."""
    credential_name: str | None
    types: list[TsType] = field(default_factory=list[TsType])
    methods: list[TsMethod] = field(default_factory=list[TsMethod])

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
    def examples_json(self) -> str:
        """The example answer of each operation, as JSON text."""
        data = {m.operation_id: m.example for m in self.methods}
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


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
        credential = "bearer" if scheme.type == "http" else scheme.location
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
        secret_env=api.security.env if api.security else None,
        credential=credential,
        credential_name=scheme.parameter if scheme is not None else None,
    )
    taken = {s.name for s in spec.schemas}
    ts.types = sorted((_named(s) for s in spec.schemas), key=lambda t: t.name)
    methods: set[str] = set()
    for operation in spec.operations:
        description = api.operations[operation.id].description or operation.description
        ts.methods.append(_method(api, operation, description, taken, methods))
    return ts


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
