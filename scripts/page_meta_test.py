"""Start a generated Next.js app, and check the metadata of its pages, its sitemap, and robots.txt.

The test generates nothing: it runs in the Next.js app of
tests/fixtures/invoices.yaml. It starts `pnpm dev` with PGlite (the
migrations of `pnpm db:generate`, and the seed), and with
PUBLIC_URL=https://invoices.example.com. Then it checks:

- `/robots.txt` allows the pages, disallows `/api/`, and gives the URL
  of the sitemap.
- `/sitemap.xml` has the invoices page and the page of each invoice.
- The invoices page has its description and the absolute URL of its
  image in the Open Graph tags.
- The page of an invoice has the number of the invoice as description.

Run it from the repository root, after `pnpm install` in the app:

    uv run scripts/page_meta_test.py --app <folder>

scripts/check-nextjs.sh runs it. It needs pnpm, but not Docker.
"""

import argparse
import html
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PUBLIC_URL = "https://invoices.example.com"
INVOICES = 6
"""The invoices of the seed: 2 seed records and 4 generated records."""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read().decode()


def wait_for(url: str, log: Path) -> None:
    for _ in range(120):
        try:
            get(url)
            return
        except urllib.error.URLError, ConnectionError:
            time.sleep(1)
    sys.exit(f"page-meta-test: the app does not answer:\n{log.read_text()}")


def meta(page: str, key: str) -> str | None:
    """Return the content of a meta tag with a name or a property, or None."""
    match = re.search(rf'<meta (?:name|property)="{re.escape(key)}" content="([^"]*)"', page)
    return html.unescape(match.group(1)) if match else None


def check(base: str) -> list[str]:
    problems: list[str] = []
    robots = get(f"{base}/robots.txt")
    for line in ("Allow: /", "Disallow: /api/", f"Sitemap: {PUBLIC_URL}/sitemap.xml"):
        if line not in robots:
            problems.append(f"robots.txt has no line {line!r}:\n{robots}")
    urls = re.findall(r"<loc>([^<]*)</loc>", get(f"{base}/sitemap.xml"))
    invoices = [url for url in urls if re.fullmatch(rf"{PUBLIC_URL}/invoices/[0-9a-f-]+", url)]
    if f"{PUBLIC_URL}/invoices" not in urls or len(invoices) != INVOICES:
        problems.append(f"the sitemap has not the invoices page and {INVOICES} invoices: {urls}")
    page = get(f"{base}/invoices")
    want = {
        "description": "The invoices of the customers.",
        "og:description": "The invoices of the customers.",
        "og:image": f"{PUBLIC_URL}/invoices.png",
        "twitter:card": "summary_large_image",
    }
    for key, value in want.items():
        if meta(page, key) != value:
            problems.append(f"the invoices page has {key} {meta(page, key)!r}, expected {value!r}")
    if invoices:
        page = get(invoices[0].replace(PUBLIC_URL, base))
        description = meta(page, "description") or ""
        if not re.fullmatch(r"INV-\d{4}", description):
            problems.append(f"the page of an invoice has the description {description!r}")
    return problems


def run(app: Path) -> None:
    print("page-meta-test: pnpm db:generate", flush=True)
    subprocess.run(["pnpm", "--silent", "db:generate"], cwd=app, check=True, capture_output=True)
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_")}
    with tempfile.TemporaryDirectory() as temp:
        env |= {
            "PORT": str(port),
            "PUBLIC_URL": PUBLIC_URL,
            "DATABASE_URL": f"pglite:{Path(temp) / 'pglite'}",
            "DATABASE_MIGRATE": "true",
            "DATABASE_SEED": "true",
        }
        log = Path(temp) / "dev.log"
        print(f"page-meta-test: pnpm dev on port {port}", flush=True)
        with log.open("w") as out:
            # A new session, so that the stop also ends the child processes of pnpm.
            process = subprocess.Popen(
                ["pnpm", "--silent", "dev"],
                cwd=app,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        base = f"http://localhost:{port}"
        try:
            wait_for(f"{base}/health", log)
            problems = check(base)
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)
    for problem in problems:
        print(f"page-meta-test: {problem}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("page-meta-test: passed (the metadata, the sitemap, and robots.txt)")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="The generated Next.js app.")
    args = parser.parse_args()
    run(args.app)


if __name__ == "__main__":
    main()
