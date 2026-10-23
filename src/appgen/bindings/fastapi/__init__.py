"""The FastAPI binding: a standalone REST API in Python.

The app uses FastAPI on Python 3.14 and uv. Its code follows a vertical
slice architecture: each entity is a slice in `app/features/<slice>/`
with its router, its operations, its schemas, and its data access.
Pages and the UI are out of the scope of the binding.
"""

from pathlib import Path

from appgen.bindings.fastapi.model import binding_context
from appgen.gen.binding import Binding, Output

_SLICE = "app/features/{{ py.entity(name).slice }}"
_TESTS = "tests/features/{{ py.entity(name).slice }}"
_OPERATION = "app/features/{{ py.operations[name].slice }}/{{ name }}"

BINDING = Binding(
    name="fastapi",
    description="A FastAPI REST API with vertical slices, uv, and Python 3.14.",
    template_dir=Path(__file__).parent / "templates",
    outputs=(
        Output(template="pyproject.toml.j2", path="pyproject.toml"),
        Output(template="python-version.j2", path=".python-version"),
        Output(template="gitignore.j2", path=".gitignore"),
        Output(template="env.example.j2", path=".env.example"),
        Output(template="README.md.j2", path="README.md"),
        Output(template="Dockerfile.j2", path="Dockerfile"),
        Output(template="compose.yaml.j2", path="compose.yaml"),
        Output(template="dockerignore.j2", path=".dockerignore"),
        Output(template="package.py.j2", path="app/__init__.py"),
        Output(template="app/main.py.j2", path="app/main.py"),
        Output(template="package.py.j2", path="app/core/__init__.py"),
        Output(template="alembic.ini.j2", path="alembic.ini"),
        Output(template="migrations/env.py.j2", path="migrations/env.py"),
        Output(template="migrations/script.py.mako.j2", path="migrations/script.py.mako"),
        Output(
            template="migrations/versions/0001_schema.py.j2",
            path="migrations/versions/0001_schema.py",
        ),
        Output(template="app/models.py.j2", path="app/models.py"),
        Output(template="app/core/config.py.j2", path="app/core/config.py"),
        Output(template="app/core/db.py.j2", path="app/core/db.py"),
        Output(template="app/core/errors.py.j2", path="app/core/errors.py"),
        Output(template="app/core/pagination.py.j2", path="app/core/pagination.py"),
        Output(template="app/core/health.py.j2", path="app/core/health.py"),
        Output(template="app/core/schemas.py.j2", path="app/core/schemas.py"),
        Output(template="app/core/types.py.j2", path="app/core/types.py"),
        Output(template="package.py.j2", path="app/features/__init__.py"),
        Output(template="package.py.j2", path=_SLICE + "/__init__.py", for_each="entity"),
        Output(
            template="app/features/slice/router.py.j2",
            path=_SLICE + "/router.py",
            for_each="entity",
        ),
        Output(
            template="app/features/slice/enums.py.j2",
            path=_SLICE + "/enums.py",
            for_each="entity",
            when="py.entity(name).enums",
        ),
        Output(
            template="app/features/slice/models.py.j2",
            path=_SLICE + "/models.py",
            for_each="entity",
        ),
        Output(
            template="app/features/slice/repository.py.j2",
            path=_SLICE + "/repository.py",
            for_each="entity",
        ),
        Output(
            template="app/features/slice/operation.py.j2",
            path=_OPERATION + ".py",
            for_each="operation",
            when="element.kind != 'custom'",
        ),
        Output(
            template="app/features/slice/custom_gen.py.j2",
            path=_OPERATION + "_gen.py",
            for_each="operation",
            when="element.kind == 'custom'",
        ),
        Output(
            template="app/features/slice/custom_ext.py.j2",
            path=_OPERATION + "_ext.py",
            for_each="operation",
            when="element.kind == 'custom'",
            extension=True,
        ),
        Output(
            template="app/features/slice/validation_ext.py.j2",
            path=_SLICE + "/validation_ext.py",
            for_each="entity",
            extension=True,
        ),
        Output(
            template="app/features/slice/schemas.py.j2",
            path=_SLICE + "/schemas.py",
            for_each="entity",
        ),
        Output(template="package.py.j2", path="tests/__init__.py"),
        Output(template="tests/payloads.py.j2", path="tests/payloads.py"),
        Output(template="tests/test_migrations.py.j2", path="tests/test_migrations.py"),
        Output(template="tests/test_openapi.py.j2", path="tests/test_openapi.py"),
        Output(template="package.py.j2", path="tests/features/__init__.py"),
        Output(template="package.py.j2", path=_TESTS + "/__init__.py", for_each="entity"),
        Output(
            template="tests/features/slice/test_schemas.py.j2",
            path=_TESTS + "/test_schemas.py",
            for_each="entity",
        ),
        Output(
            template="tests/features/slice/test_operation.py.j2",
            path="tests/features/{{ py.operations[name].slice }}/test_{{ name }}.py",
            for_each="operation",
        ),
        Output(template="tests/factories.py.j2", path="tests/factories.py"),
        Output(template="tests/problems.py.j2", path="tests/problems.py"),
        Output(template="tests/conftest.py.j2", path="tests/conftest.py"),
        Output(template="tests/test_health.py.j2", path="tests/test_health.py"),
    ),
    covers=frozenset({"app", "entity", "field", "relation", "operation", "param"}),
    excludes=frozenset({"page", "ui"}),
    gap_rule=Output(template="gap.md.j2", path="gaps/{{ element_id }}.md"),
    context=binding_context,
)
