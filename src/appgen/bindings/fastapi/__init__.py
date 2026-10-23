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
        Output(template="package.py.j2", path="app/__init__.py"),
        Output(template="app/main.py.j2", path="app/main.py"),
        Output(template="package.py.j2", path="app/core/__init__.py"),
        Output(template="app/core/config.py.j2", path="app/core/config.py"),
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
            template="app/features/slice/schemas.py.j2",
            path=_SLICE + "/schemas.py",
            for_each="entity",
        ),
        Output(template="package.py.j2", path="tests/__init__.py"),
        Output(template="tests/payloads.py.j2", path="tests/payloads.py"),
        Output(template="package.py.j2", path="tests/features/__init__.py"),
        Output(template="package.py.j2", path=_TESTS + "/__init__.py", for_each="entity"),
        Output(
            template="tests/features/slice/test_schemas.py.j2",
            path=_TESTS + "/test_schemas.py",
            for_each="entity",
        ),
        Output(template="tests/conftest.py.j2", path="tests/conftest.py"),
        Output(template="tests/test_health.py.j2", path="tests/test_health.py"),
    ),
    covers=frozenset({"app", "entity", "field", "relation"}),
    excludes=frozenset({"page", "ui"}),
    gap_rule=Output(template="gap.md.j2", path="gaps/{{ element_id }}.md"),
    context=binding_context,
)
