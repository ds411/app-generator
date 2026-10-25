"""The clients of the third-party APIs of the FastAPI app (ADR 0019).

For each API of the definition, the binding writes a package
`app/integrations/<api>/` with the Pydantic models of the schemas and an
async `httpx` client with one method for each selected operation. This
module turns the normal form of `appgen.dsl.openapi` into the Python
source lines of these files. The lines are in the format of the Ruff
formatter.
"""

import json
import keyword
import re
from dataclasses import dataclass, field
from typing import cast

from appgen.bindings.fastapi.pysource import LINE_LENGTH, call, from_import
from appgen.bindings.shared.integrations import exposed_prefix
from appgen.dsl.apis import Api
from appgen.dsl.model import AppDefinition
from appgen.dsl.openapi import (
    AnySchema,
    ArraySchema,
    ClientSpec,
    MapSchema,
    NamedSchema,
    ObjectSchema,
    Operation,
    Ref,
    ScalarSchema,
    Schema,
    UnionSchema,
    sample,
)
from appgen.gen.naming import constant, kebab, pascal, snake
from appgen.gen.render import GenerationError

# Names that a field or a parameter cannot have: they hide a name of
# Pydantic, of the client, or of a module that the generated code uses.
_RESERVED = frozenset(
    {"construct", "copy", "dict", "dt", "fields", "json", "self", "schema", "typing"}
    | {"uuid", "validate", "pydantic", "httpx", "body", "client"}
)
_SCALARS = {
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "null": "None",
}
_FORMATS = {"date": "dt.date", "date-time": "dt.datetime", "uuid": "uuid.UUID"}
# The local names of the generated tests: a parameter of a method cannot
# have them, because the tests give each argument a variable of its name.
_TEST_NAMES = frozenset({"adapter", "error", "expected", "requests", "result", "transport"})


def python_name(name: str, taken: set[str], reserved: frozenset[str] = frozenset()) -> str:
    """Return a safe snake case name for a JSON name, and add it to `taken`.

    A keyword, a name of `_RESERVED` or of `reserved`, and a name with the
    prefix of the Pydantic attributes get a trailing `_`.
    """
    base = snake(name) or "value"
    if base[0].isdigit():
        base = "n_" + base
    if (
        keyword.iskeyword(base)
        or base in _RESERVED
        or base in reserved
        or base.startswith("model_")
    ):
        base += "_"
    result = base
    number = 2
    while result in taken:
        result = f"{base}_{number}"
        number += 1
    taken.add(result)
    return result


def _docstring(text: str | None) -> str | None:
    """Return a text as one line for a docstring, or None."""
    if not text:
        return None
    line = " ".join(text.split()).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if line.endswith('"'):
        line += " "
    return line


@dataclass(slots=True)
class PyApiField:
    """A property of an object schema, as a field of a Pydantic model."""

    attr: str
    name: str
    type: str
    required: bool
    description: str | None

    def line(self, query: bool = False) -> str:
        """Return the declaration of the field in the model.

        A field of a query model has an `alias`: FastAPI reads the query
        parameter of that name.
        """
        type_ = self.type if self.required else _optional(self.type)
        args: list[str] = []
        if self.attr != self.name:
            alias = json.dumps(self.name, ensure_ascii=False)
            if query:
                args.append(f"alias={alias}")
            else:
                args += [f"validation_alias={alias}", f"serialization_alias={alias}"]
        if not self.required:
            args.insert(0, "default=None")
        if not args:
            return f"{self.attr}: {type_}"
        if args == ["default=None"]:
            return f"{self.attr}: {type_} = None"
        return call(f"{self.attr}: {type_} = ", "pydantic.Field", args)


@dataclass(slots=True)
class PyApiModel:
    """A named schema, as a Pydantic model or a type alias."""

    name: str
    description: str | None
    fields: list[PyApiField] | None
    """The fields of a model, or None for a type alias."""
    alias: str = ""
    """The type of a type alias."""
    query: bool = False
    """True for the model of the query parameters of an endpoint."""

    def lines(self) -> list[str]:
        if self.fields is None:
            return [_wrap_type(f"type {self.name} = ", self.alias)]
        lines = [f"class {self.name}(pydantic.BaseModel):"]
        lines.append(f'    """{self.description or f"The schema {self.name}."}"""')
        lines.append("")
        if self.query:
            config = "pydantic.ConfigDict(validate_by_name=True, validate_by_alias=True)"
            lines.append(f"    model_config = {config}")
        else:
            lines.append("    model_config = pydantic.ConfigDict(")
            lines.append(
                "        validate_by_name=True, validate_by_alias=True, serialize_by_alias=True"
            )
            lines.append("    )")
        if self.fields:
            lines.append("")
        for f in self.fields:
            lines.append(f"    {f.line(self.query)}")
            if f.description:
                lines.append(f'    """{f.description}"""')
        return lines


@dataclass(slots=True)
class PySample:
    """A valid value of a type, for the generated tests."""

    value: object
    """The JSON value."""
    adapter: str | None
    """The type that validates the JSON value, if the value is not a plain literal."""

    def line(self, variable: str, indent: int = 4) -> str:
        """Return the statement that gives the value to a variable, in the format of Ruff."""
        if self.adapter is None:
            return _formatted(self.value, f"{variable} = ", "", indent)
        head = f"{variable} = pydantic.TypeAdapter({self.adapter}).validate_python("
        line = head + _literal(self.value) + ")"
        if indent + len(line) <= LINE_LENGTH:
            return line
        value = _formatted(self.value, "", "", indent + 4)
        return f"{head}\n{' ' * (indent + 4)}{value}\n{' ' * indent})"


@dataclass(slots=True)
class PyApiParameter:
    attr: str
    name: str
    location: str
    type: str
    required: bool
    description: str | None
    sample: PySample

    def declaration(self) -> str:
        if self.required:
            return f"{self.attr}: {self.type}"
        return f"{self.attr}: {_optional(self.type)} = None"


@dataclass(slots=True)
class PyApiMethod:
    """An operation of the document, as a method of the client."""

    name: str
    operation_id: str
    id: str
    """The element ID of the operation."""
    method: str
    path: str
    summary: str | None
    description: str | None
    parameters: list[PyApiParameter]
    body_type: str | None
    body_required: bool
    body_sample: PySample | None
    result_type: str | None
    status: str
    example: str
    """The example answer as JSON text."""
    endpoint_path: str = ""
    """The path of the endpoint of an exposed API, after the prefix, for example `/get-pets`."""
    endpoint_id: str = ""
    """The operation ID of the endpoint in the OpenAPI document of the app."""
    query_model: PyApiModel | None = None
    """The model of the query parameters of the endpoint, or None for an operation without
    parameters."""

    @property
    def path_pattern(self) -> str:
        """A regular expression of the path, for the mock transport."""
        parts = re.split(r"(\{[^}]+\})", self.path)
        return "^" + "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts) + "$"

    @property
    def status_code(self) -> int:
        return int(self.status) if self.status.isdigit() else 200

    @property
    def adapter(self) -> str:
        return f"_{constant(self.name)}_RESULT"

    @property
    def body_adapter(self) -> str:
        return f"_{constant(self.name)}_BODY"

    def signature(self) -> str:
        args = ["self"]
        required = [p for p in self.parameters if p.required]
        optional = [p for p in self.parameters if not p.required]
        args += [p.declaration() for p in required]
        if self.body_type is not None and self.body_required:
            args.append(f"body: {self.body_type}")
        keyword_only = [p.declaration() for p in optional]
        if self.body_type is not None and not self.body_required:
            keyword_only.insert(0, f"body: {_optional(self.body_type)} = None")
        if keyword_only:
            args += ["*", *keyword_only]
        result = self.result_type or "None"
        return call("async def ", self.name, args, 4, f" -> {result}:")

    def docstring(self) -> list[str]:
        title = self.summary or self.description or f"Call the operation {self.operation_id}."
        lines = [f'"""{title}', "", f"{self.method.upper()} {self.path}"]
        for p in self.parameters:
            if p.description:
                lines.append(f"`{p.attr}`: {p.description}")
        lines.append('"""')
        return lines

    def body_lines(self) -> list[str]:
        """Return the statements of the method."""
        args = [json.dumps(self.method.upper()), json.dumps(self.path)]
        for location, keyword_ in (("path", "path"), ("query", "query"), ("header", "headers")):
            found = [p for p in self.parameters if p.location == location]
            if found:
                items = ", ".join(f"{json.dumps(p.name)}: {p.attr}" for p in found)
                args.append(f"{keyword_}={{{items}}}")
        if self.body_type is not None:
            dump = f'{self.body_adapter}.dump_python(body, mode="json", by_alias=True)'
            if not self.body_required:
                dump += " if body is not None else None"
            args.append(f"body={dump}")
        if self.result_type is None:
            return [call("await ", "self.request", args, 8)]
        return [
            call("data = await ", "self.request", args, 8),
            f"return {self.adapter}.validate_python(data)",
        ]

    def sample_lines(self, indent: int = 4) -> list[str]:
        """Return the statements of the tests that give each argument of `test_call` a value."""
        lines = [p.sample.line(p.attr, indent) for p in self.parameters if p.required]
        if self.body_sample is not None:
            lines.append(self.body_sample.line("body", indent))
        return lines

    def test_call(self, prefix: str = "", indent: int = 8) -> str:
        """Return a call of the method with the variables of `sample_lines`, for the tests."""
        args = [p.attr for p in self.parameters if p.required]
        if self.body_sample is not None:
            args.append("body")
        return call(prefix, f"client.{self.name}", args, indent)

    def path_check(self) -> str:
        """Return the assertion of the test that the request has the path of the operation."""
        return call("assert ", "re.match", [f'r"{self.path_pattern}"', "requests[0].url.path"])

    def route(self) -> str:
        """Return the route decorator of the endpoint of an exposed API."""
        args = [json.dumps(self.endpoint_path)]
        if self.result_type is None:
            args.append("status_code=204")
        args += [f"operation_id={json.dumps(self.endpoint_id)}", "responses=problem_responses(502)"]
        return call("@router.", self.method, args, 0)

    def endpoint_signature(self, dependency: str) -> str:
        """Return the signature of the endpoint function. `dependency` is the client type."""
        args = [f"client: {dependency}"]
        if self.query_model is not None:
            args.append(f"query: Annotated[{self.query_model.name}, Query()]")
        if self.body_type is not None:
            type_ = self.body_type if self.body_required else _optional(self.body_type)
            default = "" if self.body_required else " = None"
            args.append(f"body: Annotated[{type_}, Body()]{default}")
        return call("async def ", self.name, args, 0, f" -> {self.result_type or 'None'}:")

    def endpoint_lines(self) -> list[str]:
        """Return the statements of the endpoint function: the call of the client method."""
        args = [f"query.{p.attr}" for p in self.parameters if p.required]
        if self.body_type is not None and self.body_required:
            args.append("body")
        if self.body_type is not None and not self.body_required:
            args.append("body=body")
        args += [f"{p.attr}=query.{p.attr}" for p in self.parameters if not p.required]
        prefix = "return await " if self.result_type else "await "
        return [
            "try:",
            "    " + call(prefix, f"client.{self.name}", args, 8),
            "except API_ERRORS as error:",
            "    raise bad_gateway(client, error) from error",
        ]

    def endpoint_request(self, prefix: str, url: str, client: str = "client") -> str:
        """Return the request of the test of the endpoint, with the samples of the arguments."""
        args = [json.dumps(self.method.upper()), json.dumps(url)]
        if any(p.required for p in self.parameters):
            args.append("params=params")
        if self.body_sample is not None:
            args.append("json=body")
        return call(prefix, f"{client}.request", args, 4)

    def endpoint_sample_lines(self, indent: int = 4) -> list[str]:
        """Return the statements of the test that give the query and the body of a request."""
        lines: list[str] = []
        # A query parameter has a value: a parameter of any type gets a text.
        params = {
            p.name: "string" if p.sample.value is None else p.sample.value
            for p in self.parameters
            if p.required
        }
        if params:
            lines.append(_formatted(params, "params: dict[str, Any] = ", "", indent))
        if self.body_sample is not None:
            lines.append(_formatted(self.body_sample.value, "body: Any = ", "", indent))
        return lines


@dataclass(slots=True)
class PyApi:
    """A third-party API, as a package of the app."""

    name: str
    id: str
    module: str
    """The name of the package, for example `holidays`."""
    title: str
    description: str | None
    client: str
    """The class name of the client, for example `HolidaysClient`."""
    base_url: str
    url_setting: str
    """The attribute of the settings with the base URL, for example `holidays_api_url`."""
    url_env: str
    secret_setting: str | None
    secret_env: str | None
    credential: str | None
    """`header`, `query`, or `bearer`."""
    credential_name: str | None
    """The name of the header or the query parameter of an API key."""
    models: list[PyApiModel] = field(default_factory=list[PyApiModel])
    methods: list[PyApiMethod] = field(default_factory=list[PyApiMethod])
    expose: bool = False
    """True: the app has an endpoint for each operation (`apis.<api>.expose`)."""
    prefix: str = ""
    """The path of the endpoints of an exposed API, for example `/apis/exchange-rates`."""

    @property
    def dependency(self) -> str:
        return f"get_{self.module}_client"

    def construction(self) -> str:
        """Return the statement of the dependency that creates the client from the settings."""
        args = [f"settings.{self.url_setting}"]
        if self.secret_setting:
            args.append(f"settings.{self.secret_setting}")
        return call("client = ", self.client, args)

    @property
    def mock_dependency(self) -> str:
        return f"mock_{self.module}_client"

    @property
    def dependency_type(self) -> str:
        return f"{self.client}Dep"

    @property
    def secret_arg(self) -> str:
        return "token" if self.credential == "bearer" else "api_key"

    @property
    def model_names(self) -> list[str]:
        return [m.name for m in self.models]

    def used_models(self, text: str) -> list[str]:
        """Return the names of the models that a text of type expressions uses, sorted."""
        found = set(re.findall(r"\b[A-Z][A-Za-z0-9]*\b", text))
        return sorted(found & set(self.model_names))

    @property
    def client_types(self) -> str:
        """All type expressions of the methods, to find their imports."""
        types: list[str] = []
        for m in self.methods:
            types += [p.type for p in m.parameters]
            types += [t for t in (m.body_type, m.result_type) if t]
        return " ".join(types)

    def model_imports(self) -> list[str]:
        """Return the import lines of `models.py`."""
        types = [m.alias for m in self.models] + [
            f.type for m in self.models for f in (m.fields or [])
        ]
        return ["import pydantic", *_std_imports(" ".join(types))]

    def client_imports(self) -> list[str]:
        """Return the import lines of `client.py`."""
        text = self.client_types
        lines = [
            "from collections.abc import AsyncIterator",
            "from typing import Annotated",
            "from fastapi import Depends, Request",
            "from app.core.config import Settings",
            "from app.integrations.http import DEFAULT_TIMEOUT, ApiClient",
            *_std_imports(text),
        ]
        if self.methods:
            lines += ["import httpx", "import pydantic"]
        else:
            lines.append("import httpx")
        models = self.used_models(text)
        if models:
            lines.append(from_import(f"app.integrations.{self.module}.models", set(models)))
        return lines

    def router_imports(self) -> list[str]:
        """Return the import lines of `router.py`, the endpoints of an exposed API."""
        types = [m.result_type or "" for m in self.methods]
        types += [m.body_type or "" for m in self.methods]
        types += [f.type for m in self.methods if m.query_model for f in m.query_model.fields or []]
        text = " ".join(types)
        fastapi = {"APIRouter"}
        if any(m.query_model for m in self.methods):
            fastapi.add("Query")
        if any(m.body_type for m in self.methods):
            fastapi.add("Body")
        lines = [
            from_import("fastapi", fastapi),
            "from app.core.errors import problem_responses",
            "from app.integrations.endpoints import API_ERRORS, bad_gateway",
            f"from app.integrations.{self.module}.client import {self.dependency_type}",
            *_std_imports(text),
        ]
        if len(fastapi) > 1:
            lines.append("from typing import Annotated")
        if any(m.query_model for m in self.methods) or "pydantic." in text:
            lines.append("import pydantic")
        models = self.used_models(text)
        if models:
            lines.append(from_import(f"app.integrations.{self.module}.models", set(models)))
        return lines

    def endpoint_test_imports(self) -> list[str]:
        """Return the import lines of the test of the endpoints of an exposed API."""
        results = " ".join(m.result_type for m in self.methods if m.result_type)
        mocks = {"FAILURES", "EXAMPLES"} if results else {"FAILURES"}
        lines = [
            "import pytest",
            "from httpx import AsyncClient",
            from_import("tests.integrations.mocks", mocks),
            "from tests.problems import assert_problem",
            *_std_imports(results),
        ]
        if any(m.endpoint_sample_lines() for m in self.methods):
            lines.append("from typing import Any")
        if results:
            lines.append("import pydantic")
        models = self.used_models(results)
        if models:
            lines.append(from_import(f"app.integrations.{self.module}.models", set(models)))
        return lines

    def test_imports(self) -> list[str]:
        """Return the import lines of the test of the client."""
        samples = [line for m in self.methods for line in m.sample_lines()]
        results = [m.result_type for m in self.methods if m.result_type]
        text = " ".join(samples + results)
        mocks = {"mock_transport", "EXAMPLES"} if results else {"mock_transport"}
        lines = [
            "import re",
            "import httpx",
            "import pytest",
            "from app.integrations.http import DEFAULT_TIMEOUT, ApiError",
            f"from app.integrations.{self.module}.client import {self.client}",
            from_import("tests.integrations.mocks", mocks),
            *_std_imports(text),
        ]
        if "pydantic." in text or results:
            lines.append("import pydantic")
        models = self.used_models(text)
        if models:
            lines.append(from_import(f"app.integrations.{self.module}.models", set(models)))
        return lines

    @property
    def param(self) -> str:
        """The name of the parameter that gives the client to a custom operation."""
        taken = ("id", "params", "record", "result", "session")
        return self.module + "_client" if self.module in taken else self.module

    @property
    def test_url(self) -> str:
        return f"https://{self.module.replace('_', '-')}.test"

    def _arguments(self) -> list[str]:
        args = [json.dumps(self.test_url)]
        if self.credential:
            args.append('"secret"')
        return args

    def mock_construction(self) -> str:
        """Return the statement of the mock dependency that creates the client."""
        name = json.dumps(self.name)
        transport = f"transport=mock_transport({name})"
        if self.expose:
            transport = f"transport=mock_transport({name}, status=FAILURES.get({name}))"
        return call("client = ", self.client, [*self._arguments(), transport])

    def test_construction(self) -> str:
        """Return the statement of the tests that creates the client."""
        return call("return ", self.client, [*self._arguments(), "transport=transport"])

    def route_lines(self) -> list[str]:
        """Return the routes of the mock transport, one tuple on each line."""
        lines: list[str] = []
        for m in self.methods:
            args = [
                json.dumps(m.method.upper()),
                f'r"{m.path_pattern}"',
                str(m.status_code),
                json.dumps(m.operation_id),
            ]
            lines.append(call("", "", args, 8, ","))
        return lines

    @property
    def examples_json(self) -> str:
        """The example answer of each operation, as JSON text for the tests."""
        data = {m.operation_id: json.loads(m.example) for m in self.methods}
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


def python_apis(definition: AppDefinition) -> dict[str, PyApi]:
    """Return the model of each API of a definition, by API name."""
    return {name: _api(name, api) for name, api in definition.apis.items()}


def mocks_imports(apis: dict[str, PyApi]) -> list[str]:
    """Return the import lines of `tests/integrations/mocks.py`."""
    lines = [
        "import json",
        "import re",
        "from collections.abc import AsyncIterator",
        "from pathlib import Path",
        "import httpx",
    ]
    for api in apis.values():
        lines.append(f"from app.integrations.{api.module}.client import {api.client}")
    return lines


def _api(name: str, api: Api) -> PyApi:
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
    module = snake(name)
    py = PyApi(
        name=name,
        id=api.id,
        module=module,
        title=api.label,
        description=_docstring(api.description),
        client=pascal(name) + "Client",
        base_url=document.base_url if document is not None else "",
        url_setting=api.base_url_env.lower(),
        url_env=api.base_url_env,
        secret_setting=api.security.env.lower() if api.security else None,
        secret_env=api.security.env if api.security else None,
        credential=credential,
        credential_name=scheme.parameter if scheme is not None else None,
    )
    types = _Types(spec.schemas)
    for named in spec.schemas:
        py.models.append(types.model(named))
    for operation in spec.operations:
        description = api.operations[operation.id].description or operation.description
        py.methods.append(_method(api, operation, description, types, spec))
    if api.expose and py.methods:
        _expose(py, spec, types)
    py.models += types.aliases
    py.models.sort(key=lambda m: m.name)
    return py


def _expose(py: PyApi, spec: ClientSpec, types: _Types) -> None:
    """Give each method of an exposed API its endpoint: the path and the query model."""
    py.expose = True
    py.prefix = exposed_prefix(py.name)
    paths: dict[str, str] = {}
    for method, operation in zip(py.methods, spec.operations, strict=True):
        method.endpoint_path = "/" + kebab(operation.id)
        if method.endpoint_path in paths:
            raise GenerationError(
                f"The operations '{paths[method.endpoint_path]}' and '{operation.id}' of the "
                f"API '{py.name}' give the same endpoint {py.prefix}{method.endpoint_path}."
            )
        paths[method.endpoint_path] = operation.id
        method.endpoint_id = f"{py.module}_{method.name.rstrip('_')}"
        if not operation.parameters:
            continue
        fields: list[PyApiField] = []
        for parameter, p in zip(operation.parameters, method.parameters, strict=True):
            context = pascal(operation.id) + pascal(parameter.name)
            type_ = types.type(parameter.schema, context, query=True)
            fields.append(PyApiField(p.attr, p.name, type_, p.required, p.description))
        name = types.unique(pascal(operation.id) + "Query")
        method.query_model = PyApiModel(
            name, f"The query parameters of the endpoint of `{operation.id}`.", fields, query=True
        )


def _method(
    api: Api, operation: Operation, description: str | None, types: _Types, spec: ClientSpec
) -> PyApiMethod:
    taken: set[str] = set()
    parameters: list[PyApiParameter] = []
    base = pascal(operation.id)
    for p in operation.parameters:
        type_ = types.type(p.schema, base + pascal(p.name))
        parameters.append(
            PyApiParameter(
                attr=python_name(p.name, taken, _TEST_NAMES),
                name=p.name,
                location=p.location,
                type=type_,
                required=p.required,
                description=_docstring(p.description),
                sample=_typed_sample(p.schema, type_, spec, types),
            )
        )
    body_type = types.type(operation.body, base + "Body") if operation.body else None
    body_sample = None
    if operation.body is not None and body_type is not None:
        body_sample = _typed_sample(operation.body, body_type, spec, types)
    return PyApiMethod(
        name=python_name(operation.id, {"request", "aclose"}),
        operation_id=operation.id,
        id=api.operations[operation.id].id,
        method=operation.method,
        path=operation.path,
        summary=_docstring(operation.summary),
        description=_docstring(description),
        parameters=parameters,
        body_type=body_type,
        body_required=operation.body_required,
        body_sample=body_sample,
        result_type=types.type(operation.result, base + "Result") if operation.result else None,
        status=operation.status,
        example=json.dumps(operation.example, ensure_ascii=False),
    )


def _typed_sample(schema: Schema, type_: str, spec: ClientSpec, types: _Types) -> PySample:
    """Return a valid value of a type, for the generated tests."""
    value = sample(schema, spec)
    if re.search(r"\b(dt|uuid)\.", type_) or any(
        n in types.models for n in re.findall(r"\w+", type_)
    ):
        return PySample(value, type_)
    return PySample(value, None)


class _Types:
    """Write the Python type of each schema, and collect the type aliases of inline enums."""

    def __init__(self, schemas: tuple[NamedSchema, ...]) -> None:
        self.names = {s.name for s in schemas}
        self.models = {s.name for s in schemas if isinstance(s.schema, ObjectSchema)}
        self.aliases: list[PyApiModel] = []

    def model(self, named: NamedSchema) -> PyApiModel:
        description = _docstring(named.description)
        schema = named.schema
        if not isinstance(schema, ObjectSchema):
            return PyApiModel(named.name, description, None, self.type(schema, named.name, True))
        taken: set[str] = set()
        fields = [
            PyApiField(
                attr=python_name(p.name, taken),
                name=p.name,
                type=self.type(p.schema, named.name + pascal(p.name)),
                required=p.required,
                description=_docstring(p.description),
            )
            for p in schema.properties
        ]
        return PyApiModel(named.name, description, fields)

    def type(self, schema: Schema, context: str, top: bool = False, *, query: bool = False) -> str:
        """Return the Python type of a schema. With `query`, any value is a text (`str`)."""
        match schema:
            case Ref(name):
                return name
            case ScalarSchema(kind, format_, enum) if enum:
                literal = "typing.Literal[" + ", ".join(_literal(v) for v in enum) + "]"
                if top:
                    return literal
                return self.alias(context, literal)
            case ScalarSchema(kind, format_):
                if kind == "string":
                    return _FORMATS.get(format_ or "", "str")
                return _SCALARS[kind]
            case ArraySchema(items):
                return f"list[{self.type(items, context + 'Item', query=query)}]"
            case MapSchema(values):
                return f"dict[str, {self.type(values, context + 'Value', query=query)}]"
            case UnionSchema(options):
                return " | ".join(self.type(o, context, query=query) for o in options)
            case AnySchema() | ObjectSchema():
                return "str" if query else "pydantic.JsonValue"

    def unique(self, wanted: str) -> str:
        """Return a name that no model or type alias has, and take it."""
        name = wanted
        number = 2
        while name in self.names:
            name = f"{wanted}{number}"
            number += 1
        self.names.add(name)
        return name

    def alias(self, context: str, literal: str) -> str:
        for alias in self.aliases:
            if alias.alias == literal:
                return alias.name
        name = context
        number = 2
        while name in self.names:
            name = f"{context}{number}"
            number += 1
        self.names.add(name)
        self.aliases.append(PyApiModel(name, None, None, literal))
        return name


def _std_imports(text: str) -> list[str]:
    """Return the imports of the standard library that the type expressions in a text use."""
    lines: list[str] = []
    if re.search(r"\bdt\.", text):
        lines.append("import datetime as dt")
    if re.search(r"\buuid\.", text):
        lines.append("import uuid")
    if re.search(r"\btyping\.", text):
        lines.append("import typing")
    return lines


def _optional(type_: str) -> str:
    return type_ if type_.endswith("| None") or type_ == "None" else f"{type_} | None"


def _wrap_type(prefix: str, type_: str) -> str:
    """Return `<prefix><type>`, with the items of a long `Literal` on their own lines."""
    line = prefix + type_
    match = re.fullmatch(r"typing\.Literal\[(.*)\]", type_)
    if len(line) <= 100 or match is None:
        return line
    items = [item.strip() for item in re.findall(r'"(?:[^"\\]|\\.)*"|[^,]+', match.group(1))]
    inner = "".join(f"    {item},\n" for item in items)
    return f"{prefix}typing.Literal[\n{inner}]"


def _formatted(value: object, prefix: str, suffix: str, indent: int) -> str:
    """Return `<prefix><literal><suffix>` in the format of Ruff.

    A dict or a list that does not fit on the line gets one item on each
    line. Many items get a trailing comma, one item does not.
    """
    line = prefix + _literal(value) + suffix
    if indent + len(line) <= LINE_LENGTH:
        return line
    items: list[tuple[str, object]]
    if isinstance(value, dict) and value:
        pairs = cast(dict[str, object], value).items()
        items, open_, close = [(f"{_literal(k)}: ", v) for k, v in pairs], "{", "}"
    elif isinstance(value, list) and value:
        items, open_, close = [("", v) for v in cast(list[object], value)], "[", "]"
    else:
        return line
    comma = "," if len(items) > 1 else ""
    pad = " " * (indent + 4)
    inner = "".join(f"{pad}{_formatted(v, p, comma, indent + 4)}\n" for p, v in items)
    return f"{prefix}{open_}\n{inner}{' ' * indent}{close}{suffix}"


def _literal(value: object) -> str:
    """Return a JSON value as a Python literal."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in cast(list[object], value)) + "]"
    if isinstance(value, dict):
        pairs = cast(dict[str, object], value).items()
        return "{" + ", ".join(f"{_literal(k)}: {_literal(v)}" for k, v in pairs) + "}"
    return repr(value)
