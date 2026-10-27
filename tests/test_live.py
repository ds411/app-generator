"""The live updates of the records: the DSL, the checks, and the FastAPI app (ADR 0051)."""

from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.live import Live
from appgen.dsl.schema import json_schema
from appgen.gen.elements import element_kind
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
RULES = ROOT / "tests" / "fixtures" / "record-rules.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        crud: true
        live: true
        fields:
          title: { type: string, required: true }
      Project:
        crud: true
        fields:
          name: { type: string, required: true }
    """
)

USER = """\
  User:
    crud: true
    fields:
      email: { type: email, required: true, unique: true }
"""

AUTH = dedent(
    """\
    auth:
      user_entity: User
      username_field: email
      public_operations: [list_projects]
    """
)


def with_live(text: str, entity: str = "Task") -> str:
    """Return the base definition with another `live` of Task, or with `live` on Project."""
    base = BASE.replace("    live: true\n", f"    live: {text}\n", 1)
    if entity == "Project":
        base = base.replace(
            "  Project:\n    crud: true\n", "  Project:\n    crud: true\n    live: true\n", 1
        )
    return base


def with_auth(text: str) -> str:
    """Return a definition with the sign-in, a user entity, and a public list of the projects."""
    return text + USER + AUTH


def files_of(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_live_is_true_or_a_mapping_with_a_description() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    live = definition.entities["Task"].live
    assert isinstance(live, Live)
    assert live.description is None
    assert definition.entities["Project"].live is None
    assert isinstance(definition.find("entities.Task.live"), Live)
    path = ("entities", "Task", "live")
    assert element_kind(path, definition.elements["entities.Task.live"]) == "live"
    assert validate_definition(definition) == []

    text = with_live("{ description: The board shows the changes at once. }")
    live = load_definition_text(text, "app.yaml").entities["Task"].live
    assert live is not None and live.description == "The board shows the changes at once."
    assert load_definition_text(with_live("false"), "app.yaml").entities["Task"].live is None


def test_the_schema_has_the_short_form_of_live() -> None:
    schema = json_schema()
    assert schema["$defs"]["Entity"]["properties"]["live"]["$ref"] == "#/$defs/LiveInput"
    assert schema["$defs"]["LiveInput"]["anyOf"] == [
        {"type": "boolean"},
        {"$ref": "#/$defs/Live"},
        {"type": "null"},
    ]
    assert set(schema["$defs"]["Live"]["properties"]) == {"description"}


def test_a_live_entity_needs_a_list_or_a_read_operation() -> None:
    text = BASE.replace("    crud: true\n    live: true\n", "    crud: [create]\n    live: true\n")
    definition = load_definition_text(text, "app.yaml")
    diagnostics = validate_definition(definition)
    assert [(d.code, d.element_id) for d in diagnostics] == [("missing-key", "entities.Task.live")]
    assert diagnostics[0].hint == (
        "Add a list or a read operation of the entity, for example with 'crud'."
    )
    only_read = BASE.replace(
        "    crud: true\n    live: true\n", "    crud: [read]\n    live: true\n"
    )
    assert validate_definition(load_definition_text(only_read, "app.yaml")) == []


def test_the_fastapi_app_streams_the_changes_of_the_live_entities() -> None:
    files = files_of(with_live("true", entity="Project"))
    live = files["app/core/live.py"]
    assert '    Task: LiveEntity("Task", ("read_task", "list_tasks")),\n' in live
    assert '    Project: LiveEntity("Project", ("read_project", "list_projects")),\n' in live
    assert 'type LiveName = Literal["Task", "Project"]\n' in live
    assert 'CHANNEL = "tracker:live"\n' in live
    assert '@router.get(\n    "/live",\n    response_class=EventSourceResponse,\n' in live
    # Without the sign-in, all clients get the events, and no record rule applies.
    assert "RECORD_RULES" not in live
    assert "Audience" not in live
    assert "    return Viewer(frozenset(entity or NAMES))\n" in live
    main = files["app/main.py"]
    assert "    app.state.live = Broker(settings.live_events_url)\n" in main
    assert "    app.state.sessions.configure(info={BROKER_KEY: app.state.live})\n" in main
    assert "    with end_streams_on_exit(app.state.live):\n        yield\n" in main
    assert "    await app.state.live.close()\n" in main
    assert "    app.include_router(live_router)\n" in main
    assert "    live_events_url: str | None = None\n" in files["app/core/config.py"]
    assert '    "redis>=8.0",\n' in files["pyproject.toml"]
    assert "LIVE_EVENTS_URL=\n" in files[".env.example"]
    assert "      LIVE_EVENTS_URL: ${LIVE_EVENTS_URL:-}\n" in files["compose.yaml"]
    assert "    profiles: [redis]\n" in files["compose.yaml"]
    assert "## Live updates\n" in files["README.md"]
    tests = files["tests/test_live.py"]
    assert (
        "async def test_the_stream_sends_the_creates_the_changes_and_the_deletes_of_tasks(\n"
        in (tests)
    )
    assert "async def test_a_change_that_rolls_back_gives_no_event(" in tests
    assert "async def test_the_streams_end_when_the_server_stops() -> None:\n" in tests
    assert "def test_the_stream_needs_a_signed_in_user" not in tests


def test_the_fastapi_app_without_live_has_no_stream() -> None:
    files = files_of(with_live("false"))
    assert "app/core/live.py" not in files
    assert "tests/test_live.py" not in files
    assert "live" not in files["app/main.py"]
    assert "redis" not in files["pyproject.toml"]
    assert "LIVE_EVENTS_URL" not in files[".env.example"]
    assert "redis" not in files["compose.yaml"]


def test_with_the_sign_in_the_stream_needs_a_user_except_for_a_public_operation() -> None:
    files = files_of(with_auth(with_live("true", entity="Project")))
    live = files["app/core/live.py"]
    assert '    Task: LiveEntity("Task", ("read_task", "list_tasks")),\n' in live
    assert (
        '    Project: LiveEntity("Project", ("read_project", "list_projects"), public=True),\n'
    ) in live
    assert (
        "    readable = {name for name in names if NAMES[name].public or user is not None}\n"
        in (live)
    )
    assert "    responses=problem_responses(401),\n" in live
    tests = files["tests/test_live.py"]
    assert "async def test_the_stream_needs_a_signed_in_user(app: FastAPI) -> None:\n" in tests
    assert '    async with open_stream(app, "entity=Task") as stream:\n' in tests


def test_the_record_rules_decide_who_gets_the_events() -> None:
    definition = load_definition(RULES)
    assert definition.entities["Task"].live is not None
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    live = files["app/core/live.py"]
    assert "from app.core.access import RECORD_RULES, allows\n" in live
    assert "class Audience:\n" in live
    assert "    audiences: tuple[Audience, ...] | None = None\n" in live
    assert '@event.listens_for(Session, "before_flush")\n' in live
    assert "    responses=problem_responses(401, 403),\n" in live
    tests = files["tests/test_live.py"]
    for role in ("member", "reviewer"):
        name = f"test_the_stream_of_the_role_{role}_to_its_tasks_has_only_the_records_of_its_rule"
        assert f"async def {name}(\n" in tests
    # Each role may read the tasks: no role gets 403.
    assert "gets_403" not in tests
