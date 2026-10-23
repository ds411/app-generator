"""Write Python source in the format of the Ruff formatter.

The generated app must pass `ruff format --check`. A call that fits in
the line length stays on one line. A longer call has one argument on
each line and a trailing comma, which the formatter keeps as it is.
"""

LINE_LENGTH = 100


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


def from_import(module: str, names: set[str]) -> str:
    """Return a `from` import with the names in the order of the Ruff import sorter."""

    def key(name: str) -> tuple[int, str]:
        kind = 0 if name.isupper() and len(name) > 1 else 1 if name[0].isupper() else 2
        return (kind, name)

    ordered = sorted(names, key=key)
    line = f"from {module} import {', '.join(ordered)}"
    if len(line) <= LINE_LENGTH:
        return line
    inner = "".join(f"    {name},\n" for name in ordered)
    return f"from {module} import (\n{inner})"


def import_block(lines: set[str]) -> str:
    """Return import lines in the groups and the order of the Ruff import sorter.

    The groups are the standard library, the third-party packages, and the
    app (`app.`). Straight imports (`import x`) come before `from` imports
    in each group.
    """
    stdlib = {"datetime", "decimal", "enum", "typing", "uuid", "collections", "os"}
    groups: list[list[str]] = [[], [], []]
    for line in lines:
        module = line.split()[1]
        root = module.split(".")[0]
        index = 0 if root in stdlib else 2 if root == "app" else 1
        groups[index].append(line)

    def key(line: str) -> tuple[int, str]:
        return (0 if line.startswith("import ") else 1, line.split()[1])

    return "\n\n".join("\n".join(sorted(g, key=key)) for g in groups if g)
