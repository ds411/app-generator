"""Traces: the scanner and the checker of the traces in code (ADR 0004)."""

from appgen.trace.coverage import (
    CoverageReport,
    CoverageStatus,
    ElementCoverage,
    KindCoverage,
    compute_coverage,
)
from appgen.trace.scanner import (
    DEFAULT_IGNORE,
    TRACE_KINDS,
    ScanResult,
    Trace,
    TraceProblem,
    comment_openers,
    scan_folder,
    scan_text,
)
from appgen.trace.validity import (
    find_invalid_traces,
    generated_outside_output,
    unknown_elements,
    valid_traces,
)

__all__ = [
    "DEFAULT_IGNORE",
    "TRACE_KINDS",
    "CoverageReport",
    "CoverageStatus",
    "ElementCoverage",
    "KindCoverage",
    "ScanResult",
    "Trace",
    "TraceProblem",
    "comment_openers",
    "compute_coverage",
    "find_invalid_traces",
    "generated_outside_output",
    "scan_folder",
    "scan_text",
    "unknown_elements",
    "valid_traces",
]
