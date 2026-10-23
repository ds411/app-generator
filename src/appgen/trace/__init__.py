"""Traces: the scanner and the checker of the traces in code (ADR 0004)."""

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

__all__ = [
    "DEFAULT_IGNORE",
    "TRACE_KINDS",
    "ScanResult",
    "Trace",
    "TraceProblem",
    "comment_openers",
    "scan_folder",
    "scan_text",
]
