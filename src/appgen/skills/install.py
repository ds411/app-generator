"""Install the skills of appgen into the folders that agents read (ADR 0015).

Each installed skill has a record file, `.appgen-skill.json`, with the
appgen version and the hash of each file, as the output manifest of the
generator has (ADR 0005). With it, a new install updates the files of
an older version, keeps a file that a person changed, and an uninstall
removes only the files that appgen installed.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from appgen import __version__
from appgen.gen.manifest import content_hash
from appgen.skills import skill_files

RECORD_FILE = ".appgen-skill.json"
"""The record of an installed skill, in the folder of the skill."""
RECORD_VERSION = 1

SYSTEM_ROOT = Path("/")
"""The root of the system folders. The tests change it."""


class Target(StrEnum):
    """The agents whose folders get the skills."""

    CLAUDE = "claude"
    """Claude Code."""
    AGENTS = "agents"
    """Codex and other agents that read the Agent Skills format."""


class Scope(StrEnum):
    PROJECT = "project"
    USER = "user"
    SYSTEM = "system"


_PROJECT_FOLDERS = {Target.CLAUDE: ".claude/skills", Target.AGENTS: ".agents/skills"}
_SYSTEM_FOLDERS = {
    "linux": {Target.CLAUDE: "etc/claude-code/.claude/skills", Target.AGENTS: "etc/codex/skills"},
    "darwin": {
        Target.CLAUDE: "Library/Application Support/ClaudeCode/.claude/skills",
        Target.AGENTS: "etc/codex/skills",
    },
}
"""The managed folder of Claude Code and the admin folder of Codex, by platform."""


class SkillsError(Exception):
    """The skills cannot be installed or removed. The message tells why."""


def skills_folder(
    target: Target,
    scope: Scope,
    *,
    project_dir: Path,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Return the skills folder of a target and a scope.

    `home` is the home folder (default: the home folder of the user), and
    `platform` is a value of `sys.platform` (default: this platform).
    Raise SkillsError for the system scope on a platform without a known
    system folder.
    """
    platform = platform or sys.platform
    if scope is Scope.PROJECT:
        return project_dir / _PROJECT_FOLDERS[target]
    if scope is Scope.USER:
        return (home or Path.home()) / _PROJECT_FOLDERS[target]
    folders = _SYSTEM_FOLDERS.get(platform)
    if folders is None:
        raise SkillsError(
            f"The system scope has no known folder on the platform '{platform}'. "
            "Use --path to give the skills folder."
        )
    return SYSTEM_ROOT / folders[target]


@dataclass(frozen=True, slots=True)
class Record:
    """The record of an installed skill: the appgen version and the hash of each file."""

    appgen: str
    files: dict[str, str]

    def to_json(self) -> str:
        data = {
            "version": RECORD_VERSION,
            "appgen": self.appgen,
            "files": dict(sorted(self.files.items())),
        }
        return json.dumps(data, indent=2) + "\n"


def read_record(skill_dir: Path) -> Record | None:
    """Return the record of an installed skill, or None if the folder has no valid record."""
    path = skill_dir / RECORD_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != RECORD_VERSION:
            return None
        return Record(str(data["appgen"]), {str(k): str(v) for k, v in data["files"].items()})
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        return None


@dataclass(slots=True)
class Plan:
    """The changes of one install or uninstall of a skill in a skills folder."""

    skill: str
    folder: Path
    """The folder of the skill, for example `.claude/skills/appgen`."""
    create: list[str] = field(default_factory=list[str])
    update: list[str] = field(default_factory=list[str])
    delete: list[str] = field(default_factory=list[str])
    unchanged: list[str] = field(default_factory=list[str])
    changed: list[str] = field(default_factory=list[str])
    """The files that a person changed, or that appgen did not install."""
    record: Record | None = None
    """The record to write, or None to remove the record."""
    record_changes: bool = False

    @property
    def changes(self) -> bool:
        return bool(self.create or self.update or self.delete or self.record_changes)


def _text(content: bytes) -> bytes:
    """Return the content with `\\n` line ends, as the generator writes."""
    return content.replace(b"\r\n", b"\n")


def plan_install(skill: str, folder: Path, *, force: bool = False) -> Plan:
    """Compare the files of a skill with its installed copy in a skills folder."""
    skill_dir = folder / skill
    files = {path: _text(content) for path, content in skill_files(skill).items()}
    old = read_record(skill_dir)
    known = old.files if old else {}
    plan = Plan(skill, skill_dir, record=Record(__version__, {}))
    assert plan.record is not None
    for path, content in files.items():
        plan.record.files[path] = content_hash(content)
        target = skill_dir / path
        if not target.is_file():
            plan.create.append(path)
            continue
        current = target.read_bytes()
        if current == content:
            plan.unchanged.append(path)
        elif known.get(path) == content_hash(current) or force:
            plan.update.append(path)
        else:
            plan.changed.append(path)
    for path in sorted(set(known) - set(files)):
        target = skill_dir / path
        if not target.is_file():
            continue
        if known[path] == content_hash(target.read_bytes()) or force:
            plan.delete.append(path)
        else:
            plan.changed.append(path)
    plan.record_changes = old != plan.record
    return plan


def plan_uninstall(skill: str, folder: Path, *, force: bool = False) -> Plan:
    """Find the files of an installed skill that an uninstall removes."""
    skill_dir = folder / skill
    plan = Plan(skill, skill_dir)
    old = read_record(skill_dir)
    if old is None:
        return plan
    plan.record_changes = True
    for path, digest in sorted(old.files.items()):
        target = skill_dir / path
        if not target.is_file():
            continue
        if content_hash(target.read_bytes()) == digest or force:
            plan.delete.append(path)
        else:
            plan.changed.append(path)
    return plan


def apply(plan: Plan) -> None:
    """Write the changes of a plan. Raise SkillsError if the folder cannot be written."""
    try:
        files = skill_files(plan.skill) if plan.record else {}
        for path in [*plan.create, *plan.update]:
            target = plan.folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_text(files[path]))
        for path in plan.delete:
            (plan.folder / path).unlink()
        record = plan.folder / RECORD_FILE
        if plan.record is not None:
            if plan.record_changes:
                plan.folder.mkdir(parents=True, exist_ok=True)
                record.write_bytes(plan.record.to_json().encode("utf-8"))
        elif record.is_file():
            record.unlink()
        if plan.record is None:
            _remove_empty_folders(plan.folder)
    except OSError as error:
        reason = error.strerror or str(error)
        raise SkillsError(f"Cannot write the folder {plan.folder}: {reason}.") from None


def check_writable(folder: Path) -> None:
    """Raise SkillsError if appgen cannot make or write a folder."""
    existing = folder
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if not existing.is_dir() or not os.access(existing, os.W_OK | os.X_OK):
        raise SkillsError(f"Cannot write the folder {folder}: permission denied.")


def _remove_empty_folders(folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if not any(folder.iterdir()):
        folder.rmdir()


def status(skill: str, folder: Path) -> tuple[str | None, list[str]]:
    """Return the installed version of a skill in a skills folder, and the problems of the copy.

    The version is None if the skill is not installed. The problems are
    `out of date` (another version or other files) and `changed` (a
    person changed a file).
    """
    skill_dir = folder / skill
    old = read_record(skill_dir)
    if old is None:
        return None, []
    problems: list[str] = []
    files = {path: content_hash(_text(c)) for path, c in skill_files(skill).items()}
    if old.appgen != __version__ or old.files != files:
        problems.append("out of date")
    for path, digest in old.files.items():
        target = skill_dir / path
        if not target.is_file() or content_hash(target.read_bytes()) != digest:
            problems.append("changed")
            break
    return old.appgen, problems
