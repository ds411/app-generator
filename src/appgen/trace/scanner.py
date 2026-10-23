"""Find the traces in a code folder with a text scan (ADR 0004).

The scanner reads generated code and hand-written code alike. It reads
each file of a known file type line by line, and finds each `@trace` tag
that follows a comment opener of the file type on the same line.
"""

import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

import pathspec

type Scope = Literal["line", "file", "begin", "end"]

TRACE_KINDS: tuple[str, ...] = ("generated", "gap", "manual")
"""The kinds of trace. A trace without a kind is `generated`."""

DEFAULT_IGNORE: tuple[str, ...] = (
    ".git/",
    ".next/",
    ".pnpm-store/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "__pycache__/",
    "node_modules/",
)
"""The paths that the scanner skips if no other ignore list is given (gitignore syntax)."""

# The regular expression of ADR 0004, applied at the position of the tag.
TRACE_PATTERN = re.compile(
    r"@trace(?::(?P<kind>[a-z]+))?[ \t]+(?P<id>[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)"
    r"(?:[ \t]+(?P<scope>file|begin|end)\b)?"
)
# A word after the ID that is the only other text in the comment. It is
# not an explanation, so it is a scope word that the syntax does not know.
_UNKNOWN_SCOPE = re.compile(r"[ \t]+(?P<word>[A-Za-z]+)[ \t]*(?:\*/\}?|-->)?[ \t]*$")

_SLASH = ("//", "/*")
_HASH = ("#",)
_MARKUP = ("<!--",)
_SUFFIX_OPENERS: dict[str, tuple[str, ...]] = {
    ".ts": _SLASH,
    ".mts": _SLASH,
    ".cts": _SLASH,
    ".js": _SLASH,
    ".mjs": _SLASH,
    ".cjs": _SLASH,
    ".tsx": _SLASH,
    ".jsx": _SLASH,
    ".py": _HASH,
    ".pyi": _HASH,
    ".sql": ("--",),
    ".css": ("/*",),
    ".dockerfile": _HASH,
    ".yaml": _HASH,
    ".yml": _HASH,
    ".toml": _HASH,
    ".sh": _HASH,
    ".env": _HASH,
    ".md": _MARKUP,
    ".html": _MARKUP,
}
_BLOCK_CLOSERS: dict[str, str] = {"/*": "*/", "<!--": "-->"}


@dataclass(frozen=True, slots=True, order=True)
class Trace:
    """One trace in a code file. The line and the column start at 1."""

    file: str
    """The path relative to the scanned folder, with `/` as separator."""
    line: int
    column: int
    element_id: str
    kind: str
    """`generated`, `gap`, or `manual`."""
    scope: Scope
    text: str
    """The text of the trace, for example `@trace:gap operations.complete_task begin`."""

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}: {self.text}"


@dataclass(frozen=True, slots=True, order=True)
class TraceProblem:
    """A trace that is not valid, with the reason."""

    file: str
    line: int
    column: int
    code: str
    """A short, stable name for the kind of problem, for example `unknown-kind`."""
    message: str
    text: str
    """The text of the trace on the line, from the tag to the end of the trace."""
    element_id: str | None = None
    hint: str | None = None

    @classmethod
    def of(cls, trace: Trace, code: str, message: str, hint: str | None = None) -> TraceProblem:
        """Make a problem at the position of a trace."""
        return cls(
            file=trace.file,
            line=trace.line,
            column=trace.column,
            code=code,
            message=message,
            text=trace.text,
            element_id=trace.element_id,
            hint=hint,
        )

    def __str__(self) -> str:
        text = f"{self.file}:{self.line}:{self.column}: error[{self.code}]: {self.message}"
        if self.hint:
            text += f"\n  hint: {self.hint}"
        return text


@dataclass(slots=True)
class ScanResult:
    """The traces and the malformed traces of a code folder, sorted by position."""

    traces: list[Trace] = field(default_factory=list[Trace])
    problems: list[TraceProblem] = field(default_factory=list[TraceProblem])
    files: list[str] = field(default_factory=list[str])
    """The scanned files: the files of a known file type that are not ignored."""


def comment_openers(path: str) -> tuple[str, ...] | None:
    """Return the comment openers of the file type of a path, or None for other files."""
    name = PurePosixPath(path).name
    if name == "Dockerfile" or name.startswith("Dockerfile."):
        return _HASH
    if name == ".env" or name.startswith(".env."):
        return _HASH
    return _SUFFIX_OPENERS.get(PurePosixPath(name).suffix)


def scan_folder(
    root: Path | str, ignore: Iterable[str] = DEFAULT_IGNORE, use_gitignore: bool = True
) -> ScanResult:
    """Find the traces in each file of a known file type under a folder.

    The scanner skips the paths that match a pattern of the ignore list
    (gitignore syntax), and, if `use_gitignore` is true, the paths that a
    `.gitignore` file in the folder or a subfolder ignores.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"'{root}' is not a folder.")
    result = ScanResult()
    for path in _walk(root, pathspec.GitIgnoreSpec.from_lines(ignore), use_gitignore):
        data = (root / path).read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        traces, problems = scan_text(text, path)
        result.files.append(path)
        result.traces.extend(traces)
        result.problems.extend(problems)
    result.traces.sort()
    result.problems.sort()
    return result


def scan_text(text: str, path: str) -> tuple[list[Trace], list[TraceProblem]]:
    """Find the traces in the text of one file. The path gives the file type.

    A file of an unknown type has no traces.
    """
    openers = comment_openers(path)
    if openers is None:
        return [], []
    tag = re.compile(
        "(?:" + "|".join(re.escape(o) for o in openers) + r")[ \t]*(?P<tag>@trace)(?![A-Za-z0-9_])"
    )
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    header = _header_lines(lines, openers)
    traces: list[Trace] = []
    problems: list[TraceProblem] = []
    blocks: list[Trace] = []
    for number, line in enumerate(lines, start=1):
        for found in tag.finditer(line):
            start = found.start("tag")
            trace, problem = _parse(line, start, path, number)
            if problem is not None:
                problems.append(problem)
                continue
            assert trace is not None
            if trace.scope == "file" and number not in header:
                problems.append(
                    TraceProblem.of(
                        trace,
                        "file-trace-not-in-header",
                        "A file trace must be in the header of the file: the comment lines "
                        "and blank lines at the top.",
                    )
                )
            elif trace.scope == "begin":
                blocks.append(trace)
            elif trace.scope == "end":
                problem = _close_block(blocks, trace)
                if problem is None:
                    traces.append(blocks.pop())
                    traces.append(trace)
                else:
                    if blocks:
                        traces.append(blocks.pop())
                    problems.append(problem)
            else:
                traces.append(trace)
    problems.extend(
        TraceProblem.of(
            begin,
            "unclosed-block",
            f"The block trace of '{begin.element_id}' has no end.",
            hint=f"Add '@trace{_kind_text(begin.kind)} {begin.element_id} end' after the block.",
        )
        for begin in blocks
    )
    traces.sort()
    problems.sort()
    return traces, problems


def _parse(
    line: str, start: int, path: str, number: int
) -> tuple[Trace | None, TraceProblem | None]:
    match = TRACE_PATTERN.match(line, start)
    column = start + 1
    if match is None:
        rest = line[start:].strip()
        return None, TraceProblem(
            file=path,
            line=number,
            column=column,
            code="malformed-trace",
            message="The trace has no valid element ID.",
            text=rest,
            hint="Write the trace as '@trace[:kind] <element-id> [file|begin|end]'.",
        )
    text = match.group(0)
    element_id = match.group("id")
    kind = match.group("kind") or "generated"
    if kind not in TRACE_KINDS:
        return None, TraceProblem(
            file=path,
            line=number,
            column=column,
            code="unknown-kind",
            message=f"The trace kind '{kind}' is not known.",
            text=text,
            element_id=element_id,
            hint="The kinds are: " + ", ".join(TRACE_KINDS) + ".",
        )
    scope = match.group("scope")
    if scope is None:
        unknown = _UNKNOWN_SCOPE.match(line, match.end())
        if unknown is not None:
            word = unknown.group("word")
            return None, TraceProblem(
                file=path,
                line=number,
                column=column,
                code="unknown-scope",
                message=f"The scope word '{word}' is not known.",
                text=f"{text} {word}",
                element_id=element_id,
                hint="The scope words are: file, begin, end. A line trace has no scope word.",
            )
    trace = Trace(
        file=path,
        line=number,
        column=column,
        element_id=element_id,
        kind=kind,
        scope=scope or "line",  # pyright: ignore[reportArgumentType]
        text=text,
    )
    return trace, None


def _close_block(blocks: list[Trace], end: Trace) -> TraceProblem | None:
    """Check that an end trace closes the innermost open block."""
    if not blocks:
        return TraceProblem.of(
            end,
            "unmatched-end",
            f"The end trace of '{end.element_id}' has no begin trace.",
        )
    begin = blocks[-1]
    if (begin.kind, begin.element_id) != (end.kind, end.element_id):
        return TraceProblem.of(
            end,
            "mismatched-end",
            f"The end trace does not agree with the innermost open block: "
            f"'@trace{_kind_text(begin.kind)} {begin.element_id} begin' on line {begin.line}.",
            hint="Blocks can nest, but they cannot overlap.",
        )
    return None


def _kind_text(kind: str) -> str:
    return "" if kind == "generated" else f":{kind}"


def _header_lines(lines: list[str], openers: tuple[str, ...]) -> set[int]:
    """Return the numbers of the lines of the file header: the comment and blank lines at the top.

    A shebang can come before the header.
    """
    header: set[int] = set()
    closer: str | None = None
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if closer is not None:
            header.add(number)
            if closer in stripped:
                closer = None
            continue
        if not stripped or (number == 1 and stripped.startswith("#!")):
            header.add(number)
            continue
        opener = next((o for o in openers if stripped.startswith(o)), None)
        if opener is None:
            break
        header.add(number)
        block_closer = _BLOCK_CLOSERS.get(opener)
        if block_closer is not None and block_closer not in stripped[len(opener) :]:
            closer = block_closer
    return header


def _walk(root: Path, ignore: pathspec.GitIgnoreSpec, use_gitignore: bool) -> Iterator[str]:
    """Yield the paths of the files of a known type under a folder, sorted, without ignored ones."""
    gitignores: list[tuple[str, pathspec.GitIgnoreSpec]] = []

    def ignored(path: str, is_dir: bool) -> bool:
        candidate = path + "/" if is_dir else path
        if ignore.match_file(candidate):
            return True
        for base, spec in gitignores:
            if base and not candidate.startswith(base + "/"):
                continue
            relative = candidate[len(base) + 1 :] if base else candidate
            if spec.match_file(relative):
                return True
        return False

    for folder, dirs, files in os.walk(root):
        base = Path(folder).relative_to(root).as_posix()
        base = "" if base == "." else base
        if use_gitignore and ".gitignore" in files:
            lines = (Path(folder) / ".gitignore").read_text(encoding="utf-8").splitlines()
            gitignores.append((base, pathspec.GitIgnoreSpec.from_lines(lines)))
        prefix = f"{base}/" if base else ""
        dirs[:] = sorted(d for d in dirs if not ignored(prefix + d, is_dir=True))
        for name in sorted(files):
            path = prefix + name
            if comment_openers(path) is not None and not ignored(path, is_dir=False):
                yield path
