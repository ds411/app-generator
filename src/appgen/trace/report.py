"""Check a code folder against a definition, and write the report as text or JSON."""

import json
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from appgen.dsl.model import AppDefinition
from appgen.trace.coverage import CoverageReport, ElementCoverage, KindCoverage, compute_coverage
from appgen.trace.scanner import DEFAULT_IGNORE, Trace, TraceProblem, scan_folder
from appgen.trace.validity import find_invalid_traces, valid_traces

type ReportFormat = Literal["text", "json"]

REPORT_VERSION = 1
"""The version of the JSON report. A change that breaks readers of the report changes it."""


@dataclass(slots=True)
class CheckReport:
    """The result of a trace check: the coverage and the invalid traces."""

    files: list[str]
    """The scanned files."""
    traces: list[Trace]
    """The valid traces."""
    invalid: list[TraceProblem]
    coverage: CoverageReport
    excluded_kinds: list[str] = field(default_factory=list[str])
    min_coverage: float | None = None
    """The lowest coverage in percent that passes, or None for no limit."""

    @property
    def coverage_too_low(self) -> bool:
        return self.min_coverage is not None and self.coverage.percent < self.min_coverage

    @property
    def passed(self) -> bool:
        """True if there are no invalid traces and the coverage is high enough."""
        return not self.invalid and not self.coverage_too_low

    @property
    def exit_code(self) -> int:
        """0 if the check passed, else 1."""
        return 0 if self.passed else 1


def check_traces(
    definition: AppDefinition,
    code_folder: Path | str,
    *,
    ignore: Iterable[str] = DEFAULT_IGNORE,
    use_gitignore: bool = True,
    exclude_kinds: Iterable[str] = (),
    generated_files: Collection[str] | None = None,
    min_coverage: float | None = None,
) -> CheckReport:
    """Scan a code folder, and compare its traces with a definition."""
    scan = scan_folder(code_folder, ignore=ignore, use_gitignore=use_gitignore)
    invalid = find_invalid_traces(definition, scan, generated_files)
    traces = valid_traces(scan, invalid)
    excluded = sorted(set(exclude_kinds))
    return CheckReport(
        files=scan.files,
        traces=traces,
        invalid=invalid,
        coverage=compute_coverage(definition, traces, excluded),
        excluded_kinds=excluded,
        min_coverage=None if min_coverage is None else float(min_coverage),
    )


def render(report: CheckReport, format: ReportFormat) -> str:
    """Write a report in a format. The text ends with a newline."""
    return render_json(report) if format == "json" else render_text(report)


def render_text(report: CheckReport) -> str:
    """Write a report as text for people."""
    coverage = report.coverage
    lines = [
        f"Trace check: {_count(len(report.files), 'file')}, {_count(len(report.traces), 'trace')}."
    ]

    lines += ["", f"Invalid traces: {len(report.invalid)}"]
    for problem in report.invalid:
        lines.append(
            f"  {problem.file}:{problem.line}:{problem.column}: {problem.code}: {problem.message}"
        )
        lines.append(f"    {problem.text}")
        if problem.hint:
            lines.append(f"    hint: {problem.hint}")

    lines += ["", f"Uncovered elements: {len(coverage.uncovered)}"]
    lines += [f"  {e.element_id} ({e.kind})" for e in coverage.uncovered]

    lines += ["", f"Open gaps: {len(coverage.gaps)}"]
    lines += [f"  {e.element_id} ({e.kind}): {_locations(e)}" for e in coverage.gaps]

    lines += ["", "Coverage:"]
    rows = [["kind", "covered", "gaps", "uncovered", "coverage"]]
    rows += [_kind_row(k) for k in (*coverage.by_kind, coverage.total)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        cells = [
            row[0].ljust(widths[0]),
            *(c.rjust(w) for c, w in zip(row[1:], widths[1:], strict=True)),
        ]
        lines.append("  " + "  ".join(cells))
    if report.excluded_kinds:
        lines.append(f"  Excluded kinds: {', '.join(report.excluded_kinds)}.")

    lines += ["", f"Result: {_result(report)}"]
    return "\n".join(lines) + "\n"


def render_json(report: CheckReport) -> str:
    """Write a report as a stable JSON document: the same report gives the same text."""
    coverage = report.coverage
    document: dict[str, Any] = {
        "version": REPORT_VERSION,
        "passed": report.passed,
        "files": len(report.files),
        "traces": len(report.traces),
        "invalid": [
            {
                "file": p.file,
                "line": p.line,
                "column": p.column,
                "code": p.code,
                "message": p.message,
                "text": p.text,
                "element_id": p.element_id,
                "hint": p.hint,
            }
            for p in report.invalid
        ],
        "uncovered": [{"id": e.element_id, "kind": e.kind} for e in coverage.uncovered],
        "gaps": [
            {
                "id": e.element_id,
                "kind": e.kind,
                "traces": [{"file": t.file, "line": t.line} for t in e.traces],
            }
            for e in coverage.gaps
        ],
        "coverage": {
            **_kind_json(coverage.total),
            "min_percent": report.min_coverage,
            "excluded_kinds": report.excluded_kinds,
            "by_kind": [{"kind": k.kind, **_kind_json(k)} for k in coverage.by_kind],
        },
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _kind_json(kind: KindCoverage) -> dict[str, Any]:
    return {
        "percent": round(kind.percent, 2),
        "total": kind.total,
        "covered": kind.covered,
        "gaps": kind.gaps,
        "uncovered": kind.uncovered,
    }


def _kind_row(kind: KindCoverage) -> list[str]:
    return [
        kind.kind,
        str(kind.covered),
        str(kind.gaps),
        str(kind.uncovered),
        f"{kind.percent:.1f} %",
    ]


def _locations(element: ElementCoverage) -> str:
    return ", ".join(f"{t.file}:{t.line}" for t in element.traces)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _result(report: CheckReport) -> str:
    if report.passed:
        return "passed."
    reasons: list[str] = []
    if report.invalid:
        reasons.append(_count(len(report.invalid), "invalid trace"))
    if report.coverage_too_low:
        reasons.append(
            f"the coverage {report.coverage.percent:.1f} % is lower than "
            f"{report.min_coverage:.1f} %"
        )
    return f"failed: {' and '.join(reasons)}."
