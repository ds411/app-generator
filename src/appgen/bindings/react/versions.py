"""The exact versions of the tools and packages of the generated React app.

The versions are exact, not ranges, so that the same definition gives the
same app. Change them here, and check the example app with
`scripts/check-react.sh`.
"""

NODE_VERSION = "24"
"""The major version of the Node.js Docker image."""
PNPM_VERSION = "10.28.0"

DEPENDENCIES: dict[str, str] = {
    "class-variance-authority": "0.7.1",
    "clsx": "2.1.1",
    "next-themes": "0.4.6",
    "react": "19.3.1",
    "react-dom": "19.3.1",
    "react-router": "8.5.0",
    "tailwind-merge": "3.7.0",
}
"""The runtime packages that each generated app needs.

`next-themes` is not specific to Next.js: it gives the light and the
dark mode to any React app.
"""

DEV_DEPENDENCIES: dict[str, str] = {
    "@eslint/js": "10.0.1",
    "@tailwindcss/vite": "4.3.3",
    "@types/node": "26.6.5",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "@vitejs/plugin-react": "6.1.2",
    "eslint": "10.13.0",
    "eslint-plugin-react-hooks": "7.1.1",
    "eslint-plugin-react-refresh": "0.5.7",
    "globals": "17.13.0",
    "tailwindcss": "4.3.3",
    "tw-animate-css": "1.4.0",
    "typescript": "6.0.3",
    "typescript-eslint": "8.72.0",
    "vite": "8.3.5",
}
"""The development packages that each generated app needs."""

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
