# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Create or update the labels and milestones in .github/planning/.

The script only creates and updates. It never deletes a label or a
milestone. It matches labels by name and milestones by title.

Environment: GITHUB_REPOSITORY (owner/name) and GITHUB_TOKEN. Pass
--dry-run to print the changes without a write.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

PLANNING = Path(__file__).resolve().parents[1] / "planning"


class GitHub:
    def __init__(self, repo: str, token: str, dry_run: bool) -> None:
        self.base = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{repo}"
        self.token = token
        self.dry_run = dry_run

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if self.dry_run and method != "GET":
            return {"number": "?"}
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            print(f"{method} {path} failed: {error.code} {error.read().decode()}", file=sys.stderr)
            raise

    def list_all(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            batch = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


def load(name: str) -> list[dict[str, Any]]:
    return yaml.safe_load((PLANNING / name).read_text(encoding="utf-8"))


def sync_labels(github: GitHub) -> None:
    existing = {label["name"]: label for label in github.list_all("/labels")}
    for label in load("labels.yml"):
        body = {"name": label["name"], "color": label["color"], "description": label["description"]}
        current = existing.get(label["name"])
        if current is None:
            github.request("POST", "/labels", body)
            print(f"created label: {label['name']}")
        elif current["color"].lower() != label["color"].lower() or (current["description"] or "") != label["description"]:
            github.request("PATCH", f"/labels/{urllib.parse.quote(label['name'], safe='')}", body)
            print(f"updated label: {label['name']}")
        else:
            print(f"unchanged label: {label['name']}")


def sync_milestones(github: GitHub) -> None:
    existing = {milestone["title"]: milestone for milestone in github.list_all("/milestones?state=all")}
    for milestone in load("milestones.yml"):
        body = {"title": milestone["title"], "description": milestone["description"].strip()}
        current = existing.get(milestone["title"])
        if current is None:
            created = github.request("POST", "/milestones", body)
            print(f"created milestone #{created['number']}: {milestone['title']}")
        elif (current["description"] or "").replace("\r\n", "\n") != body["description"]:
            github.request("PATCH", f"/milestones/{current['number']}", body)
            print(f"updated milestone #{current['number']}: {milestone['title']}")
        else:
            print(f"unchanged milestone #{current['number']}: {milestone['title']}")


def main() -> None:
    github = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"], "--dry-run" in sys.argv[1:])
    sync_labels(github)
    sync_milestones(github)


if __name__ == "__main__":
    main()
