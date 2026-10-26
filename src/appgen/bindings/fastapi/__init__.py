"""The FastAPI binding: a standalone REST API in Python.

The app uses FastAPI on Python 3.14 and uv. Its code follows a vertical
slice architecture: each entity is a slice in `app/features/<slice>/`
with its router, its operations, its schemas, and its data access.
Pages and the UI are out of the scope of the binding.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints

from appgen.bindings.fastapi.model import (
    COLUMN_KEY,
    DEPLOY_KEY,
    EMBED_KEY,
    EXAMPLE_KEY,
    PATH_KEY,
    RATE_LIMIT_STORE_KEY,
    SEARCH_KEY,
    TABLE_KEY,
    binding_context,
)
from appgen.gen.binding import Binding, ExtensionKey, Output

_SQL_NAME = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
"""A lower case SQL name that PostgreSQL does not cut (63 bytes at most)."""
_URL_PREFIX = Annotated[str, StringConstraints(pattern=r"^(/[a-z0-9][a-z0-9._~-]*)+$")]
"""A URL prefix with one or more segments, for example `/meeting-rooms`."""
_DEPLOY_TARGET = Literal["kubernetes", "knative"]
"""A deployment target (`DEPLOY_TARGETS`)."""

_SLICE = "app/features/{{ py.entity(name).slice }}"
_TESTS = "tests/features/{{ py.entity(name).slice }}"
_OPERATION = "app/features/{{ py.operations[name].slice }}/{{ name }}"
_INTEGRATION = "app/integrations/{{ py_apis[name].module }}"
_SECOND_FACTOR = "definition.auth and definition.auth.password and definition.auth.second_factor"

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
        *(
            Output(
                template=f"deploy/kubernetes/{name}.j2",
                path=f"deploy/kubernetes/{name}",
                when="'kubernetes' in py.deploy",
            )
            for name in (
                "kustomization.yaml",
                "deployment.yaml",
                "service.yaml",
                "migrate-job.yaml",
                "config.env",
                "secret.example.env",
            )
        ),
        *(
            Output(
                template=f"deploy/knative/{name}.j2",
                path=f"deploy/knative/{name}",
                when="'knative' in py.deploy",
            )
            for name in ("service.yaml", "migrate-job.yaml")
        ),
        Output(template="dockerignore.j2", path=".dockerignore"),
        Output(template="package.py.j2", path="app/__init__.py"),
        Output(template="app/main.py.j2", path="app/main.py"),
        Output(template="package.py.j2", path="app/core/__init__.py"),
        Output(template="alembic.ini.j2", path="alembic.ini"),
        Output(template="migrations/env.py.j2", path="migrations/env.py"),
        Output(template="migrations/script.py.mako.j2", path="migrations/script.py.mako"),
        # The first migration is created once: appgen never changes it, so
        # that a database with data can get the next migrations (ADR 0009).
        Output(
            template="migrations/versions/0001_schema.py.j2",
            path="migrations/versions/0001_schema.py",
            extension=True,
        ),
        Output(template="app/models.py.j2", path="app/models.py"),
        Output(template="app/core/config.py.j2", path="app/core/config.py"),
        Output(template="app/core/db.py.j2", path="app/core/db.py"),
        Output(template="app/core/errors.py.j2", path="app/core/errors.py"),
        Output(template="app/core/pagination.py.j2", path="app/core/pagination.py"),
        Output(template="app/core/search.py.j2", path="app/core/search.py", when="py.full_text"),
        Output(template="app/core/health.py.j2", path="app/core/health.py"),
        Output(template="app/core/logging.py.j2", path="app/core/logging.py"),
        Output(template="app/core/rate_limit.py.j2", path="app/core/rate_limit.py"),
        Output(template="app/core/schemas.py.j2", path="app/core/schemas.py"),
        Output(template="app/core/types.py.j2", path="app/core/types.py"),
        Output(template="app/core/i18n.py.j2", path="app/core/i18n.py", when="i18n"),
        Output(template="app/core/auth.py.j2", path="app/core/auth.py", when="definition.auth"),
        Output(template="app/cli.py.j2", path="app/cli.py"),
        Output(template="app/core/seed.py.j2", path="app/core/seed.py"),
        Output(template="app/core/seed_data.py.j2", path="app/core/seed_data.py"),
        Output(
            template="app/core/providers.py.j2",
            path="app/core/providers.py",
            when="py.providers",
        ),
        *(
            Output(template=f"{path}.j2", path=path, when=_SECOND_FACTOR)
            for path in ("app/core/second_factor.py", "tests/test_second_factor.py")
        ),
        Output(
            template="app/core/messages.py.j2",
            path="app/core/messages.py",
            when="py.message_elements",
        ),
        Output(
            template="app/core/messages_ext.py.j2",
            path="app/core/messages_ext.py",
            when="py.message_elements and not py.smtp",
            extension=True,
        ),
        *(
            Output(template=f"{path}.j2", path=path, when="py.smtp")
            for path in ("app/core/mail.py", "tests/test_mail.py")
        ),
        Output(
            template="app/core/access.py.j2", path="app/core/access.py", when="definition.access"
        ),
        Output(
            template="tests/test_access.py.j2",
            path="tests/test_access.py",
            when="definition.access",
        ),
        Output(template="tests/test_auth.py.j2", path="tests/test_auth.py", when="definition.auth"),
        Output(
            template="tests/test_providers.py.j2",
            path="tests/test_providers.py",
            when="py.providers",
        ),
        Output(
            template="app/core/workflows.py.j2",
            path="app/core/workflows.py",
            when="definition.workflows",
        ),
        Output(
            template="app/core/rules.py.j2",
            path="app/core/rules.py",
            when="py.entities.values() | selectattr('check_rules') | list",
        ),
        Output(
            template="app/core/compute.py.j2",
            path="app/core/compute.py",
            when="py.entities.values() | selectattr('computed') | list",
        ),
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
        Output(
            template="package.py.j2",
            path="app/features/dashboards/__init__.py",
            when="py.dashboards",
        ),
        *(
            Output(
                template=f"app/features/dashboards/{module}.py.j2",
                path=f"app/features/dashboards/{module}.py",
                when="py.dashboards",
            )
            for module in ("router", "schemas", "aggregates")
        ),
        Output(
            template="app/features/dashboards/dashboard.py.j2",
            path="app/features/dashboards/{{ py.dashboards[name].module }}.py",
            for_each="dashboard",
            when="name in py.dashboards",
        ),
        Output(template="package.py.j2", path="tests/__init__.py"),
        Output(template="tests/payloads.py.j2", path="tests/payloads.py"),
        Output(template="tests/test_migrations.py.j2", path="tests/test_migrations.py"),
        Output(template="tests/test_openapi.py.j2", path="tests/test_openapi.py"),
        Output(template="package.py.j2", path="tests/features/__init__.py"),
        Output(template="package.py.j2", path=_TESTS + "/__init__.py", for_each="entity"),
        Output(
            template="tests/features/slice/test_workflow.py.j2",
            path="tests/features/{{ py.entity(element.entity).slice }}/test_{{ name }}_workflow.py",
            for_each="workflow",
        ),
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
        Output(
            template="tests/features/slice/test_translations.py.j2",
            path=_TESTS + "/test_translations.py",
            for_each="entity",
            when="py.entity(name).translatable and i18n_test",
        ),
        Output(
            template="tests/features/slice/test_list_query.py.j2",
            path="tests/features/{{ py.operations[name].slice }}/test_{{ name }}_query.py",
            for_each="operation",
            when="element.kind == 'list'",
        ),
        Output(
            template="package.py.j2",
            path="tests/features/dashboards/__init__.py",
            when="py.dashboards",
        ),
        Output(
            template="tests/features/dashboards/test_dashboard.py.j2",
            path="tests/features/dashboards/test_{{ py.dashboards[name].module }}.py",
            for_each="dashboard",
            when="name in py.dashboards",
        ),
        Output(template="package.py.j2", path="app/integrations/__init__.py", when="py_apis"),
        Output(
            template="app/integrations/http.py.j2",
            path="app/integrations/http.py",
            when="py_apis",
        ),
        Output(template="package.py.j2", path=_INTEGRATION + "/__init__.py", for_each="api"),
        Output(
            template="app/integrations/api/models.py.j2",
            path=_INTEGRATION + "/models.py",
            for_each="api",
        ),
        Output(
            template="app/integrations/api/client.py.j2",
            path=_INTEGRATION + "/client.py",
            for_each="api",
        ),
        Output(
            template="app/integrations/api/router.py.j2",
            path=_INTEGRATION + "/router.py",
            for_each="api",
            when="py_apis[name].expose",
        ),
        Output(
            template="app/integrations/endpoints.py.j2",
            path="app/integrations/endpoints.py",
            when="py_apis.values() | selectattr('expose') | list",
        ),
        Output(template="package.py.j2", path="tests/integrations/__init__.py", when="py_apis"),
        Output(
            template="tests/integrations/mocks.py.j2",
            path="tests/integrations/mocks.py",
            when="py_apis",
        ),
        Output(
            template="tests/integrations/examples.json.j2",
            path="tests/integrations/{{ py_apis[name].module }}_examples.json",
            for_each="api",
        ),
        Output(
            template="tests/integrations/test_api.py.j2",
            path="tests/integrations/test_{{ py_apis[name].module }}.py",
            for_each="api",
            when="py_apis[name].methods",
        ),
        Output(
            template="tests/integrations/test_endpoints.py.j2",
            path="tests/integrations/test_{{ py_apis[name].module }}_endpoints.py",
            for_each="api",
            when="py_apis[name].expose",
        ),
        Output(template="tests/factories.py.j2", path="tests/factories.py"),
        Output(
            template="tests/ordering.py.j2",
            path="tests/ordering.py",
            when="py.entities.values() | map(attribute='query') | selectattr('sort_tests') | list",
        ),
        Output(template="tests/problems.py.j2", path="tests/problems.py"),
        Output(template="tests/conftest.py.j2", path="tests/conftest.py"),
        Output(template="tests/test_health.py.j2", path="tests/test_health.py"),
        Output(template="tests/test_seed.py.j2", path="tests/test_seed.py"),
        Output(template="tests/test_logging.py.j2", path="tests/test_logging.py"),
        Output(template="tests/test_rate_limit.py.j2", path="tests/test_rate_limit.py"),
        Output(template="tests/test_i18n.py.j2", path="tests/test_i18n.py", when="i18n"),
    ),
    covers=frozenset(
        {"app", "entity", "field", "relation", "operation", "param"}
        | {"entity_compare_rule", "entity_unique_rule", "entity_overlap_rule"}
        | {"workflow", "transition"}
        | {"auth", "sign_up", "email_verification", "password_reset", "provider", "second_factor"}
        | {"access", "role", "record_rule"}
        | {"api", "api_operation"}
        | {"translations", "language"}
        | {"entity_seed", "seed_record"}
    ),
    excludes=frozenset({"page", "ui"}),
    gap_rule=Output(template="gap.md.j2", path="gaps/{{ element_id }}.md"),
    context=binding_context,
    stub_markers=("TODO(appgen)", "NotImplementedError"),
    extension_keys=(
        ExtensionKey(
            name=EMBED_KEY,
            kinds=frozenset({"relation"}),
            type=bool,
            description="True: the read schema embeds the related record as an object.",
        ),
        ExtensionKey(
            name=EXAMPLE_KEY,
            kinds=frozenset({"field", "param"}),
            type=JsonValue,
            description="A valid sample value of the field for the generated tests.",
        ),
        ExtensionKey(
            name=PATH_KEY,
            kinds=frozenset({"entity"}),
            type=_URL_PREFIX,
            description="The URL prefix of the router of the entity, for example `/meeting-rooms`.",
        ),
        ExtensionKey(
            name=TABLE_KEY,
            kinds=frozenset({"entity", "relation"}),
            type=_SQL_NAME,
            description="The table of the entity, or the join table of a many-to-many relation.",
        ),
        ExtensionKey(
            name=COLUMN_KEY,
            kinds=frozenset({"relation"}),
            type=_SQL_NAME,
            description=(
                "The foreign key column of a many-to-one or owning one-to-one relation. "
                "The API field keeps its name."
            ),
        ),
        ExtensionKey(
            name=RATE_LIMIT_STORE_KEY,
            kinds=frozenset({"app"}),
            type=Literal["memory", "redis"],
            description=(
                "The store of the rate limit: `memory` (default) or `redis`, which adds "
                "the setting `RATE_LIMIT_STORE_URL`: all replicas share one limit."
            ),
        ),
        ExtensionKey(
            name=DEPLOY_KEY,
            kinds=frozenset({"app"}),
            type=_DEPLOY_TARGET | Annotated[list[_DEPLOY_TARGET], Field(min_length=1)],
            description=(
                "The deployment targets: `kubernetes` (default, Kustomize) or `knative` "
                "(a Knative Service that Google Cloud Run accepts too), or a list of both."
            ),
        ),
        ExtensionKey(
            name=SEARCH_KEY,
            kinds=frozenset({"app"}),
            type=Literal["like", "fulltext"],
            description=(
                "The search of the list endpoints: `like` (default, `ILIKE` for each word) or "
                "`fulltext` (the full-text search of Postgres, with a GIN index)."
            ),
        ),
    ),
    extension_prefix="x-fastapi-",
)
