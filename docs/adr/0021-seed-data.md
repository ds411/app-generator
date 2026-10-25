# 0021. Seed data in the app definition

- Date: 2026-10-25
- Deciders: Maintainers

## Status

Accepted

## Context

The generated apps start with data that a pseudo-random generator makes
(`appgen.bindings.shared.mock_data`): the mock data of the React app,
and the seed of the Next.js app. The FastAPI app has no seed. An author
cannot give real records, for example the rooms of an office or the
categories of a shop.

The constraints:

- The same definition and the same generator version must give the same
  output (ADR 0004). The records need IDs that do not change from one
  run to the next.
- Traces refer to elements by ID, and an ID segment has only letters,
  digits, and `_` (ADR 0004). A new order of the elements must not
  change an ID (ADR 0002).
- The type of a value depends on the field of the entity, so the model
  of a record depends on its entity. The JSON Schema cannot check the
  values.
- The relations of the apps use the IDs of the records. An author does
  not want to write UUIDs.
- Large lists, for example an export of another system, do not fit well
  into the definition.

We looked at three forms of the records:

- **A list of records** under each entity. A list has no names, so a
  record has no element ID, and a relation cannot refer to a record.
- **A mapping from a record key to the record.** The key gives the
  element ID and a name for the relations.
- **Records with a UUID** that the author writes. The author must make
  and copy the UUIDs, and a relation is not readable.

## Decision

### The `seed` section

- A new optional top-level section `seed` maps an entity name to the
  seed of the entity. `records` maps a record key to the values of the
  record. Each record is an element: `seed.<Entity>.records.<key>`, of
  the kind `seed_record`. The seed of an entity has the kind
  `entity_seed`.
- A record key has only letters, digits, and `_`, so that it is a valid
  ID segment.
- A record gives values by field name and by relation name. A
  `many_to_one` or `one_to_one` relation takes the key of a seed record
  of the target entity, and a `many_to_many` relation takes a list of
  keys. A `one_to_many` relation takes no value: the records on the
  other side give it. A `one_to_one` relation and its inverse are one
  link: the author gives the key on one side, or on both sides with the
  same partner.
- A value of a `date` or a `datetime` field is ISO 8601 text. YAML reads
  a date without quotes as a date, so the loader also accepts such a
  value. A date-time without an offset is in UTC. The bindings get each
  value in a normal form (`appgen.dsl.seed.normal_value`): a date-time
  in UTC with a `Z`, and a UUID in small letters.
- Each record has a fixed ID: a UUID (version 5) from the app name, the
  entity name, and the key, in a namespace of appgen. A change of
  another record, or a new order of the records, does not change it.
- `mock` (an integer, 0 or more, default 0) gives the number of
  generated records that an entity with a seed has in addition to its
  seed records. An entity without a seed keeps its mock records
  (`x-mock-count`, default 12).
- A field that a record does not give gets its default, or no value.

### The checks

- The model keeps the values of a record as they are. The validator
  (`check_seed`) checks each value against the type and the options of
  its field (`values`, `min`, `max`, `min_length`, `max_length`,
  `pattern`, and `precision`), a value for a computed field, a required
  field or relation without a value, an unknown field or relation, and
  each key of a relation.
- Across the records of an entity, the validator checks the `unique`
  fields and the `compare`, `unique`, and `no_overlap` rules, with the
  defaults of the fields. A record has one partner or none in a
  `one_to_one` relation. An entity whose seed gives no record cannot be
  the target of a required relation of an entity with generated
  records.
- The codes: `unknown-key`, `invalid-value`, `missing-key`,
  `unsuitable-field`, and `unknown-reference`, as for other elements,
  and two new codes: `duplicate-value` (a repeated value of a unique
  field or rule, or a second partner) and `invalid-record` (a record
  that does not keep a `compare` or a `no_overlap` rule). Each
  diagnostic of a value gives the line of the value, and the element ID
  of the record.

### Data files

- `seed.<Entity>.file` names a local data file, relative to the folder
  of the definition: YAML or JSON (a mapping from a record key to a
  record, as `records`), or CSV (one row for each record, with a `key`
  column). The loader reads the files, as it reads the OpenAPI documents
  (ADR 0019). A URL is an error.
- The records of a file are elements with the same IDs as inline
  records, and each diagnostic gives the path of the file and the line
  of the record. The output manifest records the SHA-256 hash of each
  data file.
- A CSV cell is text, so the loader converts each cell to the type of
  its field. An empty cell is no value, and the keys of a
  `many_to_many` cell have `;` between them.

### The bindings

- The shared `mock_data` gives the seed records of each entity first,
  with their fixed IDs, then the generated records of `mock`. A
  generated record can refer to a seed record. Thus the React mock data,
  the Next.js seed, and the FastAPI seed have the same records.
- The Next.js seed and the FastAPI seed insert the seed records by ID: a
  second run adds the seed records that do not exist, and changes no
  record that exists. The generated records go only into empty tables.
- With `auth`, each seed record of the user entity is a user. With
  `SEED_PASSWORD`, it can sign in with this password, as a mock user
  can.
- Until a binding uses the seed, it excludes the kinds `entity_seed` and
  `seed_record`, so that it makes no gaps for them.

## Consequences

- An author gives real start data, and refers to other records by key,
  not by UUID. The apps show the same records after each run.
- The validator finds a bad value before the seed runs in a database.
  It does not find all problems that a database finds, for example a
  value that a hand-written rule rejects.
- A rename of a record key, an entity, or the app changes the ID of the
  record. The seed then adds a record with the new ID, and keeps the
  record with the old ID in a database that exists.
- The JSON Schema cannot check the values of a record, because their
  types depend on the entity. Only `appgen validate` checks them.
- The records of the definition and of the data files are part of the
  output. A large file makes large generated files.
