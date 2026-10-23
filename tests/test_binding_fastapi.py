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
    assert 'APIRouter(prefix="/tasks", tags=["Tasks"])' in files["app/features/tasks/router.py"]


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
