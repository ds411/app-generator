"""Helpers for the tests of the agent skill: its files, its front matter, and its code."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import typer.core
import typer.main
import yaml

from appgen.cli import app

ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "src" / "appgen" / "skills"
SKILL = SKILLS / "appgen"

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_SPAN = re.compile(r"`([^`]+)`")
_COMMENT = re.compile(r"<!--\s*(.*?)\s*-->")

MADE_FROM_DOCS = {"references/dsl.md"}
"""The files of the skill that a script makes from the docs of the repository."""

type Command = typer.core.TyperCommand | typer.core.TyperGroup


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block of a Markdown text."""

    content: str
    line: int
    """The line of the first line of the content in the text, from 1."""
    comment: str | None
    """The text of an HTML comment on the line before the block, for example `appgen check`."""


def skill_docs() -> dict[str, str]:
    """Return the text of each Markdown file of the skill, by its path in the skill folder."""
    return {
        path.relative_to(SKILL).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(SKILL.rglob("*.md"))
    }


def front_matter(text: str) -> dict[str, Any]:
    """Return the YAML front matter of a SKILL.md file."""
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML front matter between '---' lines."
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return cast(dict[str, Any], data)


def code_texts(text: str) -> list[str]:
    """Return the code of a Markdown text: each line of the fenced blocks, and each code span.

    A code span that spans more than one line becomes one line.
    """
    lines = [line for block in _FENCE.findall(text) for line in block.splitlines()]
    prose = _FENCE.sub("", text)
    spans = [" ".join(span.split()) for span in _SPAN.findall(prose)]
    return [*lines, *spans]


def fenced_blocks(text: str, language: str) -> list[str]:
    """Return the content of the fenced code blocks of a language, for example `yaml`."""
    return re.findall(rf"^```{language}\n(.*?)^```", text, re.DOTALL | re.MULTILINE)


def code_blocks(text: str, language: str) -> list[CodeBlock]:
    """Return the fenced code blocks of a language, with their lines and their comments.

    A block starts with a line of three backticks and the language, and
    ends with a line of three backticks, both at the start of the line.
    """
    lines = text.splitlines()
    blocks: list[CodeBlock] = []
    index = 0
    while index < len(lines):
        if lines[index] == f"```{language}":
            end = lines.index("```", index + 1)
            comment = _COMMENT.fullmatch(lines[index - 1]) if index else None
            blocks.append(
                CodeBlock(
                    content="".join(f"{line}\n" for line in lines[index + 1 : end]),
                    line=index + 2,
                    comment=comment.group(1) if comment else None,
                )
            )
            index = end
        index += 1
    return blocks


def cli_commands() -> dict[tuple[str, ...], Command]:
    """Return each command of the CLI by its path, with the root command at ()."""
    commands: dict[tuple[str, ...], Command] = {}

    def walk(path: tuple[str, ...], command: Command) -> None:
        commands[path] = command
        if isinstance(command, typer.core.TyperGroup):
            for name, sub in command.commands.items():
                walk((*path, name), cast(Command, sub))

    walk((), cast(Command, typer.main.get_command(app)))
    return commands


def option_names(command: Command) -> set[str]:
    """Return the option names of a command, for example `--format` and `-f`."""
    names = {"--help"}
    for param in command.params:
        if isinstance(param, typer.core.TyperOption):
            names.update(param.opts, param.secondary_opts)
    return names
