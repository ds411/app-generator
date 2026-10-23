"""The exact versions of the tools and packages of the generated Next.js app.

The versions are exact, not ranges, so that the same definition gives the
same app. Change them here, and check the example app with
`scripts/check-nextjs.sh`.
"""

NODE_VERSION = "24"
"""The major version of the Node.js Docker image."""
PNPM_VERSION = "10.28.0"

DEPENDENCIES: dict[str, str] = {
    "drizzle-orm": "0.45.4",
    "next": "16.4.3",
    "postgres": "3.4.9",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "server-only": "0.0.1",
    "zod": "4.6.7",
}
"""The runtime packages that each generated app needs."""

DEV_DEPENDENCIES: dict[str, str] = {
    "@tailwindcss/postcss": "4.3.3",
    "@types/node": "24.19.2",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "drizzle-kit": "0.31.11",
    "eslint": "9.39.5",
    "eslint-config-next": "16.4.3",
    "tailwindcss": "4.3.3",
    "typescript": "5.9.3",
}
"""The development packages that each generated app needs."""

UI_DEPENDENCIES: dict[str, str] = {
    "class-variance-authority": "0.7.1",
    "clsx": "2.1.1",
    "next-themes": "0.4.6",
    "tailwind-merge": "3.7.0",
}
"""The runtime packages of the shadcn/ui setup: `cn()` and the theme hook."""

UI_DEV_DEPENDENCIES: dict[str, str] = {
    "tw-animate-css": "1.4.0",
}
"""The development packages of the shadcn/ui setup: the animations of the components."""

COMPONENT_PACKAGES: dict[str, str] = {
    "class-variance-authority": "0.7.1",
    "cmdk": "1.1.1",
    "lucide-react": "1.61.0",
    "radix-ui": "1.8.1",
    "react-day-picker": "9.14.0",
    "recharts": "3.10.1",
    "sonner": "2.0.8",
}
"""The npm packages that the shadcn/ui components import, by package name.

`appgen.bindings.shared.shadcn` lists the packages of each component.
A test checks that this mapping has a version for each of them.
"""

TABLE_PACKAGES: dict[str, str] = {"@tanstack/react-table": "8.21.3"}
"""The packages of the table views: the data table of shadcn/ui uses TanStack Table."""
