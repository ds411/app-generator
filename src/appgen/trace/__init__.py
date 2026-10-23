"""Traces: the scanner and the checker of the traces in code (ADR 0004)."""

from appgen.trace.coverage import (
    CoverageReport,
    CoverageStatus,
    ElementCoverage,
    KindCoverage,
    compute_coverage,
)
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
    "REPORT_VERSION",
    "TRACE_KINDS",
    "CheckReport",
    "CoverageReport",
    "CoverageStatus",
    "ElementCoverage",
    "KindCoverage",
    "ReportFormat",
    "ScanResult",
    "Trace",
    "TraceProblem",
    "check_traces",
    "comment_openers",
    "compute_coverage",
    "find_invalid_traces",
    "find_skipped_traces",
    "generated_outside_output",
    "render",
    "render_json",
    "render_text",
    "scan_folder",
    "scan_text",
    "suggest_element",
    "unknown_elements",
    "valid_traces",
]
