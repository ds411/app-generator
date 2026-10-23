"""The template values of the Next.js binding.

The templates get these values as `nextjs`. They hold the names and the
paths that the Next.js app uses for the elements of a definition, so that
the templates do not compute them again in Jinja2.
"""

from dataclasses import dataclass
from typing import Any

from appgen.bindings.nextjs import versions
from appgen.dsl.model import AppDefinition, Page
from appgen.gen.naming import kebab, pascal

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

    @property
    def route_file(self) -> str:
        """The path of the route file, for example `app/projects/[id]/page.tsx`."""
        return "/".join(part for part in ("app", self.route_dir, "page.tsx") if part)


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


def page_info(name: str, page: Page) -> PageInfo:
    """Return the names and the paths of a page."""
    folder, params = route_dir(page.path)
    return PageInfo(
        name=name,
        page=page,
        slice=kebab(name),
        component=f"{pascal(name)}Page",
        route_dir=folder,
        params=params,
    )


def package_json(definition: AppDefinition) -> dict[str, Any]:
    """Return the content of `package.json`, with the packages sorted by name."""
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
            "start": "next start",
            "lint": "eslint --max-warnings 0",
            "typecheck": "next typegen && tsc --noEmit",
        },
        "dependencies": dict(sorted(versions.DEPENDENCIES.items())),
        "devDependencies": dict(sorted(versions.DEV_DEPENDENCIES.items())),
    }


def context(definition: AppDefinition) -> dict[str, Any]:
    """Return the template values of the Next.js binding for a definition."""
    pages = {name: page_info(name, page) for name, page in definition.pages.items()}
    return {
        "nextjs": {
            "layers": FSD_LAYERS,
            "pages": pages,
            "package_json": package_json(definition),
            "node_version": versions.NODE_VERSION,
        }
    }
