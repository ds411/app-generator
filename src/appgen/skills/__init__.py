"""The agent skills of appgen (ADR 0015).

A skill is a folder with a `SKILL.md` file and optional reference files,
in the Agent Skills format that Claude Code, Codex, and other agents
read. The skills are package data, so `importlib.resources` finds them
in the installed package, also after `uv tool install`.
"""

from importlib.resources import files
from importlib.resources.abc import Traversable

SKILL_FILE = "SKILL.md"
"""The main file of a skill: YAML front matter, then the instructions."""


def skill_names() -> list[str]:
    """Return the names of the skills, sorted. The name of a skill is the name of its folder."""
    root = files(__name__)
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / SKILL_FILE).is_file())


def skill_files(name: str) -> dict[str, bytes]:
    """Return the content of each file of a skill, by its path in the skill folder, sorted.

    The paths use `/`, for example `references/dsl.md`.
    """
    found: dict[str, bytes] = {}
    _collect(files(__name__) / name, "", found)
    if SKILL_FILE not in found:
        raise KeyError(f"The skill '{name}' does not exist.")
    return dict(sorted(found.items()))


def _collect(folder: Traversable, prefix: str, found: dict[str, bytes]) -> None:
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        path = prefix + entry.name
        if entry.is_dir():
            _collect(entry, path + "/", found)
        elif entry.is_file():
            found[path] = entry.read_bytes()
