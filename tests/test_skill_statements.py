"""The statements of the agent skill agree with the CLI (ADR 0015).

The tests run the commands of the skill on fixtures, as an agent does:

- The keys of each JSON example are the keys of the real output at each
  level, and the types of the values agree. A comment before the block,
  for example `<!-- appgen check -->`, names the command of the JSON.
- The exit code of each case of the table of commands in `SKILL.md` is
  the real exit code.
- The default of an option (`Default: <value>.` in a list item that
  starts with the option) is the default of the CLI.

A wrong statement fails with the file and the line of the text.
"""

import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

import pytest
import typer.core
from skill_support import (
    MADE_FROM_DOCS,
    ROOT,
    CodeBlock,
    cli_commands,
    code_blocks,
    skill_docs,
)
from typer.testing import CliRunner

from appgen.cli import app

EXAMPLE = ROOT / "examples" / "project-tracker"
NOT_VALID = ROOT / "examples" / "invalid" / "unknown-reference.yaml"
runner = CliRunner()


@dataclass(frozen=True)
class Run:
    """The result of a run of the CLI."""

    exit_code: int
    stdout: str


EXIT_CASES: dict[str, dict[str, list[str]]] = {
    "validate": {"valid": ["validate"], "not valid": ["validate a definition that is not valid"]},
    "generate": {
        "written": ["generate"],
        "not written": [
            "generate a definition that is not valid",
            "generate over a manual edit",
        ],
    },
    "check": {
        "passed": ["check"],
        "failed": ["check an invalid trace", "check with a coverage that is too low"],
        "definition or manifest not valid": [
            "check a definition that is not valid",
            "check with a manifest that is not valid",
        ],
    },
    "orphans": {
        "": ["orphans"],
        "as for `check`": [
            "orphans of a definition that is not valid",
            "orphans with a manifest that is not valid",
            "orphans without a manifest",
        ],
    },
    "schema": {"": ["schema"]},
}
"""The runs of each case of the table of commands, by the command and the text of the case."""

JSON_RUNS = {
    "validate": "validate a definition that is not valid",
    "check": "check",
    "orphans": "orphans",
}
"""The run that gives the JSON example of each command."""


def invoke(*args: str | Path) -> Run:
    result = runner.invoke(app, [str(a) for a in args])
    return Run(result.exit_code, result.stdout)


def copy_app(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Run]:
    """Run the commands of the skill on the project tracker, and on broken copies of it."""
    work = tmp_path_factory.mktemp("statements")
    shutil.copytree(EXAMPLE, work / "tracker")
    definition = work / "tracker" / "app.yaml"
    folder = work / "tracker" / "app"
    found: dict[str, Run] = {
        "validate": invoke("validate", definition, "--format", "json"),
        "validate a definition that is not valid": invoke("validate", NOT_VALID, "-f", "json"),
        "generate": invoke("generate", definition, "-b", "fastapi", "-o", folder),
        "generate a definition that is not valid": invoke(
            "generate", NOT_VALID, "-b", "fastapi", "-o", work / "not-written"
        ),
        "schema": invoke("schema"),
    }

    edited = copy_app(folder, work / "edited")
    main = edited / "app" / "main.py"
    main.write_text(main.read_text(encoding="utf-8") + "# A manual edit.\n", encoding="utf-8")
    found["generate over a manual edit"] = invoke(
        "generate", definition, "-b", "fastapi", "-o", edited
    )

    found["check"] = invoke("check", definition, folder, "--format", "json")
    found["check with a coverage that is too low"] = invoke(
        "check", definition, folder, "--min-coverage", "100"
    )
    invalid = copy_app(folder, work / "invalid-trace")
    (invalid / "notes.py").write_text("# @trace entities.Nothing\n", encoding="utf-8")
    found["check an invalid trace"] = invoke("check", definition, invalid)
    found["check a definition that is not valid"] = invoke("check", NOT_VALID, folder)
    broken = copy_app(folder, work / "broken-manifest")
    (broken / ".appgen" / "manifest.json").write_text("{", encoding="utf-8")
    found["check with a manifest that is not valid"] = invoke("check", definition, broken)

    # Rename an operation that has an extension file, as change-definition.md tells.
    renamed = work / "renamed"
    shutil.copytree(work / "tracker", renamed)
    text = (renamed / "app.yaml").read_text(encoding="utf-8")
    (renamed / "app.yaml").write_text(
        re.sub(r"\bcomplete_task\b", "finish_task", text), encoding="utf-8"
    )
    assert (
        invoke("generate", renamed / "app.yaml", "-b", "fastapi", "-o", renamed / "app").exit_code
        == 0
    )
    found["orphans"] = invoke("orphans", renamed / "app.yaml", renamed / "app", "-f", "json")
    found["orphans of a definition that is not valid"] = invoke("orphans", NOT_VALID, folder)
    found["orphans with a manifest that is not valid"] = invoke("orphans", definition, broken)
    (work / "empty").mkdir()
    found["orphans without a manifest"] = invoke("orphans", definition, work / "empty")
    return found


def statement_docs() -> dict[str, str]:
    """Return the Markdown files of the skill that the skill writes itself."""
    return {name: text for name, text in skill_docs().items() if name not in MADE_FROM_DOCS}


# The JSON examples.


def json_type(value: object) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return "a boolean"
        case int() | float():
            return "a number"
        case str():
            return "a string"
        case list():
            return "an array"
        case _:
            return "an object"


def compare(example: object, output: object, path: str) -> Iterator[tuple[str, str]]:
    """Give the path and the problem of each difference of the keys and the types.

    A null value agrees with each type: the CLI gives null for a value
    that it does not know, for example a `hint`.
    """
    if example is None or output is None:
        return
    if json_type(example) != json_type(output):
        yield (
            path,
            f"gives {json_type(example)} at '{path}', but the output gives {json_type(output)}",
        )
        return
    if isinstance(example, dict) and isinstance(output, dict):
        example_keys = cast(dict[str, object], example)
        output_keys = cast(dict[str, object], output)
        for key in example_keys:
            at = f"{path}.{key}" if path else key
            if key not in output_keys:
                yield at, f"has the key '{at}', but the output has no such key"
            else:
                yield from compare(example_keys[key], output_keys[key], at)
        for key in output_keys:
            if key not in example_keys:
                at = f"{path}.{key}" if path else key
                yield path, f"has no key '{at}', but the output has it"
    elif isinstance(example, list) and isinstance(output, list):
        examples = cast(list[object], example)
        outputs = cast(list[object], output)
        if examples and not outputs:
            yield path, f"gives items at '{path}', but the output of the test gives none"
        for index, item in enumerate(examples):
            for real in outputs:
                yield from compare(item, real, f"{path}[{index}]")


def key_line(block: CodeBlock, path: str) -> int:
    """Return the line of the last key of a path in a JSON block, or the first line."""
    lines = block.content.splitlines()
    index = 0
    for key in re.sub(r"\[\d+\]", "", path).split("."):
        if not key:
            continue
        index = next((i for i in range(index, len(lines)) if f'"{key}":' in lines[i]), index)
    return block.line + index


def json_errors(texts: dict[str, str], runs: dict[str, Run]) -> list[str]:
    errors: list[str] = []
    for name, text in texts.items():
        for block in code_blocks(text, "json"):
            command = (block.comment or "").removeprefix("appgen ")
            if command == (block.comment or ""):
                errors.append(
                    f"{name}:{block.line}: name the command of the JSON in a comment before "
                    "the block, for example <!-- appgen check -->"
                )
                continue
            if command not in JSON_RUNS:
                errors.append(f"{name}:{block.line}: the test does not run 'appgen {command}'")
                continue
            try:
                example = json.loads(block.content)
            except json.JSONDecodeError as error:
                errors.append(f"{name}:{block.line + error.lineno - 1}: {error.msg}")
                continue
            output = json.loads(runs[JSON_RUNS[command]].stdout)
            problems = dict.fromkeys(compare(example, output, ""))
            for path, problem in problems:
                where = f"{name}:{key_line(block, path)}"
                errors.append(f"{where}: the JSON of 'appgen {command}' {problem}")
    return errors


# The exit codes.


def table_rows(text: str) -> Iterator[tuple[int, dict[str, str]]]:
    """Give the line and the cells by column of each row of the Markdown tables of a text."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.fullmatch(r"\|[\s:|-]+\|", line) or index == 0:
            continue
        header = [cell.strip() for cell in lines[index - 1].strip("|").split("|")]
        for number in range(index + 1, len(lines)):
            if not lines[number].startswith("|"):
                break
            # A code span can hold a `|`, but the cells of these tables do not.
            cells = [cell.strip() for cell in lines[number].strip("|").split("|")]
            yield number + 1, dict(zip(header, cells, strict=False))


def exit_code_errors(texts: dict[str, str], runs: dict[str, Run]) -> list[str]:
    errors: list[str] = []
    text = texts["SKILL.md"]
    seen: set[str] = set()
    for line, row in table_rows(text):
        if "Exit code" not in row:
            continue
        where = f"SKILL.md:{line}"
        span = re.match(r"`appgen ((?:[a-z]+ ?)+)", row["Command"])
        assert span, f"{where}: no command in {row['Command']}"
        command = span.group(1).strip()
        seen.add(command)
        cases = {
            case.strip(): int(code)
            for code, case in re.findall(r"(\d+)\s*([^,]*)", row["Exit code"])
        }
        known = EXIT_CASES.get(command)
        if known is None:
            errors.append(f"{where}: the test knows no cases of 'appgen {command}'")
            continue
        for case, code in cases.items():
            if case not in known:
                errors.append(f"{where}: the test knows no case '{case}' of 'appgen {command}'")
                continue
            for name in known[case]:
                real = runs[name].exit_code
                if real != code:
                    errors.append(
                        f"{where}: 'appgen {command}' exits with {real}, not {code}, "
                        f"in the case '{case}' ({name})"
                    )
        for case in known:
            if case not in cases:
                errors.append(f"{where}: no exit code for the case '{case}' of 'appgen {command}'")
    for command in EXIT_CASES:
        if command not in seen:
            errors.append(f"SKILL.md: the table of commands has no row for 'appgen {command}'")
    return errors


# The defaults of the options.


def list_items(text: str) -> Iterator[tuple[int, str]]:
    """Give the first line and the text of each item of the bullet lists of a text."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"( *)- ", line)
        if not match:
            continue
        indent = " " * (len(match.group(1)) + 2)
        end = index + 1
        while end < len(lines) and lines[end].startswith(indent):
            end += 1
        yield index + 1, "\n".join(lines[index:end])


def value_text(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list | tuple):
        return ", ".join(value_text(v) for v in cast(list[object], value))
    return str(value)


def cli_default(option: typer.core.TyperOption) -> str | None:
    """Return the default of an option, as `--help` gives it.

    An option whose default the command finds at run time has the
    default None, and its help ends with `Default: <value>.`.
    """
    if option.default is not None and option.default != ():
        return value_text(option.default)
    match = re.search(r"Default: (.+?)\.(?:\s|$)", option.help or "")
    return match.group(1) if match else None


def default_errors(texts: dict[str, str]) -> list[str]:
    errors: list[str] = []
    commands = cli_commands()
    for name, text in texts.items():
        for line, item in list_items(text):
            option = re.match(r"- `(--[a-z-]+)", item)
            stated = re.search(r"Default: (.+?)\.(?:\s|$)", item)
            if not option or not stated:
                continue
            where = f"{name}:{line + item[: stated.start()].count('\n')}"
            value = stated.group(1).replace("`", "")
            found = False
            for path, command in commands.items():
                for param in command.params:
                    if not isinstance(param, typer.core.TyperOption):
                        continue
                    if option.group(1) not in (*param.opts, *param.secondary_opts):
                        continue
                    found = True
                    real = cli_default(param)
                    if real != value:
                        errors.append(
                            f"{where}: the default of '{option.group(1)}' is '{value}', "
                            f"but 'appgen {' '.join(path)}' gives '{real}'"
                        )
            if not found:
                errors.append(f"{where}: no command has the option '{option.group(1)}'")
    return errors


# The tests.


def line_of(text: str, fragment: str) -> int:
    return text[: text.index(fragment)].count("\n") + 1


def test_the_json_examples_agree_with_the_output(runs: dict[str, Run]) -> None:
    assert json_errors(statement_docs(), runs) == []


def test_the_exit_codes_agree_with_the_cli(runs: dict[str, Run]) -> None:
    assert exit_code_errors(statement_docs(), runs) == []


def test_the_defaults_agree_with_the_cli() -> None:
    assert default_errors(statement_docs()) == []


def test_the_checks_read_the_examples_and_the_defaults() -> None:
    texts = statement_docs()
    blocks = {
        (name, block.comment) for name, text in texts.items() for block in code_blocks(text, "json")
    }
    stated = {
        re.match(r"- `(--[a-z-]+)", item)
        for text in texts.values()
        for _, item in list_items(text)
        if "Default: " in item
    }

    assert {
        ("SKILL.md", "appgen validate"),
        ("SKILL.md", "appgen check"),
        ("references/change-definition.md", "appgen orphans"),
    } <= blocks
    assert {m.group(1) for m in stated if m} >= {"--scope", "--target"}


def test_the_checks_find_a_wrong_key_exit_code_and_default(runs: dict[str, Run]) -> None:
    texts = statement_docs()
    skill = texts["SKILL.md"]
    texts["SKILL.md"] = (
        skill.replace('"element_id": "entities', '"element": "entities', 1)
        .replace('"files": 124', '"files": "124"', 1)
        .replace("0 valid, 1 not valid", "0 valid, 2 not valid", 1)
        .replace("Default: `project`.", "Default: `user`.", 1)
    )
    change = texts["references/change-definition.md"]
    texts["references/change-definition.md"] = change.replace('"suggestion"', '"hint"', 1)

    element = line_of(skill, '"element_id": "entities')
    validate = line_of(skill, '"diagnostics": [')
    assert json_errors(texts, runs) == [
        f"SKILL.md:{element}: the JSON of 'appgen validate' has the key "
        "'diagnostics[0].element', but the output has no such key",
        f"SKILL.md:{validate}: the JSON of 'appgen validate' has no key "
        "'diagnostics[0].element_id', but the output has it",
        f"SKILL.md:{line_of(skill, '"files": 124')}: the JSON of 'appgen check' gives "
        "a string at 'files', but the output gives a number",
        f"references/change-definition.md:{line_of(change, '"suggestion"')}: the JSON of "
        "'appgen orphans' has the key 'orphans[0].hint', but the output has no such key",
        f"references/change-definition.md:{line_of(change, '"orphans": [')}: "
        "the JSON of 'appgen orphans' has no key 'orphans[0].suggestion', but the output has it",
    ]
    assert exit_code_errors(texts, runs) == [
        f"SKILL.md:{line_of(skill, '0 valid, 1 not valid')}: 'appgen validate' exits with 1, "
        "not 2, in the case 'not valid' (validate a definition that is not valid)",
    ]
    assert default_errors(texts) == [
        f"SKILL.md:{line_of(skill, 'Default: `project`.')}: the default of '--scope' is "
        f"'user', but 'appgen {command}' gives 'project'"
        for command in ("skills install", "skills uninstall")
    ]


def test_the_checks_find_a_json_block_without_a_command(runs: dict[str, Run]) -> None:
    text = "Text.\n\n```json\n{}\n```\n\n<!-- appgen deploy -->\n```json\n{}\n```\n"

    assert json_errors({"x.md": text}, runs) == [
        "x.md:4: name the command of the JSON in a comment before the block, "
        "for example <!-- appgen check -->",
        "x.md:9: the test does not run 'appgen deploy'",
    ]


def test_the_checks_find_a_missing_and_an_unknown_case(runs: dict[str, Run]) -> None:
    texts = statement_docs()
    skill = texts["SKILL.md"]
    texts["SKILL.md"] = skill.replace(
        "0 passed, 1 failed, 2 definition or manifest not valid", "0 passed, 1 not passed", 1
    )

    line = line_of(skill, "0 passed, 1 failed")
    assert exit_code_errors(texts, runs) == [
        f"SKILL.md:{line}: the test knows no case 'not passed' of 'appgen check'",
        f"SKILL.md:{line}: no exit code for the case 'failed' of 'appgen check'",
        f"SKILL.md:{line}: no exit code for the case 'definition or manifest not valid' "
        "of 'appgen check'",
    ]
