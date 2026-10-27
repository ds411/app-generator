# 0019. Third-party APIs from OpenAPI documents

- Date: 2026-10-24 (forms, files, text and binary answers, cookies, and
  OAuth 2.0: 2026-10-25)
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
  URL (`base_url_env`), the optional security (`scheme` and `env`, or
  for OAuth 2.0 `client_id_env`, `client_secret_env`, and `scopes`),
  and the operations that the app calls.
- `operations` is a list of operation IDs, or a mapping from operation
  ID to an operation with an optional `description`. The loader turns
  the list into the mapping, so that each operation is an element with
  the ID `apis.<name>.operations.<operation_id>`. An operation ID that
  is not a valid ID segment is an error (`invalid-name`).
- The security names a security scheme of the document. The clients
  support an API key in a header or a query parameter, a bearer token,
  and OAuth 2.0 with the client credentials flow. The secret comes from
  the environment variable in `env`, or in `client_secret_env` for
  OAuth 2.0.
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
  operation with an XML body, or with a cookie parameter that is an
  object.

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

### Content types, cookies, and OAuth 2.0

- The normal form keeps the kind of the request body (`json`, `form`
  for `application/x-www-form-urlencoded`, or `multipart` for
  `multipart/form-data`) and the kind of the answer (`json`, `text` for
  `text/*`, or `binary`), with the media type of the answer. When the
  document gives more than one media type, JSON comes first. The client
  sends the media type of the answer in the header `Accept`.
- The schema of a form is an object with properties. A form holds only
  texts, numbers, booleans, and lists of these. A multipart form can
  also hold files and objects (as JSON text). A file is a string with
  `format: binary`, or with `contentMediaType` in OpenAPI 3.1. It is a
  `Blob` in TypeScript (a `File` gives its name), and an `ApiFile` with
  a name, the content, and a media type in Python, because a multipart
  part needs a file name.
- A text answer is a string, and a binary answer is a `Blob` in
  TypeScript and `bytes` in Python. The example of a text answer is the
  example of the document or a fixed text, and the example of a binary
  answer is the bytes of a fixed text.
- A cookie parameter is a text, a number, or a boolean. The server
  clients send it in the header `Cookie`, percent-encoded as
  `encodeURIComponent` does it. A browser cannot set a cookie for
  another site, so in the React app an API with a cookie parameter is a
  gap, as an API with a secret is, unless the API has `expose`.
- For OAuth 2.0, the security scheme must have the client credentials
  flow, else the validator reports `unsuitable-security`. The token URL
  comes from the document. A token URL that is a path is under the base
  URL of the API, so that the mock server and a test server can give
  the tokens. Each scope in `scopes` must be a scope of the flow.
- The client authenticates with HTTP Basic (RFC 6749, section 2.3.1),
  and keeps the token until 30 seconds before it ends. Each process has
  one token source for each base URL, token URL, client ID, and scopes.
  Two requests at the same time wait for the same token request: a lock
  in Python, and a shared promise in TypeScript. After an answer with
  the status 401, the client gets a new token one time, and sends the
  request again.

### The clients

- The FastAPI app and the Next.js app call the APIs on the server. The
  Next.js clients import `server-only`, so that a secret cannot get
  into the code of the browser.
- The React app has no server, and a browser app cannot keep a secret.
  Thus only an API without a secret and without a cookie parameter gets
  a client. Another API is a gap: an extension file
  `src/shared/api/<api>/client.ext.ts` with gap traces. `appgen generate` also gives a warning with a hint: call
  the API in a custom operation of the FastAPI app, and set
  `x-react-data: api`. The new field `warnings` of the binding contract
  gives such warnings.
- With mock data, the React client answers each call with the example
  answer of the operation, and sends no request.
- `expose: true` on an API gives the FastAPI app an endpoint for each
  operation: `/apis/<api>/<operation>`, in kebab case. The endpoint
  calls the operation with the client of the FastAPI app, which has the
  secret, and gives the answer. It takes all parameters as query
  parameters and the body as its body, so that each client can call it
  in the same way. An error of the API gives 502. With `auth`, the
  endpoints need a signed-in user, and the rate limit applies to them.
  The React app then has a client for the API, also with a secret: with
  `x-react-data: api`, the client calls the endpoints with the token of
  the user, and with mock data it gives the examples. Thus an exposed
  API is not a gap, and `appgen generate` gives no warning for it. The
  validator rejects an exposed operation with a parameter that a query
  parameter cannot hold, a form body, or an answer that is not JSON,
  because the endpoints take and give JSON.

### HTTP Basic (update for #486)

- A scheme with `type: http` and `scheme: basic` is supported. Its
  security has `username_env` (the user name) and `env` (the password),
  and the validator requires both. It checks `username_env` as it
  checks `env`: a variable of the apps, a variable with a public prefix,
  or a variable with two uses is an error.
- The clients send the header `Authorization: Basic` with the Base64 of
  the UTF-8 bytes of `<user name>:<password>` (RFC 7617). The FastAPI
  client gets the user name and the password from the settings, and the
  Next.js client from the environment (`Buffer`, because `btoa` fails on
  characters outside Latin-1). Without a password, a client sends no
  credential, as without an API key.
- Both variables are secrets: the deployment files and the README of
  each app list them as secrets, and the React app has no client for
  such an API unless the API has `expose: true`.
- The first use is the Jira Cloud REST API: the user name is the email
  address of an Atlassian account, and the password is an API token
  (tests/fixtures/jira.yaml). Its OpenAPI document gives each example as
  a string with the JSON text. The reader reads such a string as JSON
  when the answer cannot be a string.

## Consequences

- A definition with `apis` gives the same output on each run, without a
  network. A change of a document changes its hash in the manifest.
- The clients cover the common parts of REST APIs: JSON, forms, and
  multipart forms, text and binary answers, cookie parameters, and
  OAuth 2.0 with the client credentials flow. They do not support other
  bodies (for example XML), the other OAuth flows, OpenID Connect, or
  mutual TLS. The validator reports these cases, so that the author can
  call such an operation from hand-written code.
- With HTTP Basic, the password goes with each request, so the server
  of the API must use HTTPS. The clients do not check the scheme of the
  base URL: a local mock server uses HTTP.
- Each process keeps its own token. Two instances of an app get two
  tokens, and a token that the API revokes costs one failed request.
- The reader checks less than a full validator of the specification. A
  document that an OpenAPI validator rejects can pass, if the parts that
  the clients use are valid.
- An operation ID with other characters, for example `get-pets`, cannot
  be an element. The author must change the document, or use another
  operation.
- The bindings share one model of the API, so the clients of the three
  apps agree.
