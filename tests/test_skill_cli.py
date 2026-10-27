"""The agent skills agree with the CLI, and their files are in the wheel (ADR 0015, ADR 0053).

The skill `appgen` names each command and each option of the CLI, and no
other. A new command or option fails these tests until the skill
describes it. The quick-start skill names only commands and options of
the CLI too, and links only to its own files and to the skill `appgen`.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import typer.core
from skill_support import (
    MADE_FROM_DOCS,
    QUICKSTART,
    ROOT,
    SKILL,
    SKILLS,
    Command,
    cli_commands,
    code_texts,
    front_matter,
    option_names,
    skill_docs,
)

from appgen.skills import skill_files, skill_names

# An invocation starts at the start of the code, or after a shell
# separator or `uv run`. Prose such as "Created by appgen once" is no
# invocation.
_INVOCATION = re.compile(r"(?:^|&&|;|\||\$\(|\buv run|\buvx)\s*appgen(?=\s|$)")
_END = {"|", "||", "&&", ";", ">", "2>", ")"}
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


@dataclass
class Usage:
    """What a text of the skill names of the CLI."""

    commands: set[tuple[str, ...]] = field(default_factory=set[tuple[str, ...]])
    options: set[tuple[tuple[str, ...], str]] = field(
        default_factory=set[tuple[tuple[str, ...], str]]
    )
    """The options with the command that they follow."""
    loose_options: set[str] = field(default_factory=set[str])
    """The options in a code span of their own, for example `--force`."""
    errors: list[str] = field(default_factory=list[str])


def usage(texts: dict[str, str]) -> Usage:
    """Read the invocations of `appgen` in the code of Markdown texts.

    The DSL reference is made from docs/dsl.md. Its code spans that start
    with `-` are CSS variables, not options.
    """
    commands = cli_commands()
    all_options = set[str]().union(*(option_names(c) for c in commands.values()))
    found = Usage()
    for name, text in texts.items():
        for code in code_texts(text):
            if code.startswith("-") and name not in MADE_FROM_DOCS:
                option = code.split()[0].split("=")[0]
                found.loose_options.add(option)
                if option not in all_options:
                    found.errors.append(f"{name}: no command has the option '{option}': {code}")
            for match in _INVOCATION.finditer(code):
                _read_invocation(name, code, code[match.end() :].split(), commands, found)
    return found


def _read_invocation(
    name: str,
    code: str,
    tokens: list[str],
    commands: dict[tuple[str, ...], Command],
    found: Usage,
) -> None:
    path: tuple[str, ...] = ()
    generic = False
    for token in tokens:
        if token in _END:
            break
        if token.startswith("-"):
            option = token.split("=")[0]
            if generic:
                continue
            found.options.add((path, option))
            if option not in option_names(commands[path]):
                where = " ".join(("appgen", *path))
                found.errors.append(f"{name}: '{where}' has no option '{option}': {code}")
            continue
        command = commands[path]
        if generic or not isinstance(command, typer.core.TyperGroup):
            continue
        if (*path, token) in commands:
            path = (*path, token)
        elif token.startswith("<"):
            generic = True
        else:
            found.errors.append(f"{name}: the CLI has no command '{token}': {code}")
            return
    if not generic:
        found.commands.add(path)


@pytest.mark.parametrize("skill", [SKILL, QUICKSTART], ids=lambda p: p.name)
def test_the_skill_names_only_commands_and_options_of_the_cli(skill: Path) -> None:
    assert usage(skill_docs(skill)).errors == []


def test_the_skill_names_each_command_and_option_of_the_cli() -> None:
    found = usage({"SKILL.md": (SKILL / "SKILL.md").read_text(encoding="utf-8")})
    missing: list[str] = []
    for path, command in cli_commands().items():
        where = " ".join(("appgen", *path))
        if path and not isinstance(command, typer.core.TyperGroup) and path not in found.commands:
            missing.append(f"the command '{where}'")
        for param in command.params:
            if not isinstance(param, typer.core.TyperOption):
                continue
            names = {*param.opts, *param.secondary_opts}
            if not any((path, n) in found.options or n in found.loose_options for n in names):
                missing.append(f"the option '{param.opts[0]}' of '{where}'")
    assert missing == [], "SKILL.md does not name " + ", ".join(missing)


def test_the_usage_check_finds_an_unknown_command_and_option() -> None:
    text = "Run `appgen validate app.yaml --strict`, then `appgen deploy app.yaml`, and `--fast`."

    errors = usage({"x.md": text}).errors

    assert errors == [
        "x.md: 'appgen validate' has no option '--strict': appgen validate app.yaml --strict",
        "x.md: the CLI has no command 'deploy': appgen deploy app.yaml",
        "x.md: no command has the option '--fast': --fast",
    ]


def test_the_usage_check_reads_code_blocks_and_skips_prose() -> None:
    text = (
        "`Created by appgen once. appgen never changes it.`\n\n"
        "```sh\ncd app && uv run appgen check app.yaml . -f json | jq .passed\n```\n"
    )

    found = usage({"x.md": text})

    assert found.errors == []
    assert found.commands == {("check",)}
    assert found.options == {(("check",), "-f")}


@pytest.mark.parametrize("skill", [SKILL, QUICKSTART], ids=lambda p: p.name)
def test_the_front_matter_follows_the_agent_skills_format(skill: Path) -> None:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    data = front_matter(text)

    assert data["name"] == skill.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", data["name"])
    assert len(data["name"]) <= 64
    assert isinstance(data["description"], str)
    assert 0 < len(data["description"]) <= 1024
    assert len(text.splitlines()) <= 500


def test_the_description_names_the_five_tasks() -> None:
    description = front_matter((SKILL / "SKILL.md").read_text(encoding="utf-8"))["description"]

    for words in (
        "appgen validate",
        "appgen generate",
        "appgen check",
        "write a new app definition",
        "change the app definition",
        "fill the generation gaps",
        "add seed records",
    ):
        assert words in description


@pytest.mark.parametrize(
    ("skill", "name"),
    [(skill, name) for skill in (SKILL, QUICKSTART) for name in sorted(skill_docs(skill))],
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_the_links_of_the_skill_stay_in_the_skill(skill: Path, name: str) -> None:
    # The installed skill has only its own files, so a link to a file of
    # the repository does not work there. The quick-start skill also
    # links to the skill appgen: `appgen skills install` installs both
    # into the same skills folder.
    allowed = [skill] if skill == SKILL else [skill, SKILL]
    path = skill / name
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (path.parent / target).resolve()
        assert any(resolved.is_relative_to(a) for a in allowed), (
            f"{skill.name}/{name}: {target} is outside the skill"
        )
        assert resolved.exists(), f"{skill.name}/{name}: {target}"


def test_the_package_gives_the_files_of_each_skill() -> None:
    assert skill_names() == ["appgen", "appgen-quickstart"]
    assert skill_names() == sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))
    for name in skill_names():
        folder = SKILLS / name
        files = skill_files(name)
        expected = [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()]
        assert list(files) == sorted(expected)
        assert files["SKILL.md"] == (folder / "SKILL.md").read_bytes()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv builds the wheel")
def test_the_wheel_contains_the_skill_and_the_package_finds_it(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", str(ROOT), "--wheel", "--out-dir", str(tmp_path), "--quiet"],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("appgen-*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    for skill in skill_names():
        for path in skill_files(skill):
            assert f"appgen/skills/{skill}/{path}" in names

    # Import appgen from the wheel, as an installed package does.
    code = (
        "import json, appgen.skills as s; "
        "print(json.dumps({'module': s.__file__, 'skills': s.skill_names(), "
        "'files': sorted(s.skill_files('appgen-quickstart'))}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(wheel)},
    )
    found = json.loads(result.stdout)
    assert found["module"].startswith(str(wheel))
    assert found["skills"] == skill_names()
    assert found["files"] == sorted(skill_files("appgen-quickstart"))
