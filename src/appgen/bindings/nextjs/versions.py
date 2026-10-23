"""The exact versions of the tools and packages of the generated Next.js app.

The versions are exact, not ranges, so that the same definition gives the
same app. Change them here, and check the example app with
`scripts/check-nextjs.sh`.
"""

NODE_VERSION = "24"
"""The major version of the Node.js Docker image."""
PNPM_VERSION = "10.28.0"

DEPENDENCIES: dict[str, str] = {
    "next": "16.4.3",
    "react": "19.3.0",
    "react-dom": "19.3.0",
}
"""The runtime packages that each generated app needs."""

DEV_DEPENDENCIES: dict[str, str] = {
    "@tailwindcss/postcss": "4.3.3",
    "@types/node": "24.19.2",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "eslint": "9.39.5",
    "eslint-config-next": "16.4.3",
    "tailwindcss": "4.3.3",
    "typescript": "5.9.3",
}
"""The development packages that each generated app needs."""
