"""Make the DSL reference of the agent skill from docs/dsl.md (ADR 0015).

The installed skill has only its own files, so the reference of the
skill (`src/appgen/skills/appgen/references/dsl.md`) changes the links
to other files of the repository into links to the files on GitHub. A
link to a section of the same page stays as it is.

Run it after each change to docs/dsl.md:

    uv run scripts/update_skill_references.py

With `--check`, the script writes no file, and exits with 1 if the
reference of the skill is out of date. `tests/test_skill_new_definition.py`
runs the check.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "dsl.md"
TARGET = ROOT / "src" / "appgen" / "skills" / "appgen" / "references" / "dsl.md"
GITHUB = "https://github.com/ds411/app-generator"

HEADER = "<!-- Made from docs/dsl.md by scripts/update_skill_references.py. Do not edit. -->\n\n"
_LINK = re.compile(r"\]\(([^)#\s]+)((?:#[^)]*)?)\)")
_EXAMPLE_PATH = re.compile(r"(?<!\[)`(examples/[^`\s]+)`")


def _github_url(path: str) -> str:
    """Return the GitHub URL of a path of the repository, for example `docs/adr/0002-x.md`."""
    kind = "tree" if path.endswith("/") else "blob"
    return f"{GITHUB}/{kind}/main/{path}"


def skill_dsl_reference(text: str) -> str:
    """Return the DSL reference of the skill, made from the text of docs/dsl.md."""

    def link(match: re.Match[str]) -> str:
        target, anchor = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "mailto:")):
            return match.group(0)
        path = (SOURCE.parent / target).resolve().relative_to(ROOT).as_posix()
        if target.endswith("/"):
            path += "/"
        return f"]({_github_url(path)}{anchor})"

    text = _LINK.sub(link, text)
    text = _EXAMPLE_PATH.sub(lambda m: f"[`{m.group(1)}`]({_github_url(m.group(1))})", text)
    return HEADER + text


def main(argv: list[str]) -> int:
    expected = skill_dsl_reference(SOURCE.read_text(encoding="utf-8"))
    current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else None
    if "--check" in argv:
        if current != expected:
            print(
                f"{TARGET.relative_to(ROOT)} is out of date. "
                "Run 'uv run scripts/update_skill_references.py'.",
                file=sys.stderr,
            )
            return 1
        return 0
    if current != expected:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8", newline="\n")
        print(f"Wrote {TARGET.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
