"""The JSON Schema of the app definition DSL, made from the Pydantic models.

Editors use the schema to complete and check app definitions while the
author types. Because the schema comes from the models, it cannot drift
from the loader. `schema/app.schema.json` holds a copy for editors.
"""

import json
from typing import Any

from appgen.dsl.model import AppDefinition

SCHEMA_ID = "https://raw.githubusercontent.com/ds411/app-generator/main/schema/app.schema.json"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def json_schema() -> dict[str, Any]:
    """Return the JSON Schema of an app definition."""
    schema = AppDefinition.model_json_schema()
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_ID,
        **schema,
        "title": "appgen app definition",
        "description": "An app definition for appgen, DSL version 0. See ADR 0002.",
    }


def json_schema_text() -> str:
    """Return the JSON Schema as JSON text, the same each time, with a final newline."""
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
