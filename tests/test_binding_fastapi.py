"""Tests of the FastAPI binding: the generated files, their traces, and determinism.

The pre-push hook installs, lints, type checks, and tests the generated
app (see `scripts/check-fastapi.sh`). These tests check the output of the
generator only, so that they need no network and no database.
"""

import os
from pathlib import Path

import pytest

from appgen.bindings.fastapi.model import python_app
from appgen.bindings.fastapi.names import attribute, plural, singular
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen import Binding, GenerationResult, find_binding, generate, write_result
from appgen.trace import check_traces

TESTS = Path(__file__).parent
FIXTURE = TESTS / "fixtures" / "project-tracker.yaml"
EXAMPLES = TESTS.parent / "examples"
GOLDEN = TESTS / "golden" / "fastapi"


@pytest.fixture(scope="module")
def fastapi() -> Binding:
    return find_binding("fastapi")


@pytest.fixture(scope="module")
def definition() -> AppDefinition:
    return load_definition(FIXTURE)


@pytest.fixture(scope="module")
def result(definition: AppDefinition, fastapi: Binding) -> GenerationResult:
    return generate(definition, fastapi)


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def test_output_matches_the_golden_files(result: GenerationResult) -> None:
    files = _files(result)
    if os.environ.get("APPGEN_UPDATE_GOLDEN") == "1":
        for path, content in files.items():
            target = GOLDEN / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode())
    golden = {
        path.relative_to(GOLDEN).as_posix(): path.read_bytes().decode()
        for path in sorted(GOLDEN.rglob("*"))
        if path.is_file()
    }
    assert files == golden


@pytest.mark.parametrize("example", ["project-tracker", "edge-cases"])
def test_two_runs_give_the_same_output(fastapi: Binding, example: str) -> None:
    definition = load_definition(EXAMPLES / example / "app.yaml")
    assert _files(generate(definition, fastapi)) == _files(generate(definition, fastapi))


def test_the_app_uses_fastapi_python_3_14_and_uv(result: GenerationResult) -> None:
    files = _files(result)
    assert '"fastapi[standard]>=0.161,<0.162"' in files["pyproject.toml"]
    assert 'requires-python = ">=3.14"' in files["pyproject.toml"]
    assert files[".python-version"] == "3.14\n"


def test_each_entity_is_a_slice_with_a_router(result: GenerationResult) -> None:
    files = _files(result)
    for slice_name in ("projects", "tasks"):
        assert f"app/features/{slice_name}/router.py" in files
        assert f"from app.features.{slice_name}.router import" in files["app/main.py"]
    router = files["app/features/tasks/router.py"]
    assert 'router = APIRouter(tags=["Tasks"])' in router
    assert "# @trace operations.create_task\nrouter.include_router(create_task.router)" in router


@pytest.mark.parametrize("example", ["project-tracker", "edge-cases"])
def test_the_check_finds_no_invalid_traces(tmp_path: Path, fastapi: Binding, example: str) -> None:
    definition = load_definition(EXAMPLES / example / "app.yaml")
    result = generate(definition, fastapi)
    write_result(result, tmp_path, fastapi.name)

    report = check_traces(definition, tmp_path)

    assert report.invalid == []
    with_file_trace = {t.file for t in report.traces if t.scope == "file"}
    assert with_file_trace == {f.path for f in result.files}
    assert report.coverage.total.uncovered == 0


def test_pages_and_the_ui_are_out_of_scope(result: GenerationResult) -> None:
    assert result.excluded_kinds == ("page", "translations", "ui")
    assert not [g for g in result.gaps if g.element_id.startswith("pages.")]


def test_python_names() -> None:
    assert [plural(n) for n in ("Task", "Category", "Box", "Day", "ProjectTask")] == [
        "tasks",
        "categories",
        "boxes",
        "days",
        "project_tasks",
    ]
    assert [singular(n) for n in ("members", "categories", "boxes", "class")] == [
        "member",
        "category",
        "box",
        "class",
    ]
    assert [attribute(n) for n in ("title", "from", "metadata", "model_number")] == [
        "title",
        "from_",
        "metadata_",
        "model_number_",
    ]


def test_slices_use_the_plural_label_of_the_entity() -> None:
    app = python_app(load_definition(EXAMPLES / "project-tracker" / "app.yaml"))
    assert app.entity("Person").slice == "people"
    assert app.entity("Person").path == "/people"
    assert app.entity("Task").slice == "tasks"


def test_two_names_with_the_same_python_name_stop_the_run(fastapi: Binding) -> None:
    definition = load_definition_text(
        "version: 0\n"
        "app: { name: clash, title: Clash }\n"
        "entities:\n"
        "  Task:\n"
        "    fields:\n"
        "      owner_id: { type: uuid }\n"
        "    relations:\n"
        "      owner: { kind: many_to_one, target: Task }\n"
    )
    with pytest.raises(Exception, match="both give the Python name 'owner_id'"):
        generate(definition, fastapi)


def test_each_entity_has_create_update_and_read_schemas(result: GenerationResult) -> None:
    schemas = _files(result)["app/features/tasks/schemas.py"]
    for name in ("TaskCreate(InputModel)", "TaskUpdate(InputModel)", "TaskRead(ReadModel)"):
        assert f"class {name}:" in schemas
    assert "    title: str\n" in schemas
    assert "    due_date: dt.date | None = None\n" in schemas
    assert "    project_id: UUID\n" in schemas
    assert 'return reject_null(self, "title", "project_id")' in schemas
    assert "# @trace entities.Task.fields.title" in schemas


def test_enums_have_their_own_module(result: GenerationResult) -> None:
    files = _files(result)
    assert 'IN_PROGRESS = "in_progress"' not in files["app/features/projects/enums.py"]
    assert 'PLANNED = "planned"' in files["app/features/projects/enums.py"]
    assert "app/features/tasks/enums.py" not in files


def test_an_embedded_relation_is_an_object_in_the_read_schema(fastapi: Binding) -> None:
    definition = load_definition(EXAMPLES / "edge-cases" / "app.yaml")
    files = _files(generate(definition, fastapi))
    schemas = files["app/features/items/schemas.py"]
    assert "from app.features.owners.schemas import OwnerRead" in schemas
    assert "    owner: OwnerRead | None\n" in schemas
    assert (
        "    tag_ids: list[UUID] = Field(default_factory=list[UUID])\n"
        in (files["app/features/owners/schemas.py"])
    )


def test_a_field_can_give_its_sample_value(fastapi: Binding) -> None:
    definition = load_definition_text(
        "version: 0\n"
        "app: { name: codes, title: Codes }\n"
        "entities:\n"
        "  Code:\n"
        "    fields:\n"
        "      value: { type: string, pattern: '^(?=x)', x-example: x1 }\n"
    )
    payloads = _files(generate(definition, fastapi))["tests/payloads.py"]
    assert '"value": "x1",' in payloads


def test_embedded_relations_cannot_form_a_cycle(fastapi: Binding) -> None:
    definition = load_definition_text(
        "version: 0\n"
        "app: { name: loop, title: Loop }\n"
        "entities:\n"
        "  Node:\n"
        "    fields:\n"
        "      name: { type: string }\n"
        "    relations:\n"
        "      parent: { kind: many_to_one, target: Node, x-fastapi-embed: true }\n"
    )
    with pytest.raises(Exception, match=r"cycle: Node -> Node"):
        generate(definition, fastapi)


def test_each_entity_has_a_model_with_columns_and_relations(fastapi: Binding) -> None:
    definition = load_definition(EXAMPLES / "project-tracker" / "app.yaml")
    files = _files(generate(definition, fastapi))
    tasks = files["app/features/tasks/models.py"]
    assert '    __tablename__ = "tasks"\n' in tasks
    assert "    title: Mapped[str] = mapped_column(String(200))\n" in tasks
    assert 'ForeignKey("projects.id", ondelete="CASCADE")' in tasks
    assert "    project: Mapped[Project] = relationship(\n" in tasks
    assert 'foreign_keys="Comment.task_id"' in tasks
    projects = files["app/features/projects/models.py"]
    assert "projects_members = Table(" in projects
    assert "def member_ids(self) -> list[UUID]:" in projects
    assert "from app.features.tasks.models import Task" in files["app/models.py"]


def test_the_migration_creates_each_table_and_foreign_key(fastapi: Binding) -> None:
    definition = load_definition(EXAMPLES / "project-tracker" / "app.yaml")
    migration = _files(generate(definition, fastapi))["migrations/versions/0001_schema.py"]
    for table in ("people", "projects", "tasks", "comments", "projects_members"):
        assert f'        "{table}",\n' in migration
        assert f'op.drop_table("{table}")' in migration
    assert '"fk_tasks_project_id_projects",' in migration
    assert 'sa.UniqueConstraint("email", name="uq_people_email")' in migration
    assert 'op.create_index("ix_tasks_project_id", "tasks", ["project_id"])' in migration


def test_one_side_of_a_one_to_one_pair_has_the_foreign_key(fastapi: Binding) -> None:
    app = python_app(load_definition(EXAMPLES / "edge-cases" / "app.yaml"))
    [owner_profile] = [r for r in app.entity("Owner").relations if r.name == "profile"]
    [profile_owner] = app.entity("Profile").relations
    assert (owner_profile.side, owner_profile.fk) == ("fk", "profile_id")
    assert profile_owner.side == "back"


def test_each_operation_has_its_own_module(result: GenerationResult) -> None:
    files = _files(result)
    for module in ("create_task", "list_tasks", "complete_task_gen", "repository"):
        assert f"app/features/tasks/{module}.py" in files
    assert files["app/features/tasks/create_task.py"].startswith(
        "# Generated by appgen. Do not edit: change the app definition instead.\n"
        "# @trace operations.create_task file\n"
    )
    assert 'router = APIRouter(prefix="/tasks")' in files["app/features/tasks/list_tasks.py"]
    assert "class ListTasksQuery(PageQuery):" in files["app/features/tasks/list_tasks.py"]
    assert "def add_problem_handlers(app: FastAPI) -> None:" in files["app/core/errors.py"]
    assert "add_problem_handlers(app)" in files["app/main.py"]


def test_a_custom_operation_has_a_generated_endpoint_and_an_extension_file(
    result: GenerationResult,
) -> None:
    by_path = {f.path: f for f in result.files}
    gen = by_path["app/features/tasks/complete_task_gen.py"]
    ext = by_path["app/features/tasks/complete_task_ext.py"]
    assert (gen.kind, ext.kind) == ("generated", "extension")
    assert "from app.features.tasks.complete_task_ext import complete_task" in gen.content
    assert '"/{id}/complete-task"' in gen.content
    assert "# @trace:gap operations.complete_task file" in ext.content
    assert "# TODO(appgen): write the logic of the operation complete_task." in ext.content
    assert 'raise NotImplementedError("operations.complete_task")' in ext.content
    assert (
        "class CompleteTaskParams(InputModel):" in by_path["app/features/tasks/schemas.py"].content
    )


def test_routes_with_a_fixed_path_come_before_routes_with_an_id() -> None:
    app = python_app(load_definition(EXAMPLES / "project-tracker" / "app.yaml"))
    routes = [(op.method.upper(), op.path) for op in app.entity("Task").operations]
    assert routes == [
        ("POST", ""),
        ("GET", ""),
        ("GET", "/{id}"),
        ("PATCH", "/{id}"),
        ("DELETE", "/{id}"),
        ("POST", "/{id}/assign-task"),
        ("POST", "/{id}/complete-task"),
        ("POST", "/{id}/schedule-task"),
    ]


def test_a_second_operation_of_a_kind_gets_a_path_with_its_name() -> None:
    definition = load_definition_text(
        "version: 0\n"
        "app: { name: lists, title: Lists }\n"
        "entities:\n"
        "  Task:\n"
        "    fields:\n"
        "      title: { type: string }\n"
        "operations:\n"
        "  list_tasks: { kind: list, entity: Task }\n"
        "  open_tasks: { kind: list, entity: Task }\n"
    )
    paths = [op.path for op in python_app(definition).entity("Task").operations]
    assert paths == ["", "/open-tasks"]


def test_an_operation_cannot_have_the_name_of_a_slice_module(fastapi: Binding) -> None:
    definition = load_definition_text(
        "version: 0\n"
        "app: { name: clash, title: Clash }\n"
        "entities:\n"
        "  Task:\n"
        "    fields:\n"
        "      title: { type: string }\n"
        "operations:\n"
        "  schemas: { kind: list, entity: Task }\n"
    )
    with pytest.raises(Exception, match="has the name of a module of the slice 'tasks'"):
        generate(definition, fastapi)


def test_each_entity_has_a_validation_extension_file(result: GenerationResult) -> None:
    by_path = {f.path: f for f in result.files}
    for slice_name in ("projects", "tasks"):
        ext = by_path[f"app/features/{slice_name}/validation_ext.py"]
        assert ext.kind == "extension"
        assert "async def validate(session: AsyncSession, record: " in ext.content
    repository = by_path["app/features/tasks/repository.py"].content
    assert "from app.features.tasks.validation_ext import validate" in repository
    assert "    await validate(session, record, created=True)\n" in repository
    assert "    await validate(session, record, created=False)\n" in repository


def test_regeneration_keeps_the_code_in_the_extension_files(
    tmp_path: Path, definition: AppDefinition, result: GenerationResult, fastapi: Binding
) -> None:
    write_result(result, tmp_path, fastapi.name)
    validation = tmp_path / "app" / "features" / "tasks" / "validation_ext.py"
    operation = tmp_path / "app" / "features" / "tasks" / "complete_task_ext.py"
    validation.write_text("# my validation\n")
    operation.write_text("# my operation\n")

    write_result(generate(definition, fastapi), tmp_path, fastapi.name)

    assert validation.read_text() == "# my validation\n"
    assert operation.read_text() == "# my operation\n"


def test_each_operation_has_a_test_module(result: GenerationResult) -> None:
    files = _files(result)
    for name in ("create_task", "list_tasks", "complete_task"):
        test = files[f"tests/features/tasks/test_{name}.py"]
        assert test.startswith(
            "# Generated by appgen. Do not edit: change the app definition instead.\n"
            f"# @trace operations.{name} file\n"
        )
    create = files["tests/features/tasks/test_create_task.py"]
    assert "async def test_create_task_stores_a_record(" in create
    assert "# @trace entities.Task.relations.project\n" in create
    assert "assert_problem(response, 422)" in create
    complete = files["tests/features/tasks/test_complete_task.py"]
    assert "assert_problem(response, 404)" in complete


def test_the_tests_of_a_custom_operation_check_the_501_of_the_stub(
    result: GenerationResult,
) -> None:
    complete = _files(result)["tests/features/tasks/test_complete_task.py"]
    assert "async def test_complete_task_gives_501_until_it_has_its_logic(" in complete
    assert "    record = await make_task(session)\n" in complete
    assert 'await client.post(f"/tasks/{record.id}/complete-task"' in complete
    assert "        assert_problem(response, 501)\n" in complete
    # After the developer writes the logic, the test still passes.
    assert "        assert response.status_code < 500, response.text\n" in complete
    errors = _files(result)["app/core/errors.py"]
    assert "app.add_exception_handler(NotImplementedError, _not_implemented)" in errors


def test_the_factories_store_the_records_that_a_record_needs(result: GenerationResult) -> None:
    factories = _files(result)["tests/factories.py"]
    assert "async def make_task(session: AsyncSession, **values: Any) -> Task:" in factories
    assert '        values["project_id"] = str((await make_project(session)).id)\n' in factories
    assert '"Task": itertools.count(1),' in factories


def test_the_app_has_a_dockerfile_and_a_compose_file(result: GenerationResult) -> None:
    files = _files(result)
    dockerfile = files["Dockerfile"]
    assert "# @trace app file" in dockerfile
    assert "ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11" in dockerfile
    uv_sync = "RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \\\n    uv sync --no-dev\n"
    assert uv_sync in dockerfile
    assert "USER app" in dockerfile
    assert dockerfile.count("\nFROM ") == 3
    compose = files["compose.yaml"]
    assert "# @trace app file" in compose
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert "condition: service_completed_successfully" in compose
    assert ".venv\n" in files[".dockerignore"]


def test_the_app_has_logs_rate_limits_and_kubernetes_files(result: GenerationResult) -> None:
    files = _files(result)
    main = files["app/main.py"]
    assert "configure_logging(settings.log_level, as_json=settings.log_json)" in main
    assert "app.add_middleware(RateLimitMiddleware, limiter=app.state.rate_limiter)" in main
    assert "rate_limit_per_minute: int = 0" in files["app/core/config.py"]
    assert "tests/test_logging.py" in files
    assert "tests/test_rate_limit.py" in files
    assert '"--no-access-log"' in files["Dockerfile"]
    kubernetes = {path for path in files if path.startswith("deploy/kubernetes/")}
    assert kubernetes == {
        f"deploy/kubernetes/{name}"
        for name in (
            "kustomization.yaml",
            "deployment.yaml",
            "service.yaml",
            "migrate-job.yaml",
            "config.env",
            "secret.example.env",
        )
    }
    assert "readOnlyRootFilesystem: true" in files["deploy/kubernetes/deployment.yaml"]
    assert "deploy/kubernetes/secret.env\n" in files[".gitignore"]


NAMING = (
    "version: 0\n"
    "app: { name: rooms, title: Rooms }\n"
    "entities:\n"
    "  Room:\n"
    "    crud: [list]\n"
    "    x-fastapi-path: /meeting-rooms\n"
    "    x-fastapi-table: room\n"
    "    fields:\n"
    "      name: { type: string }\n"
    "    relations:\n"
    "      tags: { kind: many_to_many, target: Tag, inverse: rooms }\n"
    "  Tag:\n"
    "    fields:\n"
    "      name: { type: string }\n"
    "    relations:\n"
    "      rooms: { kind: many_to_many, target: Room, inverse: tags, x-fastapi-table: room_tag }\n"
    "  Booking:\n"
    "    fields:\n"
    "      title: { type: string }\n"
    "    relations:\n"
    "      room: { kind: many_to_one, target: Room, x-fastapi-column: room_ref }\n"
)


def test_extension_keys_set_the_table_column_and_url_names(fastapi: Binding) -> None:
    files = _files(generate(load_definition_text(NAMING), fastapi))

    rooms = files["app/features/rooms/models.py"]
    assert '    __tablename__ = "room"\n' in rooms
    # The key of the second side names the join table of the pair.
    assert 'room_tag = Table(\n    "room_tag",' in rooms
    list_rooms = files["app/features/rooms/list_rooms.py"]
    assert 'router = APIRouter(prefix="/meeting-rooms")' in list_rooms
    bookings = files["app/features/bookings/models.py"]
    assert '"room_ref",' in bookings and 'ForeignKey("room.id")' in bookings
    # The API field keeps the name of the relation.
    assert "    room_id: UUID | None" in files["app/features/bookings/schemas.py"]
    migration = files["migrations/versions/0001_schema.py"]
    assert 'sa.Column("room_ref", sa.Uuid(), nullable=True)' in migration
    assert '"fk_bookings_room_ref_room",' in migration


def test_without_the_keys_the_names_follow_the_slice(fastapi: Binding) -> None:
    text = NAMING.replace(", x-fastapi-table: room_tag", "")
    text = text.replace(", x-fastapi-column: room_ref", "")
    text = "\n".join(line for line in text.splitlines() if "x-fastapi-" not in line)
    app = python_app(load_definition_text(text))

    room = app.entity("Room")
    assert (room.table, room.path, room.join_tables[0].name) == ("rooms", "/rooms", "rooms_tags")
    assert [(r.fk, r.fk_attr) for r in app.entity("Booking").relations] == [("room_id", "room_id")]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("x-fastapi-table: room\n", "x-fastapi-table: bookings\n", "both use the table name"),
        ("/meeting-rooms", "/bookings", "both use the URL prefix"),
        (", x-fastapi-table: room_tag", ", x-fastapi-table: tag_room", "different values"),
        ("inverse: tags,", "inverse: tags, x-fastapi-column: c,", "has no foreign key column"),
        ("x-fastapi-column", "x-fastapi-table", "has no join table"),
    ],
)
def test_wrong_naming_keys_stop_the_run(fastapi: Binding, old: str, new: str, message: str) -> None:
    text = NAMING.replace(old, new)
    if "different" in message:
        text = text.replace("inverse: rooms }", "inverse: rooms, x-fastapi-table: room_tag }")

    with pytest.raises(Exception, match=message):
        generate(load_definition_text(text), fastapi)


def test_a_computed_field_is_a_property_of_the_model_and_a_read_field(fastapi: Binding) -> None:
    definition = load_definition(EXAMPLES / "room-booking" / "app.yaml")
    files = _files(generate(definition, fastapi))
    model = files["app/features/bookings/models.py"]
    assert "    def cost(self) -> Decimal | None:\n" in model
    assert '        v2 = compute.num(compute.get(self, "room", "hourly_rate"))\n' in model
    assert "        return compute.round_to(v3, 2)\n" in model
    assert 'lazy="selectin"' in model.split("room: Mapped")[1].split(")")[0]
    schemas = files["app/features/bookings/schemas.py"]
    assert schemas.count("cost: Decimal | None\n") == 1
    assert "cost" not in files["migrations/versions/0001_schema.py"]
    assert "app/core/compute.py" in files
    assert "app/core/compute.py" not in _files(generate(load_definition(FIXTURE), fastapi))


def test_the_rules_of_an_entity_are_checks_and_constraints(fastapi: Binding) -> None:
    definition = load_definition(EXAMPLES / "room-booking" / "app.yaml")
    files = _files(generate(definition, fastapi))
    repository = files["app/features/bookings/repository.py"]
    assert repository.count("    await check_rules(session, record)\n") == 2
    assert '    if not compare(record.ends_at, "gt", record.starts_at):\n' in repository
    assert (
        '    if await overlaps(session, record, "starts_at", "ends_at", ["room_id"]):\n'
        in repository
    )
    assert "from app.core.rules import compare, overlaps\n" in repository
    constraint = 'UniqueConstraint("floor", "name", name="uq_rooms_unique_name_per_floor")'
    assert f"        {constraint},\n" in files["app/features/rooms/models.py"]
    assert f"        sa.{constraint},\n" in files["migrations/versions/0001_schema.py"]
    payloads = files["tests/payloads.py"]
    assert '"ends_at": f"2026-01-01T{n % 24:02d}:30:00Z",' in payloads
    assert '"starts_at": f"2026-01-01T{n % 24:02d}:00:00Z",' in payloads
