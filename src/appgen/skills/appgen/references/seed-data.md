# Add seed records to a definition

Read this file when the task gives data that the app must start with,
for example a table of rooms in the prompt, a CSV file, or a JSON
export. The data becomes the **seed records** of the definition: the
`seed` section ([dsl.md](dsl.md#seed) has all keys). The React app has
them in its mock data, and the Next.js app and the FastAPI app add them
to the database with their seed command.

## Steps

1. Find the entity of each table of the data, and the field or the
   relation of each column. Add the fields that the data needs and the
   entity does not have.
2. Choose where the records go:
   - A few records (about 20 or fewer): `records` in the definition.
   - More records, or a file that the task gives: a data file next to
     the definition, in `file`. Use the file as it is if it is CSV,
     YAML, or JSON. An entity can have `records` and `file`.
3. Give each record a **record key**: letters, digits, and `_`, for
   example `a101` or `head_office`. Take it from a code or a name of the
   data, not from the row number. The key gives the ID of the record, so
   a later change of the key changes the ID.
4. Give the relations by record key. A `many_to_one` or `one_to_one`
   relation takes the key of a seed record of the target entity, and a
   `many_to_many` relation takes a list of keys (`[screen, board]`, or
   `screen;board` in a CSV cell). Give no value for a `one_to_many`
   relation: give the key on the other side. Each target needs a seed
   record too.
5. Convert each value to the type of its field (see
   [Values](#values)).
6. Set `mock` to the number of generated records that the entity gets
   in addition to the seed records. The default is 0: only the seed
   records.
7. Validate: `appgen validate app.yaml --format json`. Fix each
   diagnostic ([diagnostics.md](diagnostics.md)). A diagnostic of a
   record of a data file gives the file and the line.
8. Generate and check, as the CLI loop of `SKILL.md` tells. The check
   counts a trace to each seed record (`seed.<Entity>.records.<key>`).
9. Load the records into the app (see [Load the records](#load-the-records)).

## Example

Inline records for the offices, and a CSV file for the rooms:

```yaml
version: 0
app: { name: offices, title: Offices }
entities:
  Office:
    fields:
      name: { type: string, required: true, unique: true }
  Room:
    fields:
      code: { type: string, required: true, unique: true }
      capacity: { type: integer, min: 1 }
      bookable: { type: boolean, default: true }
      opened_on: { type: date }
    relations:
      office: { kind: many_to_one, target: Office, required: true }
      features: { kind: many_to_many, target: Feature }
  Feature:
    fields:
      label: { type: string, required: true }
seed:
  Office:
    records:
      hq: { name: Head office }
      lisbon: { name: Lisbon office }
  Room:
    file: data/rooms.csv
    mock: 2
  Feature:
    file: data/features.yaml
```

<!-- data/rooms.csv -->
```csv
key,code,capacity,bookable,opened_on,office,features
a101,A101,8,true,2020-03-01,hq,screen;board
a102,A102,4,,,hq,
l201,L201,12,false,2024-09-15,lisbon,board
```

<!-- data/features.yaml -->
```yaml
screen: { label: Screen }
board: { label: Whiteboard }
```

A CSV file has a header with the column `key`, and one column for each
field and relation that it gives. An empty cell is no value: the field
gets its default. A YAML or a JSON file is a mapping from a record key
to a record, as `records`.

## Values

| Type                              | Value                                                        |
| --------------------------------- | ------------------------------------------------------------ |
| `string`, `text`, `email`, `url`  | A text. Put quotes around a text that YAML reads as a number or a boolean, for example `code: "101"`. |
| `integer`, `decimal`              | A number, without units or thousands separators.             |
| `boolean`                         | `true` or `false`. Change `yes`/`no` and `1`/`0` of the data. |
| `enum`                            | One of the `values` of the field. Map the words of the data to them. |
| `date`                            | `YYYY-MM-DD`. Change `05/01/2026` to `2026-01-05`, after you find out the order of the day and the month. |
| `datetime`                        | ISO 8601 with an offset, for example `2026-01-05T09:30:00Z`. A value without an offset is in UTC. |
| `uuid`                            | A UUID.                                                      |
| `json`                            | Any value. In a CSV cell: JSON text.                         |
| `file`, `image`                   | The path of a local file, from the folder of the definition, for example `files/a101.jpg`. The file has 1 MB or less, and suits the `max_size` and the `types` of the field. |

Leave out a value that the data does not have. A required field without
a default needs a value. Do not invent a value: ask, or add a `default`
to the field if the task allows it. Do not give a computed field or a field
with `sequence`: the database gives its number.

## Load the records

| Binding   | Command                          | Result                                               |
| --------- | -------------------------------- | ---------------------------------------------------- |
| `react`   | None                             | The mock data has the seed records first (`src/entities/<entity>/api/<entity>-mock-data.ts`). |
| `nextjs`  | `pnpm db:seed`                   | Adds each seed record that the database does not have. `DATABASE_SEED=true` runs it when the server starts. |
| `fastapi` | `uv run python -m app.cli seed`  | The same. `DATABASE_SEED=true` runs it when the API starts. |

Apply the migrations first. The seed adds a record by its ID, and does
not change a record that exists, so you can run it again after you add
records to the definition. The generated records (`mock`) go in only if
all tables are empty. With `auth`, the seed records of the user entity
are users. With `SEED_PASSWORD`, the Next.js and FastAPI seeds give each
new seed user this password. The React app accepts each user with the
password `password`.

After a change of the definition, generate the app again: the seed
records are in generated files. A change of a data file needs a new run
of `appgen generate` too.
