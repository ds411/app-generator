"""`appgen skills`: install, list, and uninstall the skills for agents (ADR 0015).

The tests use a temporary home folder, a temporary system root, and a
temporary project folder, so that they do not change the folders of the
machine.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from appgen import __version__
from appgen.cli import app
from appgen.skills import install, skill_files
from appgen.skills.install import RECORD_FILE, Scope, SkillsError, Target, skills_folder

runner = CliRunner()
SKILL_FILES = skill_files("appgen")


@dataclass(frozen=True)
class Places:
    home: Path
    root: Path
    project: Path

    def folder(self, target: str, scope: str) -> Path:
        """Return the folder of the skill appgen for a target and a scope on Linux."""
        parent = {
            ("claude", "project"): self.project / ".claude/skills",
            ("claude", "user"): self.home / ".claude/skills",
            ("claude", "system"): self.root / "etc/claude-code/.claude/skills",
            ("agents", "project"): self.project / ".agents/skills",
            ("agents", "user"): self.home / ".agents/skills",
            ("agents", "system"): self.root / "etc/codex/skills",
        }[target, scope]
        return parent / "appgen"


@pytest.fixture
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Places:
    found = Places(tmp_path / "home", tmp_path / "root", tmp_path / "project")
    for path in (found.home, found.root, found.project):
        path.mkdir()
    monkeypatch.setenv("HOME", str(found.home))
    monkeypatch.setattr(install, "SYSTEM_ROOT", found.root)
    monkeypatch.setattr(install.sys, "platform", "linux")
    monkeypatch.chdir(found.project)
    return found


def skills(*args: str | Path) -> tuple[int, str]:
    result = runner.invoke(app, ["skills", *(str(a) for a in args)])
    return result.exit_code, result.output


def snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    """Return the content and the modification time of each file under a folder."""
    return {
        p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def assert_installed(folder: Path) -> None:
    files = {p: c for p, (c, _) in snapshot(folder).items()}
    assert set(files) == {*SKILL_FILES, RECORD_FILE}
    for path, content in SKILL_FILES.items():
        assert files[path] == content
        assert b"\r\n" not in files[path]
    record = json.loads(files[RECORD_FILE])
    assert record["version"] == 1
    assert record["appgen"] == __version__
    assert set(record["files"]) == set(SKILL_FILES)
    assert all(digest.startswith("sha256:") for digest in record["files"].values())


@pytest.mark.parametrize("scope", ["project", "user", "system"])
@pytest.mark.parametrize("target", ["claude", "agents"])
def test_install_writes_the_skill_for_each_target_and_scope_once(
    places: Places, target: str, scope: str
) -> None:
    code, output = skills("install", "--target", target, "--scope", scope)

    assert code == 0, output
    folder = places.folder(target, scope)
    assert_installed(folder)
    assert f"Installed the skill of appgen {__version__} into {folder}:" in output
    assert "  created: SKILL.md\n" in output
    # Only the folder of the target and the scope gets the skill.
    others = [places.folder(t, s) for t in ("claude", "agents") for s in ("project", "user")]
    assert [f for f in others if f.exists() and f != folder] == []

    before = snapshot(folder)
    code, output = skills("install", "--target", target, "--scope", scope)

    assert code == 0
    assert output == f"{folder}: the skill 'appgen' is up to date ({__version__}).\n"
    assert snapshot(folder) == before


def test_install_without_options_writes_both_project_folders(places: Places) -> None:
    code, output = skills("install")

    assert code == 0, output
    assert_installed(places.folder("agents", "project"))
    assert_installed(places.folder("claude", "project"))
    assert output.index(".agents/skills/appgen") < output.index(".claude/skills/appgen")
    assert not (places.home / ".claude").exists()


def test_install_takes_more_targets_and_a_project_folder(places: Places, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()

    code, output = skills("install", "-t", "claude", "-t", "agents", "--project-dir", other)

    assert code == 0, output
    assert_installed(other / ".claude/skills/appgen")
    assert_installed(other / ".agents/skills/appgen")
    assert not (places.project / ".claude").exists()


def test_install_writes_to_another_skills_folder_with_path(places: Places, tmp_path: Path) -> None:
    code, output = skills("install", "--path", tmp_path / "custom")

    assert code == 0, output
    assert_installed(tmp_path / "custom" / "appgen")

    code, output = skills("install", "--path", tmp_path / "custom", "--scope", "user")

    assert code == 1
    assert "give --path, or --target and --scope, not both" in output


def test_an_install_of_another_version_updates_the_files(places: Places) -> None:
    folder = places.folder("claude", "project")
    skills("install", "-t", "claude")
    # Make the copy look like the copy of an older version: another text
    # of SKILL.md, a file that the new version does not have, and the
    # hashes of these files in the record.
    old_text = b"The skill of an older version.\n"
    (folder / "SKILL.md").write_bytes(old_text)
    (folder / "references" / "old.md").write_bytes(b"Gone.\n")
    record = json.loads((folder / RECORD_FILE).read_text())
    record["appgen"] = "0.0.1"
    record["files"]["SKILL.md"] = install.content_hash(old_text)
    record["files"]["references/old.md"] = install.content_hash(b"Gone.\n")
    (folder / RECORD_FILE).write_text(json.dumps(record))
    code, output = skills("list")
    assert "0.0.1      out of date" in output

    code, output = skills("install", "-t", "claude")

    assert code == 0, output
    assert "  updated: SKILL.md\n" in output
    assert "  deleted: references/old.md\n" in output
    assert_installed(folder)


def test_install_does_not_overwrite_a_changed_file_without_force(places: Places) -> None:
    skills("install", "-t", "claude")
    changed = places.folder("claude", "project") / "references" / "dsl.md"
    changed.write_text("My notes.\n")

    code, output = skills("install")

    assert code == 1
    assert f"  {changed}\n" in output
    assert "--force" in output
    assert changed.read_text() == "My notes.\n"
    # The command stops before it writes any folder.
    assert not places.folder("agents", "project").exists()

    code, output = skills("install", "--force")

    assert code == 0, output
    assert "  updated: references/dsl.md\n" in output
    assert_installed(places.folder("claude", "project"))
    assert_installed(places.folder("agents", "project"))


def test_install_does_not_overwrite_a_file_that_appgen_did_not_install(places: Places) -> None:
    folder = places.folder("claude", "project")
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("Another skill.\n")

    code, output = skills("install", "-t", "claude")

    assert code == 1
    assert f"  {folder / 'SKILL.md'}\n" in output
    assert not (folder / RECORD_FILE).exists()


def test_dry_run_shows_the_changes_and_writes_no_file(places: Places) -> None:
    code, output = skills("install", "--dry-run")

    assert code == 0, output
    assert "The install would change" in output
    assert "  create: SKILL.md\n" in output
    assert list(places.project.iterdir()) == []

    skills("install")
    before = snapshot(places.project)
    code, output = skills("uninstall", "--dry-run")

    assert code == 0, output
    assert "  delete: SKILL.md\n" in output
    assert snapshot(places.project) == before


def test_list_shows_each_target_and_scope_with_the_status(places: Places) -> None:
    skills("install", "-t", "claude")
    skills("install", "-t", "agents", "-s", "user")
    (places.folder("agents", "user") / "SKILL.md").write_text("Changed.\n")

    code, output = skills("list", "--format", "json")

    assert code == 0, output
    report = json.loads(output)
    assert report["appgen"] == __version__
    found = {(r["target"], r["scope"]): (r["installed"], r["status"]) for r in report["skills"]}
    assert found == {
        ("claude", "project"): (__version__, "up to date"),
        ("claude", "user"): (None, "not installed"),
        ("claude", "system"): (None, "not installed"),
        ("agents", "project"): (None, "not installed"),
        ("agents", "user"): (__version__, "changed"),
        ("agents", "system"): (None, "not installed"),
    }
    folders = {(r["target"], r["scope"]): r["folder"] for r in report["skills"]}
    assert folders["agents", "system"] == str(places.folder("agents", "system"))

    code, output = skills("list")

    assert code == 0
    lines = output.splitlines()
    assert lines[0].split() == ["skill", "target", "scope", "installed", "status", "folder"]
    assert lines[1].split()[:5] == ["appgen", "claude", "project", __version__, "up"]
    assert len(lines) == 7


def test_list_shows_the_folder_of_path(places: Places, tmp_path: Path) -> None:
    skills("install", "--path", tmp_path / "custom")

    code, output = skills("list", "--path", tmp_path / "custom", "-f", "json")

    assert code == 0, output
    (row,) = [r for r in json.loads(output)["skills"] if r["scope"] == "path"]
    assert row["target"] is None
    assert row["status"] == "up to date"


def test_uninstall_removes_only_the_files_that_appgen_installed(places: Places) -> None:
    skills("install")
    folder = places.folder("claude", "project")
    (folder / "my-notes.md").write_text("Mine.\n")

    code, output = skills("uninstall", "-t", "claude")

    assert code == 0, output
    assert "  deleted: SKILL.md\n" in output
    assert [p.relative_to(folder).as_posix() for p in folder.rglob("*")] == ["my-notes.md"]
    assert_installed(places.folder("agents", "project"))

    code, output = skills("uninstall", "-t", "agents")

    assert code == 0, output
    assert not places.folder("agents", "project").exists()
    code, output = skills("uninstall", "-t", "agents")
    assert output == f"{places.folder('agents', 'project')}: the skill 'appgen' is not installed.\n"


def test_uninstall_keeps_a_changed_file_without_force(places: Places) -> None:
    skills("install", "-t", "claude")
    changed = places.folder("claude", "project") / "SKILL.md"
    changed.write_text("Changed.\n")

    code, output = skills("uninstall", "-t", "claude")

    assert code == 1
    assert f"  {changed}\n" in output
    assert changed.is_file()
    assert (changed.parent / RECORD_FILE).is_file()

    code, output = skills("uninstall", "-t", "claude", "--force")

    assert code == 0, output
    assert not changed.parent.exists()


def test_a_folder_that_appgen_cannot_write_gives_a_message(places: Places, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("Not a folder.\n")

    code, output = skills("install", "--path", blocker / "skills")

    assert code == 1
    assert f"error: Cannot write the folder {blocker / 'skills' / 'appgen'}" in output


def test_the_system_scope_without_root_gives_a_message(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tests can run as root, so the check of the permission is simulated.
    def access(path: Path, mode: int) -> bool:
        return not str(path).startswith(str(places.root))

    monkeypatch.setattr(install.os, "access", access)

    code, output = skills("install", "--scope", "system")

    assert code == 1
    assert "permission denied" in output
    assert "needs root" in output
    assert not (places.root / "etc").exists()


def test_the_system_folders_follow_the_platform(places: Places) -> None:
    project = places.project

    assert skills_folder(Target.CLAUDE, Scope.SYSTEM, project_dir=project, platform="darwin") == (
        places.root / "Library/Application Support/ClaudeCode/.claude/skills"
    )
    assert skills_folder(Target.AGENTS, Scope.SYSTEM, project_dir=project, platform="linux") == (
        places.root / "etc/codex/skills"
    )
    with pytest.raises(SkillsError, match="no known folder on the platform 'win32'"):
        skills_folder(Target.CLAUDE, Scope.SYSTEM, project_dir=project, platform="win32")
    assert skills_folder(Target.CLAUDE, Scope.USER, project_dir=project) == (
        Path(os.environ["HOME"]) / ".claude/skills"
    )
