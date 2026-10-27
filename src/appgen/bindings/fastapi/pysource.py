"""Write Python source in the format of the Ruff formatter.

The generated app must pass `ruff format --check`. A call that fits in
the line length stays on one line. A longer call has one argument on
each line and a trailing comma, which the formatter keeps as it is.
"""

import ast
import json
from typing import cast

from appgen.dsl.translations import VALUE

LINE_LENGTH = 100


def string(value: str) -> str:
    """Return a text as a Python string literal, with the quotes of the Ruff formatter.

    The literal has double quotes, unless the text has more double quotes
    than single quotes.
    """
    quote = "'" if value.count('"') > value.count("'") else '"'
    body = json.dumps(value, ensure_ascii=False)[1:-1]
    if quote == "'":
        body = body.replace('\\"', '"').replace("'", "\\'")
    return quote + body + quote


def call(prefix: str, func: str, args: list[str], indent: int = 4, suffix: str = "") -> str:
    """Return `<prefix><func>(<args>)<suffix>` on one line if it fits, else on many lines.

    The result has no indent on its first line. The indent applies to the
    next lines.
    """
    pad = " " * indent
    one_line = f"{prefix}{func}({', '.join(args)}){suffix}"
    if not args or indent + len(one_line) <= LINE_LENGTH:
        return one_line
    inner = "".join(f"{pad}    {arg},\n" for arg in args)
    return f"{prefix}{func}(\n{inner}{pad}){suffix}"


def signature(head: str, params: str | list[str], tail: str, indent: int = 0) -> str:
    """Return a function signature in the format of the Ruff formatter.

    `head` is for example `async def list_tasks`, `params` the parameters (a
    list, or a text with commas between them), and `tail` for example
    ` -> None:`. The signature is on one line if it fits. Else two or more
    parameters that fit on one line go on one line between the brackets.
    Else each parameter is on its own line, with a trailing comma.
    """
    items = _split_params(params) if isinstance(params, str) else params
    pad = " " * indent
    one_line = f"{head}({', '.join(items)}){tail}"
    if indent + len(one_line) <= LINE_LENGTH:
        return one_line
    joined = ", ".join(items)
    if len(items) > 1 and indent + 4 + len(joined) <= LINE_LENGTH:
        return f"{head}(\n{pad}    {joined}\n{pad}){tail}"
    inner = "".join(f"{pad}    {item},\n" for item in items)
    return f"{head}(\n{inner}{pad}){tail}"


def _split_params(text: str) -> list[str]:
    """Split parameters at the commas outside brackets."""
    items: list[str] = []
    depth = 0
    current = ""
    for char in text:
        depth += char in "([{"
        depth -= char in ")]}"
        if char == "," and depth == 0:
            items.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        items.append(current.strip())
    return items


def literal(value: object, prefix: str = "", indent: int = 0, suffix: str = "") -> str:
    """Return a JSON value as a Python literal, in the format of the Ruff formatter.

    `prefix` and `suffix` are the text before and after the value on its
    line, for example `"key": ` and `,`, and `indent` is the indent of the
    line. A list or a dict that does not fit in the line length has one
    item on each line and a trailing comma. The result has no indent on
    its first line.
    """
    one_line = f"{prefix}{_flat(value)}{suffix}"
    if indent + len(one_line) <= LINE_LENGTH or not isinstance(value, list | dict) or not value:
        return one_line
    pad = " " * indent
    if isinstance(value, dict):
        entries = cast(dict[str, object], value)
        items = [literal(v, f"{string(k)}: ", indent + 4, ",") for k, v in entries.items()]
        brackets = "{}"
    else:
        items = [literal(v, "", indent + 4, ",") for v in cast(list[object], value)]
        brackets = "[]"
    inner = "".join(f"{pad}    {item}\n" for item in items)
    return f"{prefix}{brackets[0]}\n{inner}{pad}{brackets[1]}{suffix}"


def _flat(value: object) -> str:
    match value:
        case None:
            return "None"
        case bool():
            return str(value)
        case int() | float():
            return json.dumps(value)
        case str():
            return string(value)
        case list():
            return "[" + ", ".join(_flat(v) for v in cast(list[object], value)) + "]"
        case dict():
            entries = cast(dict[str, object], value)
            return "{" + ", ".join(f"{string(k)}: {_flat(v)}" for k, v in entries.items()) + "}"
        case _:
            raise TypeError(f"not a JSON value: {value!r}")


def raise_problem(
    status: int,
    text: str,
    values: dict[str, str],
    *,
    indent: int,
    translated: bool,
    suffix: str = "",
) -> str:
    """Return `raise ProblemError(<status>, <message>)`, on one line if it fits, else on many lines.

    With translations, the message is a call of `t` (ADR 0010), for
    example `t("No {entity} has the ID {id}.", entity="Project", id=id)`.
    Else it is a string literal, or an f-string with the values in it. Each
    value is a Python expression. A string literal goes into the f-string
    as text. A text without values stays as it is, also with braces. The
    suffix follows the raise, for example ` from error`. The result has no
    indent on its first line.
    """
    pad = " " * indent
    parts = VALUE.split(text) if values else [text]
    if set(parts[1::2]) != set(values):
        raise ValueError(f"The values {sorted(values)} do not agree with the text {text!r}.")
    if translated:
        args = [string(text), *(f"{name}={expression}" for name, expression in values.items())]
        message = f"t({', '.join(args)})"
    else:
        args = []
        message = _f_string(parts, values)
    one_line = f"raise ProblemError({status}, {message}){suffix}"
    if indent + len(one_line) <= LINE_LENGTH:
        return one_line
    if translated:
        message = call("", "t", args, indent + 4, ",")
    else:
        message += ","
    return f"raise ProblemError(\n{pad}    {status},\n{pad}    {message}\n{pad}){suffix}"


def _f_string(parts: list[str], values: dict[str, str]) -> str:
    """Return a text with values as an f-string, or as a string literal without a value."""
    literals: dict[str, str] = {}
    for name, expression in values.items():
        try:
            value = ast.literal_eval(expression)
        except ValueError, SyntaxError:
            continue
        if isinstance(value, str):
            literals[name] = value
    if len(literals) == len(values):
        return string("".join(literals[part] if i % 2 else part for i, part in enumerate(parts)))

    def escaped(part: str) -> str:
        return part.replace("{", "{{").replace("}", "}}")

    body = "".join(
        escaped(part)
        if i % 2 == 0
        else escaped(literals[part])
        if part in literals
        else "{" + values[part] + "}"
        for i, part in enumerate(parts)
    )
    return "f" + string(body)


def from_import(module: str, names: set[str]) -> str:
    """Return a `from` import with the names in the order of the Ruff import sorter."""

    def key(name: str) -> tuple[int, str, str]:
        kind = 0 if name.isupper() and len(name) > 1 else 1 if name[0].isupper() else 2
        return (kind, name.lower(), name)

    ordered = sorted(names, key=key)
    line = f"from {module} import {', '.join(ordered)}"
    if len(line) <= LINE_LENGTH:
        return line
    inner = "".join(f"    {name},\n" for name in ordered)
    return f"from {module} import (\n{inner})"


def import_block(lines: set[str]) -> str:
    """Return import lines in the groups and the order of the Ruff import sorter.

    The groups are the standard library, the third-party packages, and the
    app (`app.` and `tests.`). Straight imports (`import x`) come before `from` imports
    in each group.
    """
    stdlib = {"collections", "dataclasses", "datetime", "decimal", "enum", "itertools", "os"}
    stdlib |= {"typing", "uuid"}
    stdlib |= {"asyncio", "json", "pathlib", "re", "types", "urllib"}
    stdlib |= {"base64", "copy", "email", "hashlib", "hmac", "time"}
    stdlib |= {"argparse", "contextlib", "logging", "secrets", "signal", "sys", "threading"}
    groups: list[list[str]] = [[], [], []]
    for line in lines:
        module = line.split()[1]
        root = module.split(".")[0]
        index = 0 if root in stdlib else 2 if root in ("app", "tests") else 1
        groups[index].append(line)

    def key(line: str) -> tuple[int, str]:
        return (0 if line.startswith("import ") else 1, line.split()[1])

    return "\n\n".join("\n".join(sorted(g, key=key)) for g in groups if g)
