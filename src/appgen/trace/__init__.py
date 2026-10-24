"""Traces: the scanner and the checker of the traces in code (ADR 0004)."""

from appgen.trace.coverage import (
    CoverageReport,
    CoverageStatus,
    ElementCoverage,
    KindCoverage,
    compute_coverage,
)
from appgen.trace.orphans import ORPHANS_VERSION, Orphan, find_orphans, render_orphans
from appgen.trace.report import (
    REPORT_VERSION,
    CheckReport,
    ReportFormat,
    check_traces,
    render,
    render_json,
    render_text,
)
from appgen.trace.scanner import (
    DEFAULT_IGNORE,
    TRACE_KINDS,
    ScanResult,
    Trace,
    TraceProblem,
    comment_openers,
    find_skipped_traces,
    scan_folder,
    scan_text,
)
from appgen.trace.validity import (
    find_invalid_traces,
    generated_outside_output,
    suggest_element,
    unknown_elements,
    valid_traces,
)

__all__ = [
    "DEFAULT_IGNORE",
    "ORPHANS_VERSION",
    "REPORT_VERSION",
    "TRACE_KINDS",
    "CheckReport",
    "CoverageReport",
    "CoverageStatus",
    "ElementCoverage",
    "KindCoverage",
    "Orphan",
    "ReportFormat",
    "ScanResult",
    "Trace",
    "TraceProblem",
    "check_traces",
    "comment_openers",
    "compute_coverage",
    "find_invalid_traces",
    "find_orphans",
    "find_skipped_traces",
    "generated_outside_output",
    "render",
    "render_json",
    "render_orphans",
    "render_text",
    "scan_folder",
    "scan_text",
    "suggest_element",
    "unknown_elements",
    "valid_traces",
]
