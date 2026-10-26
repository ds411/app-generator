"""The template values of the Next.js binding.

The templates get these values as `nextjs`. They hold the names and the
paths that the Next.js app uses for the elements of a definition, so that
the templates do not compute them again in Jinja2.
"""

from dataclasses import dataclass
from typing import Any, cast

from appgen.bindings.nextjs import versions
from appgen.bindings.nextjs.db import belongs_to, build_tables, seed_tables
from appgen.bindings.nextjs.jobs import cron_jobs, ts_jobs
from appgen.bindings.nextjs.webhooks import ts_webhooks
from appgen.bindings.shared import shadcn
from appgen.bindings.shared.auth import auth_pages, record_rules
from appgen.bindings.shared.files import reject_file_fields
from appgen.bindings.shared.forms import FormContext
from appgen.bindings.shared.i18n import text_helpers
from appgen.bindings.shared.integrations import ts_apis
from appgen.bindings.shared.theme import build_theme
from appgen.bindings.shared.ui import ui_plan
from appgen.bindings.shared.views import ViewContext
from appgen.dsl.model import AppDefinition, Page
from appgen.gen.naming import kebab, pascal

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
        group=route_group(layout),
    )


def package_json(definition: AppDefinition) -> dict[str, Any]:
    """Return the content of `package.json`, with the packages sorted by name.

    The app gets the npm packages of the shadcn/ui components that it uses,
    with providers `jose` (ADR 0020), with the delivery by SMTP
    `nodemailer`, and with the rate limit in Redis `@redis/client`
    (ADR 0013).
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


def deploy_targets(definition: AppDefinition) -> tuple[str, ...]:
    """Return the deployment targets in a fixed order (the key schema checks the names)."""
    value = definition.app.extensions.get(DEPLOY_KEY)
    if value is None:
        return ("kubernetes",)
    names = {value} if isinstance(value, str) else set(cast(list[str], value))
    return tuple(target for target in DEPLOY_TARGETS if target in names)


def context(definition: AppDefinition) -> dict[str, Any]:
    """Return the template values of the Next.js binding for a definition."""
    reject_file_fields(definition, "nextjs")
    plan = ui_plan(definition)
    pages = {
        name: page_info(name, page, plan.pages[name].layout)
        for name, page in definition.pages.items()
    }
    components = shadcn.used_components(definition)
    ui = definition.ui
    default_layout = ui.defaults.layout if ui is not None and ui.defaults else None
    groups = {info.layout for info in plan.pages.values()}
    theme = ui.theme if ui is not None else None
    tables = build_tables(definition)
    by_entity = {table.entity: table for table in tables}
    rules = record_rules(definition)
    jobs = ts_jobs(definition, by_entity)
    return {
        "ts_apis": ts_apis(definition),
        "ts_webhooks": ts_webhooks(definition),
        "theme": build_theme(definition),
        "theme_element": theme.id if theme is not None else "app",
        "ui_plan": plan,
        "ui_views": ViewContext(definition, forms=True, api_server=True),
        "ui_forms": FormContext(definition),
        "auth_pages": auth_pages(definition, server=True),
        "record_rules": rules,
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
            "seed": seed_tables(definition, tables),
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
        },
    }
