"""The template values of the Next.js binding.

The templates get these values as `nextjs`. They hold the names and the
paths that the Next.js app uses for the elements of a definition, so that
the templates do not compute them again in Jinja2.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from appgen.bindings.nextjs import versions
from appgen.bindings.nextjs.db import belongs_to, build_tables, seed_tables
from appgen.bindings.nextjs.jobs import cron_jobs, ts_jobs
from appgen.bindings.nextjs.totals import repository_totals
from appgen.bindings.nextjs.webhooks import ts_webhooks
from appgen.bindings.shared import shadcn
from appgen.bindings.shared.auth import auth_pages, record_rules
from appgen.bindings.shared.events import has_events
from appgen.bindings.shared.forms import FormContext
from appgen.bindings.shared.i18n import text_helpers
from appgen.bindings.shared.integrations import ts_apis, ts_connections
from appgen.bindings.shared.lines import lines_operations
from appgen.bindings.shared.theme import build_theme
from appgen.bindings.shared.totals import total_keys
from appgen.bindings.shared.typescript import has_history
from appgen.bindings.shared.ui import ui_plan
from appgen.bindings.shared.views import ViewContext
from appgen.dsl.model import AppDefinition, Page
from appgen.dsl.rules import EntityCompareRule
from appgen.gen.naming import camel, kebab, pascal

RATE_LIMIT_STORE_KEY = "x-nextjs-rate-limit-store"
"""The extension key of the app that selects the store of the rate limit: `memory` or `redis`."""
DEPLOY_KEY = "x-nextjs-deploy"
"""The extension key of the app that selects the deployment targets: one target or a list."""
DEPLOY_TARGETS = ("kubernetes", "knative")
"""The deployment targets, in the order of the README. `kubernetes` is the default."""

FSD_LAYERS: tuple[tuple[str, str], ...] = (
    ("app", "The app layer: global styles, providers, and the app configuration."),
    ("pages", "The pages layer: one slice for each page of the app definition."),
    ("widgets", "The widgets layer: large UI blocks, for example the app shell and the views."),
    ("features", "The features layer: one slice for each operation, with its server action."),
    ("entities", "The entities layer: one slice for each entity, with its data access."),
    ("shared", "The shared layer: UI components, the database client, and utilities."),
)
"""The layers of Feature-Sliced Design in `src/`, from top to bottom.

A layer imports only the layers below it.
"""


@dataclass(frozen=True, slots=True)
class PageInfo:
    """The names and the paths of a page in the Next.js app."""

    name: str
    page: Page
    slice: str
    """The FSD slice of the page in `src/pages`, for example `project-detail`."""
    component: str
    """The name of the page component, for example `ProjectDetailPage`."""
    route_dir: str
    """The route folder in `app/`, for example `projects/[id]`, or `` for `/`."""
    params: tuple[str, ...]
    """The names of the path parameters, for example `("id",)`."""
    group: str
    """The route group of the layout of the page, for example `(app-shell)`."""

    @property
    def route_file(self) -> str:
        """The path of the route file, for example `app/(app-shell)/projects/[id]/page.tsx`."""
        return "/".join(part for part in ("app", self.group, self.route_dir, "page.tsx") if part)


def route_dir(path: str) -> tuple[str, tuple[str, ...]]:
    """Return the route folder and the parameter names of a page path.

    `/projects/{id}` gives `projects/[id]` and `("id",)`.
    """
    parts: list[str] = []
    params: list[str] = []
    for segment in path.strip("/").split("/"):
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}"):
            params.append(segment[1:-1])
            parts.append(f"[{segment[1:-1]}]")
        else:
            parts.append(segment)
    return "/".join(parts), tuple(params)


BARE_GROUP = "(bare)"
"""The route group of the pages without a layout."""
EMBED_GROUP = "(embed)"
"""The route group of the pages with `embed`: without the app shell (ADR 0032)."""


def route_group(layout: str | None) -> str:
    """Return the route group of a layout: `app_shell` gives `(app-shell)`."""
    return f"({kebab(layout)})" if layout else BARE_GROUP


def page_info(name: str, page: Page, layout: str | None = None) -> PageInfo:
    """Return the names and the paths of a page with its effective layout."""
    folder, params = route_dir(page.path)
    return PageInfo(
        name=name,
        page=page,
        slice=kebab(name),
        component=f"{pascal(name)}Page",
        route_dir=folder,
        params=params,
        group=EMBED_GROUP if page.embed else route_group(layout),
    )


@dataclass(frozen=True, slots=True)
class SitemapPage:
    """A public page with metadata in the sitemap: its path, or the path of each record."""

    meta_id: str
    """The element ID of the metadata of the page, for example `pages.home.meta`."""
    url: str
    """The path as the body of a JavaScript template literal after the base URL, with the keys
    of `record` for the path parameters."""
    entity: str | None = None
    """The entity of a page of a record: the sitemap has the path of each record."""


def sitemap_pages(definition: AppDefinition) -> list[SitemapPage]:
    """Return the public pages with `meta`, for `sitemap.xml`.

    A page with path parameters is in the sitemap if it has an entity, and
    each parameter is the ID, a required field, or the key of a required
    `many_to_one` relation of the entity: the sitemap has the path of each
    record.
    """
    auth = definition.auth
    found: list[SitemapPage] = []
    for name, page in definition.pages.items():
        if page.meta is None or (auth is not None and name not in auth.public_pages):
            continue
        _, params = route_dir(page.path)
        if not params:
            found.append(SitemapPage(page.meta.id, page.path))
            continue
        entity = definition.entities.get(page.entity or "")
        keys = {param: _record_key(definition, page.entity or "", param) for param in params}
        if entity is None or None in keys.values():
            continue
        url = page.path
        for param, key in keys.items():
            url = url.replace(f"{{{param}}}", f"${{encodeURIComponent(String(record.{key}))}}")
        found.append(SitemapPage(page.meta.id, url, page.entity))
    return found


def _record_key(definition: AppDefinition, entity_name: str, param: str) -> str | None:
    """Return the key of a record that gives a path parameter, or None.

    The key is the ID, a required field, or the key of a required
    `many_to_one` relation: each record has a value for it.
    """
    entity = definition.entities.get(entity_name)
    if entity is None:
        return None
    field = entity.fields.get(param)
    if param == "id" or (field is not None and field.required):
        return camel(param)
    relation = entity.relations.get(param.removesuffix("_id"))
    if (
        param.endswith("_id")
        and relation is not None
        and relation.kind == "many_to_one"
        and relation.required
    ):
        return camel(param.removesuffix("_id")) + "Id"
    return None


def route_source(path: str) -> str:
    """Return the `source` of a page path in `next.config.ts`: `/rooms/{id}` gives
    `/rooms/:id`."""
    return re.sub(r"\{([^}]+)\}", r":\1", path)


def frame_headers(definition: AppDefinition) -> list[tuple[str, str, str]]:
    """Return the page ID, the `source`, and the `frame-ancestors` of each page with `embed`
    (ADR 0032)."""
    return [
        (page.id, route_source(page.path), " ".join(["'self'", *page.embed]))
        for page in definition.pages.values()
        if page.embed
    ]


def package_json(definition: AppDefinition) -> dict[str, Any]:
    """Return the content of `package.json`, with the packages sorted by name.

    The app gets the npm packages of the shadcn/ui components that it uses,
    with providers `jose` (ADR 0020), with the delivery by SMTP
    `nodemailer`, with the rate limit in Redis `@redis/client`
    (ADR 0013), and with the storage kind `s3` `@aws-sdk/client-s3`
    (ADR 0027).
    """
    components = shadcn.used_components(definition)
    dependencies = {
        **versions.DEPENDENCIES,
        **versions.UI_DEPENDENCIES,
        **{name: versions.COMPONENT_PACKAGES[name] for name in shadcn.packages(components)},
    }
    if "table" in ViewContext(definition).features:
        dependencies |= versions.TABLE_PACKAGES
    if definition.auth is not None and definition.auth.providers:
        dependencies |= versions.PROVIDER_PACKAGES
    if definition.auth is not None and definition.auth.second_factor is not None:
        dependencies |= versions.SECOND_FACTOR_PACKAGES
    if definition.storage is not None and definition.storage.kind == "s3":
        dependencies |= versions.S3_PACKAGES
    if uses_smtp(definition):
        dependencies |= versions.SMTP_PACKAGES
    if uses_redis(definition):
        dependencies |= versions.REDIS_PACKAGES
    dev_dependencies = {**versions.DEV_DEPENDENCIES, **versions.UI_DEV_DEPENDENCIES}
    return {
        "name": definition.app.name,
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "packageManager": f"pnpm@{versions.PNPM_VERSION}",
        "engines": {"node": ">=20.9.0"},
        "scripts": {
            "dev": "next dev",
            "build": "next build",
            "build:migrate": (
                "esbuild src/shared/db/run-migrate.ts --bundle --platform=node --format=esm"
                " --outfile=.next/migrate.mjs"
            ),
            "start": "next start",
            "lint": "eslint --max-warnings 0",
            "typecheck": "next typegen && tsc --noEmit",
            "db:generate": "drizzle-kit generate",
            "db:migrate": "drizzle-kit migrate",
            "db:push": "drizzle-kit push",
            "db:studio": "drizzle-kit studio",
            "db:seed": "tsx src/shared/db/run-seed.ts",
        },
        "dependencies": dict(sorted(dependencies.items())),
        "devDependencies": dict(sorted(dev_dependencies.items())),
    }


def uses_smtp(definition: AppDefinition) -> bool:
    """Return True if the app sends the messages of the sign-in by SMTP (`auth.delivery: smtp`).

    The app has these messages with a password reset or a verification of the email address.
    """
    auth = definition.auth
    if auth is None or auth.delivery != "smtp":
        return False
    return auth.password_reset is not None or (
        auth.sign_up is not None and auth.sign_up.verify_email is not None
    )


def uses_redis(definition: AppDefinition) -> bool:
    """Return True if the rate limit can count in Redis (`RATE_LIMIT_STORE_URL`)."""
    return definition.app.extensions.get(RATE_LIMIT_STORE_KEY) == "redis"


UPLOAD_MARGIN = 1024 * 1024
"""The bytes of a server action body for the rest of the form data of an upload."""


def upload_limit(definition: AppDefinition) -> int | None:
    """Return the largest body of a server action with a file, or None without file fields.

    Next.js accepts server action bodies of 1 MB by default (ADR 0027).
    """
    sizes = [
        f.size_limit for entity in definition.entities.values() for f in entity.file_fields.values()
    ]
    return max(sizes) + UPLOAD_MARGIN if sizes else None


def deploy_targets(definition: AppDefinition) -> tuple[str, ...]:
    """Return the deployment targets in a fixed order (the key schema checks the names)."""
    value = definition.app.extensions.get(DEPLOY_KEY)
    if value is None:
        return ("kubernetes",)
    names = {value} if isinstance(value, str) else set(cast(list[str], value))
    return tuple(target for target in DEPLOY_TARGETS if target in names)


def context(definition: AppDefinition) -> dict[str, Any]:
    """Return the template values of the Next.js binding for a definition."""
    plan = ui_plan(definition)
    pages = {
        name: page_info(name, page, plan.pages[name].layout)
        for name, page in definition.pages.items()
    }
    components = shadcn.used_components(definition)
    ui = definition.ui
    default_layout = ui.defaults.layout if ui is not None and ui.defaults else None
    groups = {info.layout for info in plan.pages.values() if not info.embedded}
    theme = ui.theme if ui is not None else None
    tables = build_tables(definition)
    by_entity = {table.entity: table for table in tables}
    rules = record_rules(definition)
    jobs = ts_jobs(definition, by_entity)
    seed = seed_tables(definition, tables)
    apis = ts_apis(definition)
    return {
        "ts_apis": apis,
        "ts_connections": ts_connections(apis),
        "ts_webhooks": ts_webhooks(definition),
        "theme": build_theme(definition),
        "theme_element": theme.id if theme is not None else "app",
        "ui_plan": plan,
        "ui_views": ViewContext(definition, forms=True, api_server=True),
        "ui_forms": FormContext(definition),
        "auth_pages": auth_pages(definition, server=True),
        "record_rules": rules,
        # The keys of the totals in the records (ADR 0034), by entity.
        "record_totals": {
            name: total_keys(definition, name, api=False) for name in definition.entities
        },
        # The create and the update operations with lines (ADR 0035), by name.
        "lines_ops": lines_operations(definition),
        **text_helpers(definition),
        "nextjs": {
            "default_layout": default_layout,
            "groups": [(layout, route_group(layout)) for layout in sorted(groups, key=str)],
            "default_mode": theme.default_mode if theme is not None else "system",
            "mode_toggle": shadcn.has_mode_toggle(definition),
            "shadcn": [component.name for component in components],
            "hooks": shadcn.hooks(components),
            "layers": FSD_LAYERS,
            "tables": tables,
            "tables_by_entity": by_entity,
            # The conditions of the owner paths of the record rules (ADR 0025).
            "owner_conditions": {
                entity: belongs_to(r.path, by_entity, 4)
                for entity, r in rules.items()
                if r.path and not r.direct
            },
            "seed": seed,
            "seed_files": any(table.files for table in seed),
            "pages": pages,
            "package_json": package_json(definition),
            "node_version": versions.NODE_VERSION,
            "curl_version": versions.CURL_VERSION,
            "redis": uses_redis(definition),
            "smtp": uses_smtp(definition),
            "deploy": deploy_targets(definition),
            # The jobs (ADR 0029): a route handler and a module for each job, and the CronJobs
            # that call the routes.
            "jobs": jobs,
            "cron_jobs": cron_jobs(f"{definition.app.name}-web", jobs),
            "upload_limit": upload_limit(definition),
            # The events (ADR 0031): the repositories run their operations.
            "events": has_events(definition),
            # The totals of the related records (ADR 0034): the subqueries of the repositories.
            "totals": repository_totals(definition, by_entity),
            # The compare rules with totals of the lines (ADR 0034): the repositories check
            # them after a change.
            "total_rules": any(
                isinstance(rule, EntityCompareRule) and rule.totals
                for entity in definition.entities.values()
                for rule in entity.rules.values()
            ),
            # The change log (ADR 0040): one table for all entities, and the helpers.
            "history": has_history(definition),
            "frame_headers": frame_headers(definition),
            # The public pages with metadata: `sitemap.xml` and `robots.txt`.
            "sitemap": sitemap_pages(definition),
        },
    }
