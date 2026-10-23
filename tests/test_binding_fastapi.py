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
    assert result.excluded_kinds == ("page", "ui")
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


def test_the_factories_store_the_records_that_a_record_needs(result: GenerationResult) -> None:
    factories = _files(result)["tests/factories.py"]
    assert "async def make_task(session: AsyncSession, **values: Any) -> Task:" in factories
    assert '        values["project_id"] = str((await make_project(session)).id)\n' in factories
    assert '"Task": itertools.count(1),' in factories
