"""Tests of the production files of the Next.js app: the rate limit, the health route, and deploy/.

ADR 0013 describes the settings. `scripts/check-nextjs.sh` builds the app,
checks the shared limit in Redis (`scripts/check_shared_rate_limit.py`),
and validates the deployment files against their schemas
(`scripts/check_deploy_files.py`). These tests check the output of the
generator only.
"""

import json
import re
from pathlib import Path

import pytest

from appgen.bindings.nextjs import versions
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen import Binding, GenerationResult, find_binding, generate
from appgen.gen.extensions import check_extensions

EXAMPLES = Path(__file__).parent.parent / "examples"
TRACKER = EXAMPLES / "project-tracker" / "app.yaml"
ROOM_BOOKING = EXAMPLES / "room-booking" / "app.yaml"
KUBERNETES = {
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


@pytest.fixture(scope="module")
def nextjs() -> Binding:
    return find_binding("nextjs")


@pytest.fixture(scope="module")
def result(nextjs: Binding) -> GenerationResult:
    return generate(load_definition(TRACKER), nextjs)


def _files(result: GenerationResult) -> dict[str, str]:
    return {f.path: f.content for f in result.files}


def _with_app_keys(path: Path, keys: str) -> AppDefinition:
    text = re.sub(r"(?m)^app:\n", f"app:\n{keys}", path.read_text(), count=1)
    return load_definition_text(text, str(path))


def test_the_proxy_limits_the_requests_in_memory(result: GenerationResult) -> None:
    files = _files(result)
    proxy = files["proxy.ts"]
    assert "export function proxy(request: NextRequest) {\n  return limitRate(request);" in proxy
    assert 'matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]' in proxy
    limit = files["src/shared/lib/rate-limit.ts"]
    assert "export class MemoryLimiter {" in limit
    assert "RedisLimiter" not in limit and "@redis/client" not in limit
    assert 'const EXEMPT_PATHS = new Set(["/health"]);' in limit
    assert 'process.env.RATE_LIMIT_PER_MINUTE ?? ""' in limit
    assert 'process.env.RATE_LIMIT_TRUSTED_HOPS ?? ""' in limit
    assert '"retry-after": String(hit.wait)' in limit
    # The project tracker has translations: the message of a 429 is in the language of the request.
    assert (
        'languageStore.run(language, () => t("Send not more than {limit} requests in each minute.",'
        " { limit }))"
    ) in limit
    assert 'matchLanguage(request.headers.get("accept-language"))' in limit
    package = json.loads(files["package.json"])
    assert "@redis/client" not in package["dependencies"]
    env = files[".env.example"]
    assert "RATE_LIMIT_PER_MINUTE=0\n" in env and "RATE_LIMIT_TRUSTED_HOPS=1\n" in env
    assert "RATE_LIMIT_STORE_URL" not in env
    compose = files["compose.yaml"]
    # Local runs have no limit: the UI tests make more requests than a user.
    assert "RATE_LIMIT_PER_MINUTE: ${RATE_LIMIT_PER_MINUTE:-0}" in compose
    assert "RATE_LIMIT_PER_MINUTE=1200\n" in files["deploy/kubernetes/config.env"]
    assert "redis" not in compose


def test_the_health_route_checks_the_database(result: GenerationResult) -> None:
    route = _files(result)["app/health/route.ts"]
    assert "// @trace app file" in route
    assert "await getDb().execute(sql`select 1`);" in route
    assert 'return Response.json({ status: "error" }, { status: 503 });' in route
    assert 'export const dynamic = "force-dynamic";' in route


def test_the_redis_store_adds_redis_and_its_settings(nextjs: Binding) -> None:
    definition = _with_app_keys(TRACKER, "  x-nextjs-rate-limit-store: redis\n")
    files = _files(generate(definition, nextjs))

    package = json.loads(files["package.json"])
    assert package["dependencies"]["@redis/client"] == versions.REDIS_PACKAGES["@redis/client"]
    limit = files["src/shared/lib/rate-limit.ts"]
    assert 'import { createClient } from "@redis/client";' in limit
    assert "export class RedisLimiter {" in limit
    assert "redis.multi().incr(key).expire(key, WINDOW_SECONDS).exec()" in limit
    assert "disableOfflineQueue: true" in limit
    assert "store ? new RedisLimiter(limit, store) : new MemoryLimiter(limit)" in limit
    assert 'failClosed: process.env.RATE_LIMIT_FAIL_CLOSED === "true"' in limit
    assert 't("The store of the rate limit is not available. Try again later.")' in limit
    assert "return textResponse(text, 503, {});" in limit
    env = files[".env.example"]
    assert "RATE_LIMIT_STORE_URL=\n" in env and "RATE_LIMIT_FAIL_CLOSED=false\n" in env
    compose = files["compose.yaml"]
    assert "  redis:\n" in compose and "profiles: [redis]" in compose
    assert "RATE_LIMIT_STORE_URL: ${RATE_LIMIT_STORE_URL:-}" in compose
    assert "RATE_LIMIT_FAIL_CLOSED=false" in files["deploy/kubernetes/config.env"]
    assert "RATE_LIMIT_STORE_URL=redis://" in files["deploy/kubernetes/secret.example.env"]
    assert "RATE_LIMIT_STORE_URL" in files["README.md"]


def test_the_memory_store_gives_the_same_app_as_no_key(
    result: GenerationResult, nextjs: Binding
) -> None:
    definition = _with_app_keys(TRACKER, "  x-nextjs-rate-limit-store: memory\n")
    assert _files(generate(definition, nextjs)) == _files(result)


def test_the_kubernetes_files_are_the_default_target(result: GenerationResult) -> None:
    files = _files(result)
    assert {path for path in files if path.startswith("deploy/")} == KUBERNETES
    deployment = files["deploy/kubernetes/deployment.yaml"]
    assert "name: project-tracker-web\n" in deployment
    assert "runAsUser: 1000\n" in deployment and "readOnlyRootFilesystem: true" in deployment
    assert "- name: HOSTNAME\n              value: 0.0.0.0\n" in deployment
    assert "path: /health\n" in deployment and "containerPort: 3000\n" in deployment
    assert "mountPath: /app/.next/cache\n" in deployment
    job = files["deploy/kubernetes/migrate-job.yaml"]
    assert 'command: ["node", "migrate.mjs"]' in job
    secret = files["deploy/kubernetes/secret.example.env"]
    assert (
        "DATABASE_URL=postgres://app:change-me@postgres.example.com:5432/project_tracker" in secret
    )
    assert "EXCHANGE_RATES_API_KEY=\n" in secret
    config = files["deploy/kubernetes/config.env"]
    assert "HOLIDAYS_API_URL=https://date.nager.at/api/v3\n" in config
    assert "/deploy/kubernetes/secret.env\n" in files[".gitignore"]
    assert "\ndeploy\n" in files[".dockerignore"]
    readme = files["README.md"]
    assert "## Production" in readme and "- Kubernetes:" in readme
    assert "- Knative and Google Cloud Run:" not in readme


def test_the_image_has_the_script_of_the_migration_job(result: GenerationResult) -> None:
    files = _files(result)
    dockerfile = files["Dockerfile"]
    assert "RUN pnpm build && pnpm build:migrate\n" in dockerfile
    assert "COPY --from=build --chown=node:node /app/.next/migrate.mjs ./migrate.mjs" in dockerfile
    package = json.loads(files["package.json"])
    assert "src/shared/db/run-migrate.ts --bundle" in package["scripts"]["build:migrate"]
    assert package["devDependencies"]["esbuild"] == versions.DEV_DEPENDENCIES["esbuild"]
    script = files["src/shared/db/run-migrate.ts"]
    assert 'import { migrate } from "drizzle-orm/postgres-js/migrator";' in script
    assert 'await migrate(drizzle(client), { migrationsFolder: "drizzle" });' in script


def test_the_knative_target_replaces_the_kubernetes_files(nextjs: Binding) -> None:
    definition = _with_app_keys(TRACKER, "  x-nextjs-deploy: knative\n")
    files = _files(generate(definition, nextjs))

    deploy = {path for path in files if path.startswith("deploy/")}
    assert deploy == {"deploy/knative/service.yaml", "deploy/knative/migrate-job.yaml"}
    assert "deploy/kubernetes" not in files[".gitignore"]
    readme = files["README.md"]
    assert "- Knative and Google Cloud Run:" in readme and "- Kubernetes:" not in readme
    assert "gcloud run jobs deploy project-tracker-web-migrate" in readme
    assert "--command node --args migrate.mjs" in readme
    assert "gcloud secrets create project-tracker-web-exchange-rates-api-key" in readme


def test_the_knative_service_uses_only_fields_that_cloud_run_takes(nextjs: Binding) -> None:
    keys = "  x-nextjs-deploy: [knative, kubernetes]\n  x-nextjs-rate-limit-store: redis\n"
    files = _files(generate(_with_app_keys(ROOM_BOOKING, keys), nextjs))

    assert set(files) >= KUBERNETES
    service = files["deploy/knative/service.yaml"]
    assert "apiVersion: serving.knative.dev/v1\nkind: Service\n" in service
    assert "envFrom:" not in service and "securityContext:" not in service
    assert "- name: http1\n              containerPort: 3000\n" in service
    assert "- name: HOSTNAME\n              value: 0.0.0.0\n" in service
    assert "startupProbe:\n            httpGet:\n              path: /health\n" in service
    for secret in ("database-url", "rate-limit-store-url", "auth-secret", "company-client-secret"):
        assert f"name: room-booking-web-{secret}\n                  key: latest\n" in service
    assert "- name: RATE_LIMIT_FAIL_CLOSED\n" in service
    assert "- name: PUBLIC_URL\n" in service and "- name: COMPANY_ISSUER\n" in service
    job = files["deploy/knative/migrate-job.yaml"]
    assert 'command: ["node", "migrate.mjs"]' in job
    assert "name: room-booking-web-database-url" in job


@pytest.mark.parametrize(
    ("keys", "code"),
    [
        ("  x-nextjs-rate-limit-store: memcached\n", "invalid-value"),
        ("  x-nextjs-deploy: lambda\n", "invalid-value"),
        ("  x-nextjs-deploy: []\n", "invalid-value"),
        ("  x-nextjs-deploy: [kubernetes, swarm]\n", "invalid-value"),
        ("  x-nextjs-rate-limit: redis\n", "unknown-key"),
    ],
)
def test_the_keys_of_the_binding_are_checked(nextjs: Binding, keys: str, code: str) -> None:
    definition = _with_app_keys(TRACKER, keys)
    assert validate_definition(definition) == []
    assert [d.code for d in check_extensions(definition, [nextjs])] == [code]
