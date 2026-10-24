# 0019. Third-party APIs from OpenAPI documents

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

The generated apps use only their own data. Many apps also call an
outside service, for example payments, maps, or public holidays. An
OpenAPI document describes the paths, the parameters, the schemas, and
the security of such an API. A typed client lets the hand-written code
of an app call the API with checked parameters and results.

The constraints:

- The same definition and the same generator version must give the same
  output (ADR 0004). A document on a server can change at any time, and
  a check without a network must not fail.
- Real documents are large. An app often calls only a few operations.
- Each binding writes a client in its own language: Python (FastAPI) and
  TypeScript (Next.js and React).
- Traces refer to elements by ID, and an ID segment has only letters,
  digits, and `_` (ADR 0004).
- The logic that uses the data of an API is specific to the app. Views
  of third-party data without hand-written code are out of the scope of
  this version.

We looked at two ways to read the documents:

- **An OpenAPI package**, for example `openapi-spec-validator` with
  `prance`, or `openapi-pydantic`. These packages check the full
  specification and resolve remote references. They add dependencies
  and give much more than the clients need. They do not give the normal
  form that the templates need (see below).
- **A small reader** of the parts that the clients need. It checks less
  of the specification, but it gives clear errors with the line in the
  document, and it has no new dependency.

## Decision

### The `apis` section

- A new optional top-level section `apis` maps an API name to an API:
  the path of its OpenAPI document, the environment variable of its base
  URL (`base_url_env`), the optional security (`scheme` and `env`), and
  the operations that the app calls.
- `operations` is a list of operation IDs, or a mapping from operation
  ID to an operation with an optional `description`. The loader turns
  the list into the mapping, so that each operation is an element with
  the ID `apis.<name>.operations.<operation_id>`. An operation ID that
  is not a valid ID segment is an error (`invalid-name`).
- The security names a security scheme of the document. The clients
  support an API key in a header or a query parameter, and a bearer
  token. The secret comes from the environment variable in `env`.
- A custom operation can name the APIs that its logic calls (`apis` of
  the operation). The bindings give the clients of these APIs to the
  extension file of the operation.

### The documents

- The path of a document is relative to the folder of the definition.
  The loader reads each document when it loads the definition. A URL is
  an error: the generator reads only local files. The output manifest
  records the SHA-256 hash of each document (`documents`).
- We use a small reader (`appgen.dsl.openapi`), not an OpenAPI package.
  It reads OpenAPI 3.0 and 3.1, in YAML or JSON. It checks the structure
  that the clients need: the version, `info.title`, the paths, the
  operations and their responses, unique operation IDs, the parameters,
  and the security schemes.
- The reader resolves the local `$ref`s. A remote `$ref` is an error.
  The author copies the parts of the other file into the document.
- The validator reports a document that does not exist or is not valid
  (`invalid-document`), an operation ID or a security scheme that the
  document does not have (`unknown-reference`), a security scheme that
  the clients do not support (`unsuitable-security`), and an operation
  that a client cannot call (`unsuitable-operation`), for example an
  operation with a body that is not JSON, or with a cookie parameter.

### The normal form

- `OpenApiDocument.select` keeps only the selected operations and the
  schemas that they refer to, so a large document gives a small client.
- In the result, each object schema with properties has a name: a
  component schema keeps its name in Pascal case. An inline object gets
  the name of its place, for example `AddPetBody` or `PetOwner`. Thus a
  binding writes one class (Python) or one interface (TypeScript) for
  each object, and a reference elsewhere.
- `allOf` merges the properties of its parts. `oneOf`, `anyOf`, a list
  of types, and `nullable` become a union. A schema that the normal form
  cannot express becomes "any JSON value".
- Each operation has an example answer: the example of the document, or
  a sample from the schema. The mock data and the generated tests use
  it, so that the checks do not call the real API.

### The clients

- The FastAPI app and the Next.js app call the APIs on the server. The
  Next.js clients import `server-only`, so that a secret cannot get
  into the code of the browser.
- The React app has no server, and a browser app cannot keep a secret.
  Thus only an API without a secret gets a client. An API with a secret
  is a gap: an extension file `src/shared/api/<api>/client.ext.ts` with
  gap traces. `appgen generate` also gives a warning with a hint: call
  the API in a custom operation of the FastAPI app, and set
  `x-react-data: api`. The new field `warnings` of the binding contract
  gives such warnings.
- With mock data, the React client answers each call with the example
  answer of the operation, and sends no request.

## Consequences

- A definition with `apis` gives the same output on each run, without a
  network. A change of a document changes its hash in the manifest.
- The clients cover the common parts of REST APIs. They do not support
  other content types, cookie parameters, multipart bodies, or OAuth
  flows. The validator reports these cases, so that the author can call
  such an operation from hand-written code.
- The reader checks less than a full validator of the specification. A
  document that an OpenAPI validator rejects can pass, if the parts that
  the clients use are valid.
- An operation ID with other characters, for example `get-pets`, cannot
  be an element. The author must change the document, or use another
  operation.
- The bindings share one model of the API, so the clients of the three
  apps agree.
