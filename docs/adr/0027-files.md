# 0027. Files and images in the records

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

No field type holds a file. Many apps need one: the screenshot of an
issue, the photo of a product, the avatar of a user, or the PDF of an
invoice. The report "appgen Real App Coverage" lists 8 features in 6
apps that need files or images.

A file is not a value like a text or a number:

- It is large, so a database is a bad place for it. The usual places
  are a folder of the server, or an object storage service with the
  API of Amazon S3 (Amazon S3, Cloudflare R2, MinIO, and others).
- The FastAPI app takes JSON bodies, and its clients are the React app
  and other programs. A file needs a multipart body.
- A browser shows an image with `<img src>`, which sends no
  `Authorization` header. The React app signs in to the FastAPI app with
  a bearer token, so the URL of an image must work without the header.
  The Next.js app signs in with a cookie, which the browser sends.
- An app checks the size and the type of each file, so that a user
  cannot fill the storage or upload a page with scripts.

The options for the value of a file field:

- **A JSON value in one column**: the key of the file in the storage,
  the name, the size, and the media type. A record has one column for
  each file field, as for a translatable field (ADR 0026).
- **More columns for each field**, for example `<f>_key`, `<f>_name`,
  `<f>_size`, and `<f>_type`. Each field takes four names of the
  entity.
- **A table of files** with a relation from each record. Each read needs
  a join, and the relations of the entities get a second kind.

The options for the upload in the FastAPI app:

- **One endpoint for each file field** (`PUT` and `DELETE` with a
  multipart body), after the create of the record. The create and the
  change keep their JSON bodies.
- **A multipart create and change**: the record and its files in one
  request. The OpenAPI document gets two forms of each body, and each
  client must build multipart bodies.
- **An upload endpoint for all files**, which gives a key that the JSON
  body of the create names. The app needs a cleanup of the keys that no
  record names.

## Decision

We add the field types `file` and `image`, and the section `storage`.
Each file field holds one file, as a JSON value in one column.

### The definition

- `entities.<E>.fields.<f>.type` takes `file` and `image`. An `image`
  field is a `file` field that allows only image types.
- `max_size` is the largest file: an integer of bytes, or a text with
  `B`, `KB`, `MB`, or `GB`, for example `5MB` (1 KB is 1024 bytes). The
  default is 10 MB.
- `types` is the list of the media types that the field allows, for
  example `application/pdf`, or a group, for example `image/*`. The
  default of a `file` field is all types. The default of an `image`
  field is `image/png`, `image/jpeg`, `image/gif`, and `image/webp`: an
  SVG image can have scripts, so it needs an explicit `types`.
- The optional section `storage` has `kind` (`local` or `s3`) and the
  names of the environment variables of its settings: `folder_env`
  (`STORAGE_FOLDER`), and for `s3` also `bucket_env` (`STORAGE_BUCKET`),
  `region_env` (`STORAGE_REGION`), `endpoint_env` (`STORAGE_ENDPOINT`),
  `access_key_env` (`STORAGE_ACCESS_KEY_ID`), and `secret_key_env`
  (`STORAGE_SECRET_ACCESS_KEY`). With `s3`, the apps keep the files in
  the folder while the variable of the bucket has no value, for example
  on the machine of a developer and in the tests.
- `storage` is an element with the ID `storage`. The code of the
  storage has a trace to it, and the code of each file field has a
  trace to the field.
- More files for one record are a `one_to_many` relation to an entity
  with a file field, for example `Attachment`.

`appgen validate` reports:

- A file field without `storage` (`invalid-option`).
- A media type that is not valid: a value that does not match
  `type/subtype` (`invalid-value`), a top-level type that is not
  `application`, `audio`, `font`, `image`, `model`, `text`, or `video`
  (`invalid-value`), another type than an image type in an `image` field
  (`invalid-value`), and a type that occurs two times (`duplicate-name`).
- `required`, `unique`, and `default` on a file field
  (`invalid-option`). The upload comes after the create, so the apps
  cannot require a file in each record. A form can require a file with
  the rule `required` of its form field.
- A computed file field, and a file field in the expression of a
  computed field, in an entity rule, in a sort, or in a filter
  (`invalid-option` and `unsuitable-field`). A param of an operation
  cannot be a file (`invalid-option`).
- A key of `s3` in a `local` storage (`invalid-option`), a variable that
  the apps use for their own settings (`invalid-value`), a variable of a
  key that starts with `NEXT_PUBLIC_` or `VITE_` (`invalid-value`), and
  a variable that the storage or an API also uses (`duplicate-name`).

### Seed records

A seed record gives the value of a file field as the path of a local
file, from the folder of the definition, for example
`files/board.png`. The loader reads the file. The validator reports a
file that does not exist, a file larger than the `max_size` of its
field, and a type that the field does not allow (`invalid-value`). The
extension of the file gives its type, from a fixed table, so that each
machine gives the same type. The output manifest records the hash of
each file, as it does for the data files (ADR 0021).

The generated code holds no binary files, so the apps keep each seed
file in their code, as text (Base64). A seed file can have 1 MB or less.

### The apps

- The column of a file field (JSON, JSONB on Postgres) keeps the key of
  the file in the storage, the name, the size, and the media type, or
  null without a file. The key is new for each upload, so that a cache
  never shows an old file.
- The apps check the size and the type of each upload. The type comes
  from the first bytes of the file when the app knows them (PNG, JPEG,
  GIF, WebP, and PDF), else from the type that the client gives. The
  FastAPI app gives the status 413 for a file that is too large, and 415
  for a type that the field does not allow.
- An app deletes the file of a record when it deletes the record, and
  the old file when a new file replaces it, after the commit.
- FastAPI: each file field has the endpoints `PUT` and `DELETE`
  `/<plural>/{id}/<field>`, with a multipart body. They need the
  permission of the update operation of the entity (else of the create
  operation), and the record rules of the change apply (ADR 0025). The
  read schema gives the name, the size, the type, and a URL of the file.
  The URL is a signed link to the app (`/file-links/<token>`, an
  HMAC-SHA256 signature with `STORAGE_LINK_SECRET`), which ends after a
  time (`STORAGE_LINK_SECONDS`), so an `<img src>` works without the
  bearer token. The end of a link is a multiple of 5 minutes, so that a
  browser can cache the file. The app gives the link only with a read of
  the record, so the access rules of the read apply. The response of a
  link has `X-Content-Type-Options: nosniff` and a content security
  policy with `sandbox`, so that a file cannot run scripts. The S3
  storage uses boto3 in worker threads.
- Next.js: the server actions of the forms take the files in their
  form data (`upload<Entity>FileAction`). A route handler gives a file
  (`/files/<entity>/<id>/<field>`). It checks the session and the
  access rules of the record, as a read does, so the URL needs no
  signature. The S3 storage uses `@aws-sdk/client-s3`. Next.js limits
  the body of a server action to 1 MB by default, so `next.config.ts`
  allows the largest file of the file fields and 1 MB more.
- React: the mock data keeps an uploaded file in the browser tab. With
  `x-react-data: api`, the forms call the endpoints of the FastAPI app.

The bindings add the file fields one after the other. Until a binding
generates their code, `appgen generate` stops with an error for a
definition with a file field.

## Consequences

- A record has its files without a join, and the search, the sort, and
  the filters do not change.
- A JSON column has no foreign key: a file that a record does not name
  any more stays in the storage if a delete fails after the commit. The
  files of the records that the database deletes with `on_delete:
  cascade` stay in the storage too. A later job can remove such files.
- The create of a record with a file takes two requests in the FastAPI
  app. A record can exist without its file for a short time.
- A file field cannot be required in the database. A form can require a
  file.
- A signed URL works for anyone who has it, until it ends.
- The seed files make the code of the apps larger, so they must be
  small.
