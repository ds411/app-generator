"""The Next.js 16 binding: a full-stack TypeScript app.

The app uses the App Router, TypeScript in strict mode, Tailwind CSS,
shadcn/ui, Drizzle ORM with Postgres, and pnpm. Its code follows
Feature-Sliced Design (FSD): the Next.js `app/` folder in the root
holds only the routes, and the FSD layers `app`, `pages`, `widgets`,
`features`, `entities`, and `shared` are folders in `src/`. Each
route renders the page of its slice in `src/pages`.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from appgen.bindings import shared
from appgen.bindings.nextjs import db
from appgen.bindings.nextjs.model import (
    DEPLOY_KEY,
    FSD_LAYERS,
    RATE_LIMIT_STORE_KEY,
    SHARE_GROUP,
    context,
)
from appgen.bindings.shared import forms, shadcn, typescript, ui, views
from appgen.bindings.shared.auth import auth_rules, kind_operations, public_kinds
from appgen.bindings.shared.events import ts_events
from appgen.bindings.shared.gaps import gap_rules, gap_spec
from appgen.bindings.shared.i18n import finish, i18n_rules
from appgen.bindings.shared.notices import notice_rules
from appgen.bindings.shared.sharing import share_rules
from appgen.bindings.shared.totals import rule_side_key
from appgen.dsl.storage import format_size
from appgen.gen.binding import Binding, ExtensionKey, Output

_PAGE = "src/pages/{{ nextjs.pages[name].slice }}"
_ENTITY = "src/entities/{{ name | kebab }}"
_OPERATION = "src/features/{{ name | kebab }}"
_CUSTOM_OP = "element.kind == 'custom'"
_QUERY_OP = "element.kind == 'query'"
_LINES_OP = "element.lines and element.kind in ('create', 'update')"
_INTEGRATION = "src/shared/api/{{ ts_apis[name].folder }}"
_WEBHOOK = "src/features/{{ ts_webhooks[name].slice }}"
_DEPLOY_TARGET = Literal["kubernetes", "knative"]
"""A deployment target (`DEPLOY_TARGETS`)."""
_VERIFY_EMAIL = (
    "definition.auth and definition.auth.sign_up and definition.auth.sign_up.verify_email"
)
_MESSAGES = f"definition.auth and (definition.auth.password_reset or ({_VERIFY_EMAIL}))"
_SECOND_FACTOR = "definition.auth and definition.auth.second_factor"
_LOCAL_FILES = "definition.storage and definition.storage.kind == 'local'"

# The app shell: the layouts, the menus, the breadcrumbs, and the search
# (shared templates, see `appgen.bindings.shared.ui`). Each layout with
# pages is a route group in `app/`.
_APP_SHELL = (
    Output(template="ui/config/pages.ts.j2", path="src/shared/config/pages.ts"),
    Output(template="ui/lib/pages.ts.j2", path="src/shared/lib/pages.ts"),
    Output(template="ui/lib/use-media-query.ts.j2", path="src/shared/lib/use-media-query.ts"),
    Output(template="ui/lib/use-resource.ts.j2", path="src/shared/lib/use-resource.ts"),
    Output(template="src/shared/lib/router.tsx.j2", path="src/shared/lib/router.tsx"),
    Output(
        template="src/shared/lib/access.tsx.j2",
        path="src/shared/lib/access.tsx",
        when="definition.access",
    ),
    Output(template="src/shared/lib/me.tsx.j2", path="src/shared/lib/me.tsx", when="me"),
    Output(
        template="ui/widgets/layout/layout.tsx.j2",
        path="src/widgets/layouts/ui/{{ name | kebab }}-layout.tsx",
        for_each="layout",
    ),
    Output(
        template="ui/widgets/layout/index.ts.j2",
        path="src/widgets/layouts/index.ts",
        when="ui_plan.layouts",
    ),
    Output(
        template="app/group/layout.tsx.j2",
        path="app/({{ name | kebab }})/layout.tsx",
        for_each="layout",
        when="ui_plan.pages_of(name)",
    ),
    Output(
        template="app/group/bare-layout.tsx.j2",
        path="app/(bare)/layout.tsx",
        when="ui_plan.pages_of(none)",
    ),
    Output(
        template="app/group/embed-layout.tsx.j2",
        path="app/(embed)/layout.tsx",
        when="ui_plan.embedded_pages",
    ),
    Output(
        template="app/group/shared-layout.tsx.j2",
        path="app/" + SHARE_GROUP + "/layout.tsx",
        when="shares",
    ),
    Output(template="app/not-found.tsx.j2", path="app/not-found.tsx"),
    Output(
        template="ui/widgets/navigation/menu.tsx.j2",
        path="src/widgets/navigation/ui/{{ name | kebab }}-menu.tsx",
        for_each="menu",
        when="name in ui_plan.menus",
    ),
    Output(
        template="ui/widgets/navigation/index.ts.j2",
        path="src/widgets/navigation/index.ts",
        when="ui_plan.menus",
    ),
    *(
        Output(
            template=f"ui/widgets/breadcrumbs/{template}.j2",
            path=f"src/widgets/page-breadcrumbs/{path}",
            when="ui_plan.breadcrumbs",
        )
        for template, path in (
            ("index.ts", "index.ts"),
            ("page-breadcrumbs.tsx", "ui/page-breadcrumbs.tsx"),
            ("record-labels.ts", "model/record-labels.ts"),
        )
    ),
    Output(
        template="ui/features/search-pages/index.ts.j2",
        path="src/features/search-pages/index.ts",
        when="ui_plan.search",
    ),
    Output(
        template="ui/features/search-pages/page-search.tsx.j2",
        path="src/features/search-pages/ui/page-search.tsx",
        when="ui_plan.search",
    ),
    Output(template="ui/widgets/page-header/index.ts.j2", path="src/widgets/page-header/index.ts"),
    Output(
        template="ui/widgets/page-header/page-header.tsx.j2",
        path="src/widgets/page-header/ui/page-header.tsx",
    ),
    Output(template="src/pages/not-found/index.ts.j2", path="src/pages/not-found/index.ts"),
    Output(
        template="ui/pages/not-found.tsx.j2",
        path="src/pages/not-found/ui/not-found-page.tsx",
    ),
)

# One rule for each shadcn/ui component and hook. The app gets only the
# components that its UI uses (ADR 0003, "Binding map").
_SHADCN = tuple(
    Output(
        template=component.template,
        path=f"src/shared/ui/{name}.tsx",
        when=f"{name!r} in nextjs.shadcn",
    )
    for name, component in sorted(shadcn.registry().items())
)
_HOOKS = tuple(
    Output(
        template=f"shadcn/{hook}.ts.j2",
        path=f"src/shared/lib/{hook}.ts",
        when=f"{hook!r} in nextjs.hooks",
    )
    for hook in sorted({h for c in shadcn.registry().values() for h in c.hooks})
)

BINDING = Binding(
    name="nextjs",
    description="A Next.js 16 app with TypeScript, FSD, and pnpm.",
    template_dir=Path(__file__).parent / "templates",
    shared_template_dirs=(shared.TEMPLATE_DIR,),
    outputs=(
        Output(template="package.json.j2", path="package.json"),
        Output(template="pnpm-workspace.yaml.j2", path="pnpm-workspace.yaml"),
        Output(template="tsconfig.json.j2", path="tsconfig.json"),
        Output(template="next.config.ts.j2", path="next.config.ts"),
        Output(template="eslint.config.mjs.j2", path="eslint.config.mjs"),
        Output(template="postcss.config.mjs.j2", path="postcss.config.mjs"),
        Output(template="gitignore.j2", path=".gitignore"),
        Output(template="Dockerfile.j2", path="Dockerfile"),
        Output(template="dockerignore.j2", path=".dockerignore"),
        Output(template="compose.yaml.j2", path="compose.yaml"),
        *(
            Output(
                template=f"deploy/kubernetes/{name}.j2",
                path=f"deploy/kubernetes/{name}",
                when="'kubernetes' in nextjs.deploy",
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
        Output(
            template="deploy/kubernetes/files-volume.yaml.j2",
            path="deploy/kubernetes/files-volume.yaml",
            when=f"'kubernetes' in nextjs.deploy and {_LOCAL_FILES}",
        ),
        *(
            Output(
                template=f"deploy/knative/{name}.j2",
                path=f"deploy/knative/{name}",
                when="'knative' in nextjs.deploy",
            )
            for name in ("service.yaml", "migrate-job.yaml")
        ),
        *(
            Output(
                template=f"deploy/{target}/jobs.yaml.j2",
                path=f"deploy/{target}/jobs.yaml",
                when=f"{target!r} in nextjs.deploy and nextjs.jobs",
            )
            for target in ("kubernetes", "knative")
        ),
        Output(template="README.md.j2", path="README.md"),
        Output(template="root-pages-readme.md.j2", path="pages/README.md"),
        *(
            Output(template="layer-readme.md.j2", path=f"src/{layer}/README.md")
            for layer, _ in FSD_LAYERS
        ),
        Output(template="app/layout.tsx.j2", path="app/layout.tsx"),
        *_APP_SHELL,
        *views.view_rules(),
        *i18n_rules(),
        Output(
            template="src/shared/lib/i18n-server.ts.j2",
            path="src/shared/lib/i18n-server.ts",
            when="i18n",
        ),
        *auth_rules(),
        *share_rules(),
        *notice_rules(),
        *forms.form_rules(),
        Output(
            template="app/page.tsx.j2",
            path="{{ nextjs.pages[name].route_file }}",
            for_each="page",
        ),
        # The pages of the secret links of the records (ADR 0049).
        Output(
            template="app/shared-page.tsx.j2",
            path="app/" + SHARE_GROUP + "/{{ nextjs.share_routes[name] }}/page.tsx",
            for_each="entity",
            when="name in shares",
        ),
        *(
            Output(template=f"{path}.j2", path=path, when="shares")
            for path in ("src/shared/db/schema/share-links.ts", "src/shared/db/sharing.ts")
        ),
        # The metadata of the pages: the previews of the links, the sitemap, and robots.txt.
        Output(
            template="src/shared/lib/site.ts.j2",
            path="src/shared/lib/site.ts",
            when="definition.pages.values() | selectattr('meta') | list",
        ),
        Output(template="app/sitemap.ts.j2", path="app/sitemap.ts", when="nextjs.sitemap"),
        Output(template="app/robots.ts.j2", path="app/robots.ts", when="nextjs.sitemap"),
        Output(template="theme/globals.css.j2", path="src/app/styles/globals.css"),
        Output(template="src/app/providers/index.tsx.j2", path="src/app/providers/index.tsx"),
        Output(
            template="src/features/toggle-theme/index.ts.j2",
            path="src/features/toggle-theme/index.ts",
            when="nextjs.mode_toggle",
        ),
        Output(
            template="theme/mode-toggle.tsx.j2",
            path="src/features/toggle-theme/ui/mode-toggle.tsx",
            when="nextjs.mode_toggle",
        ),
        Output(template="src/pages/slice/index.ts.j2", path=_PAGE + "/index.ts", for_each="page"),
        Output(
            template="src/pages/slice/ui/page.tsx.j2",
            path=_PAGE + "/ui/{{ nextjs.pages[name].slice }}-page.tsx",
            for_each="page",
        ),
        Output(template="src/shared/config/index.ts.j2", path="src/shared/config/index.ts"),
        Output(template="src/shared/config/app.ts.j2", path="src/shared/config/app.ts"),
        Output(template="components.json.j2", path="components.json"),
        Output(template="shadcn/lib/utils.ts.j2", path="src/shared/lib/utils.ts"),
        Output(template="src/shared/lib/theme.ts.j2", path="src/shared/lib/theme.ts"),
        Output(template="drizzle.config.ts.j2", path="drizzle.config.ts"),
        Output(template="instrumentation.ts.j2", path="instrumentation.ts"),
        Output(template="proxy.ts.j2", path="proxy.ts"),
        Output(template="src/shared/lib/rate-limit.ts.j2", path="src/shared/lib/rate-limit.ts"),
        Output(template="app/health/route.ts.j2", path="app/health/route.ts"),
        # The jobs (ADR 0029): the table of the runs, and for each job a module and a route
        # handler that a scheduler calls.
        Output(
            template="src/shared/db/schema/job-runs.ts.j2",
            path="src/shared/db/schema/job-runs.ts",
            when="nextjs.jobs",
        ),
        Output(
            template="src/shared/lib/jobs.ts.j2", path="src/shared/lib/jobs.ts", when="nextjs.jobs"
        ),
        Output(
            template="src/app/jobs/job.ts.j2",
            path="src/app/jobs/{{ nextjs.jobs[name].module }}.ts",
            for_each="job",
        ),
        Output(
            template="src/app/jobs/job.ext.ts.j2",
            path="src/app/jobs/{{ nextjs.jobs[name].module }}.ext.ts",
            for_each="job",
            when="nextjs.jobs[name].gap",
            extension=True,
        ),
        Output(
            template="app/api/jobs/route.ts.j2",
            path="app/api/jobs/{{ name }}/route.ts",
            for_each="job",
        ),
        # The daily snapshots of the stat widgets (ADR 0042): the table, the built-in job and
        # its route, and the server actions of the charts.
        *(
            Output(template=f"{path}.j2", path=path, when="nextjs.snapshots")
            for path in (
                "src/shared/db/schema/stat-snapshots.ts",
                "src/shared/db/snapshots.ts",
                "src/app/jobs/stat-snapshots.ts",
            )
        ),
        Output(
            template="src/shared/api/snapshot-actions.ts.j2",
            path="src/shared/api/snapshot-actions.ts",
            when="nextjs.snapshots and nextjs.snapshots.charts",
        ),
        Output(
            template="app/api/jobs/stat-snapshots-route.ts.j2",
            path="app/api/jobs/stat_snapshots/route.ts",
            when="nextjs.snapshots",
        ),
        # The emails of the notices (ADR 0044): the built-in job and its route, and the page of
        # the settings.
        Output(
            template="src/app/jobs/notice-emails.ts.j2",
            path="src/app/jobs/notice-emails.ts",
            when="nextjs.notice_emails",
        ),
        Output(
            template="app/api/jobs/notice-emails-route.ts.j2",
            path="app/api/jobs/notice_emails/route.ts",
            when="nextjs.notice_emails",
        ),
        Output(
            template="app/notice-settings/page.tsx.j2",
            path="app/notice-settings/page.tsx",
            when="nextjs.notice_emails",
        ),
        Output(template="env.example.j2", path=".env.example"),
        Output(template="src/shared/db/index.ts.j2", path="src/shared/db/index.ts"),
        Output(template="src/shared/db/client.ts.j2", path="src/shared/db/client.ts"),
        Output(template="src/shared/db/connect.ts.j2", path="src/shared/db/connect.ts"),
        Output(template="src/shared/db/migrate.ts.j2", path="src/shared/db/migrate.ts"),
        Output(template="src/shared/db/seed.ts.j2", path="src/shared/db/seed.ts"),
        Output(template="src/shared/db/seed-data.ts.j2", path="src/shared/db/seed-data.ts"),
        Output(
            template="src/shared/db/seed-files.ts.j2",
            path="src/shared/db/seed-files.ts",
            when="nextjs.seed_files",
        ),
        Output(template="src/shared/db/run-seed.ts.j2", path="src/shared/db/run-seed.ts"),
        Output(template="src/shared/db/run-migrate.ts.j2", path="src/shared/db/run-migrate.ts"),
        Output(template="src/shared/db/schema/index.ts.j2", path="src/shared/db/schema/index.ts"),
        *(
            Output(template=f"{path}.j2", path=path, when="nextjs.history")
            for path in ("src/shared/db/schema/history-entries.ts", "src/shared/db/history.ts")
        ),
        Output(
            template="src/shared/db/acting-user.ts.j2",
            path="src/shared/db/acting-user.ts",
            # The change log without auth has no user of a change: the module gives null.
            when="nextjs.history or nextjs.notices",
        ),
        Output(
            template="src/shared/db/paths.ts.j2",
            path="src/shared/db/paths.ts",
            # The receiver paths of the notices, and the owner paths of the live events.
            when="nextjs.notices or nextjs.live | selectattr('owner_path') | list",
        ),
        # The live updates (ADR 0051): the changes of the repositories, the route of the events,
        # and the client that loads the open views again.
        *(
            Output(template=template, path=path, when="nextjs.live")
            for template, path in (
                ("src/shared/db/live.ts.j2", "src/shared/db/live.ts"),
                ("app/api/live/route.ts.j2", "app/api/live/route.ts"),
                ("ui/lib/live.ts.j2", "src/shared/lib/live.ts"),
                ("src/app/providers/live-updates.tsx.j2", "src/app/providers/live-updates.tsx"),
            )
        ),
        *(
            Output(template=f"{path}.j2", path=path, when="nextjs.notices")
            for path in (
                "src/shared/db/schema/notices.ts",
                "src/shared/db/notices.ts",
                "src/shared/api/notice-actions.ts",
                "src/shared/api/notices.ts",
            )
        ),
        *(
            Output(
                template=template,
                path=path,
                when="definition.access" if "access" in template else "definition.auth",
            )
            for template, path in (
                ("src/shared/auth/session.ts.j2", "src/shared/auth/session.ts"),
                ("src/shared/auth/actions.ts.j2", "src/shared/auth/actions.ts"),
                ("src/shared/auth/index.ts.j2", "src/shared/auth/index.ts"),
                ("src/shared/auth/access.ts.j2", "src/shared/auth/access.ts"),
                ("app/sign-in/page.tsx.j2", "app/sign-in/page.tsx"),
            )
        ),
        *(
            Output(
                template=template, path=path, when="definition.auth and definition.auth.password"
            )
            for template, path in (
                ("src/shared/db/schema/credentials.ts.j2", "src/shared/db/schema/credentials.ts"),
                ("src/shared/auth/password.ts.j2", "src/shared/auth/password.ts"),
            )
        ),
        *(
            Output(
                template=template, path=path, when="definition.auth and definition.auth.providers"
            )
            for template, path in (
                ("src/shared/auth/providers.ts.j2", "src/shared/auth/providers.ts"),
                (
                    "app/auth/providers/start/route.ts.j2",
                    "app/auth/providers/[name]/start/route.ts",
                ),
                (
                    "app/auth/providers/callback/route.ts.j2",
                    "app/auth/providers/[name]/callback/route.ts",
                ),
            )
        ),
        # The connections of the users to the APIs with the authorization code flow (ADR 0033).
        *(
            Output(template=template, path=path, when="ts_connections")
            for template, path in (
                (
                    "src/shared/db/schema/api-connections.ts.j2",
                    "src/shared/db/schema/api-connections.ts",
                ),
                ("src/shared/auth/connections.ts.j2", "src/shared/auth/connections.ts"),
                (
                    "src/shared/auth/connection-actions.ts.j2",
                    "src/shared/auth/connection-actions.ts",
                ),
                ("app/connections/page.tsx.j2", "app/connections/page.tsx"),
                ("app/connections/start/route.ts.j2", "app/connections/[api]/start/route.ts"),
                (
                    "app/connections/callback/route.ts.j2",
                    "app/connections/[api]/callback/route.ts",
                ),
            )
        ),
        *(
            Output(
                template=template,
                path=path,
                when="definition.auth and definition.auth.password_reset",
                extension=template.endswith(".ext.ts.j2"),
            )
            for template, path in (
                ("src/shared/auth/password-reset.ts.j2", "src/shared/auth/password-reset.ts"),
                ("app/forgot-password/page.tsx.j2", "app/forgot-password/page.tsx"),
                ("app/reset-password/page.tsx.j2", "app/reset-password/page.tsx"),
            )
        ),
        # One delivery hook for the messages of the password reset and of the verification of
        # the email address (ADR 0023).
        # With `auth.delivery: smtp`, `mail.ts` sends them, and the hook is not there.
        Output(
            template="src/shared/auth/messages.ts.j2",
            path="src/shared/auth/messages.ts",
            when=_MESSAGES,
        ),
        Output(
            template="src/shared/auth/messages.ext.ts.j2",
            path="src/shared/auth/messages.ext.ts",
            when=f"not nextjs.smtp and {_MESSAGES}",
            extension=True,
        ),
        Output(
            template="src/shared/auth/mail.ts.j2",
            path="src/shared/auth/mail.ts",
            when="nextjs.smtp",
        ),
        *(
            Output(template=template, path=path, when=_VERIFY_EMAIL)
            for template, path in (
                (
                    "src/shared/auth/email-verification.ts.j2",
                    "src/shared/auth/email-verification.ts",
                ),
                ("app/verify-email/page.tsx.j2", "app/verify-email/page.tsx"),
            )
        ),
        *(
            Output(template=template, path=path, when=_SECOND_FACTOR)
            for template, path in (
                ("src/shared/auth/second-factor.ts.j2", "src/shared/auth/second-factor.ts"),
                (
                    "src/shared/auth/second-factor-actions.ts.j2",
                    "src/shared/auth/second-factor-actions.ts",
                ),
                ("app/second-factor/page.tsx.j2", "app/second-factor/page.tsx"),
            )
        ),
        *(
            Output(template=template, path=path, when="definition.auth and definition.auth.sign_up")
            for template, path in (
                (
                    "src/features/sign-up/api/sign-up-action.ts.j2",
                    "src/features/sign-up/api/sign-up-action.ts",
                ),
                ("src/features/sign-up/api/sign-up.ts.j2", "src/features/sign-up/api/sign-up.ts"),
                ("app/sign-up/page.tsx.j2", "app/sign-up/page.tsx"),
            )
        ),
        Output(
            template="src/shared/db/schema/table.ts.j2",
            path="src/shared/db/schema/{{ nextjs.tables_by_entity[name].module }}.ts",
            for_each="entity",
        ),
        Output(template="src/shared/db/repository.ts.j2", path="src/shared/db/repository.ts"),
        # The storage of the files of the file fields, and a route of the files of each entity
        # with file fields (ADR 0027).
        *(
            Output(
                template=f"src/shared/storage/{name}.j2",
                path=f"src/shared/storage/{name}",
                when="definition.storage",
            )
            for name in ("storage.ts", "upload.ts", "index.ts")
        ),
        Output(
            template="app/files/route.ts.j2",
            path="app/files/{{ name | kebab }}/[id]/[field]/route.ts",
            for_each="entity",
            when="element.file_fields",
        ),
        Output(template="src/shared/api/types.ts.j2", path="src/shared/api/types.ts"),
        Output(template="src/shared/api/errors.ts.j2", path="src/shared/api/errors.ts"),
        Output(template="src/shared/api/client.ts.j2", path="src/shared/api/client.ts"),
        Output(template="src/shared/api/server.ts.j2", path="src/shared/api/server.ts"),
        Output(template="src/shared/api/index.ts.j2", path="src/shared/api/index.ts"),
        *(
            Output(
                template=f"src/entities/entity/{template}.j2",
                path=f"{_ENTITY}/{path}",
                for_each="entity",
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("server.ts", "server.ts"),
                ("model/types.ts", "model/types.ts"),
                ("model/meta.ts", "model/meta.ts"),
                ("model/schema.ts", "model/schema.ts"),
                ("api/repository.ts", "api/{{ name | kebab }}-repository.ts"),
                ("api/actions.ts", "api/{{ name | kebab }}-actions.ts"),
                ("api/api.ts", "api/{{ name | kebab }}-api.ts"),
            )
        ),
        *(
            Output(
                template=f"src/features/operation/{template}.j2",
                path=f"{_OPERATION}/{path}",
                for_each="operation",
                when=_CUSTOM_OP,
                extension=template.endswith(".ext.ts"),
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("api/api.ts", "api/{{ name | kebab }}-api.ts"),
                ("api/operation.gen.ts", "api/{{ name | kebab }}.gen.ts"),
                ("api/operation.ext.ts", "api/{{ name | kebab }}.ext.ts"),
            )
        ),
        # A query (ADR 0045): the server action gives a page of the rows of the extension file.
        *(
            Output(
                template=f"src/features/query/{template}.j2",
                path=f"{_OPERATION}/{path}",
                for_each="operation",
                when=_QUERY_OP,
                extension=template.endswith(".ext.ts"),
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("api/api.ts", "api/{{ name | kebab }}-api.ts"),
                ("api/query.gen.ts", "api/{{ name | kebab }}.gen.ts"),
                ("api/query.ext.ts", "api/{{ name | kebab }}.ext.ts"),
            )
        ),
        # An operation with lines (ADR 0035): the server action writes the lines.
        *(
            Output(
                template=f"src/features/lines-operation/{template}.j2",
                path=f"{_OPERATION}/{path}",
                for_each="operation",
                when=_LINES_OP,
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("api/api.ts", "api/{{ name | kebab }}-api.ts"),
                ("api/action.ts", "api/{{ name | kebab }}-action.ts"),
            )
        ),
        Output(
            template="src/shared/api/lines.ts.j2", path="src/shared/api/lines.ts", when="lines_ops"
        ),
        Output(
            template="integrations/third-party.ts.j2",
            path="src/shared/api/third-party.ts",
            when="ts_apis",
        ),
        *(
            Output(
                template=f"integrations/{template}.j2",
                path=f"{_INTEGRATION}/{template}",
                for_each="api",
            )
            for template in ("index.ts", "types.ts", "client.ts")
        ),
        Output(
            template="src/shared/db/schema/webhook-events.ts.j2",
            path="src/shared/db/schema/webhook-events.ts",
            when="ts_webhooks",
        ),
        *(
            Output(
                template=f"src/shared/webhooks/{module}.ts.j2",
                path=f"src/shared/webhooks/{module}.ts",
                when="ts_webhooks",
            )
            for module in ("index", "receive", "signature")
        ),
        Output(
            template="src/shared/webhooks/email.ts.j2",
            path="src/shared/webhooks/email.ts",
            when="ts_webhooks.values() | selectattr('email') | list",
        ),
        Output(
            template="app/webhook/route.ts.j2",
            path="{{ ts_webhooks[name].route_file }}",
            for_each="webhook",
        ),
        Output(
            template="src/features/webhook/index.ts.j2",
            path=_WEBHOOK + "/index.ts",
            for_each="webhook",
        ),
        Output(
            template="src/features/webhook/model/event.ts.j2",
            path=_WEBHOOK + "/model/event.ts",
            for_each="webhook",
            when="ts_webhooks[name].typed",
        ),
        *(
            Output(
                template=f"src/features/webhook/api/webhook.{part}.ts.j2",
                path=_WEBHOOK + "/api/{{ ts_webhooks[name].slice }}." + part + ".ts",
                for_each="webhook",
                extension=part == "ext",
            )
            for part in ("gen", "ext")
        ),
        *gap_rules(),
        *_SHADCN,
        *_HOOKS,
    ),
    covers=frozenset(
        {"app", "page", "page_meta", "entity", "field", "sequence", "relation", "operation"}
        | {"param", "result_field"}
        | {"theme", "tokens", "token_group", "token"}
        | {"layout", "sidebar", "topbar", "content", "footer"}
        | {"layout_override", "sidebar_override", "topbar_override", "content_override"}
        | {"menu", "menu_group", "menu_item", "menu_sub_item"}
        | {"table_view", "cards_view", "board_view", "column", "card", "badge_ref", "board_column"}
        | {"calendar_view", "map_view", "near_filter", "area_filter"}
        | {"api_table_view", "api_cards_view", "api_detail_view", "api_column", "api_sort"}
        | {"api_search_filter", "api_card", "api_detail_header", "api_detail_section"}
        | {"query_table_view", "query_cards_view", "query_calendar_view", "query_column"}
        | {"query_card", "query_filter"}
        | {"search_filter", "select_filter", "boolean_filter", "date_range_filter", "pagination"}
        | {"badge_set", "badge_value"}
        | {"detail_view", "detail_header", "detail_section", "detail_tab", "sort"}
        | {"dashboard", "dashboard_period", "grid", "grid_override"}
        | {"stat_widget", "chart_widget", "list_widget"}
        | {"form", "form_section", "form_field", "form_on_success"}
        | {"field_rules", "required_rule", "length_rule", "number_rule", "pattern_rule"}
        | {"compare_rule"}
        | {"entity_compare_rule", "entity_unique_rule", "entity_overlap_rule"}
        | {"custom_widget", "custom_rule", "custom_action"}
        | {"page_content", "page_arrangement", "navigate_action", "form_action", "operation_action"}
        | {"view_responsive", "motion"}
        | {"translations", "language"}
        | {"workflow", "transition"}
        | {"auth", "sign_up", "password_reset", "provider", "access", "role", "record_rule"}
        | {"memberships", "membership_role", "guests"}
        | {"email_verification", "second_factor"}
        | {"confirm", "on_success", "ui", "defaults", "states", "state", "loading_state"}
        | {"api", "api_operation"}
        | {"webhook"}
        | {"entity_seed", "seed_record"}
        | {"job", "event"}
        | {"storage"}
        | {"history", "notification"}
        | {"live"}
    ),
    gap_rule=Output(template="gaps/gap.ts.j2", path="src/gaps/{{ element_id }}.ext.ts"),
    context=context,
    finish=finish,
    filters={"json": typescript.to_json},
    helpers=typescript.HELPERS
    | ui.HELPERS
    | views.HELPERS
    | {"public_kinds": public_kinds, "kind_operations": kind_operations}
    | {"gap_spec": gap_spec, "rule_key": db.record_key, "rule_keys": db.record_keys}
    | {"rule_side_key": rule_side_key}
    | {"size_text": format_size}
    | {"ts_events": ts_events},
    stub_markers=("TODO(appgen)", "Not implemented yet"),
    extension_keys=(
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
    ),
    extension_prefix="x-nextjs-",
)
