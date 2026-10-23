"""Find the invalid traces of a code folder (ADR 0004)."""

import difflib
from collections.abc import Collection, Iterable

from appgen.dsl.model import AppDefinition
from appgen.trace.scanner import ScanResult, Trace, TraceProblem


def find_invalid_traces(
    definition: AppDefinition, scan: ScanResult, generated_files: Collection[str] | None = None
) -> list[TraceProblem]:
    """Return the invalid traces of a scan, sorted by position.

    These are the malformed traces that the scanner found, and the traces
    to element IDs that the definition does not have. If the list of
    generated files (from the output manifest) is given, a `generated`
    trace in another file is also invalid.
    """
    problems = list(scan.problems)
    problems.extend(unknown_elements(definition, scan.traces))
    if generated_files is not None:
        problems.extend(generated_outside_output(scan.traces, generated_files))
    return sorted(problems)


def valid_traces(scan: ScanResult, problems: Iterable[TraceProblem]) -> list[Trace]:
    """Return the traces of a scan that have no problem."""
    invalid = {(p.file, p.line, p.column) for p in problems}
    return [t for t in scan.traces if (t.file, t.line, t.column) not in invalid]


def unknown_elements(definition: AppDefinition, traces: Iterable[Trace]) -> list[TraceProblem]:
    """Return a problem for each trace to an element ID that the definition does not have."""
    ids = list(definition.elements)
    problems: list[TraceProblem] = []
    for trace in traces:
        if trace.element_id in definition.elements:
            continue
        match = difflib.get_close_matches(trace.element_id, ids, n=1)
        problems.append(
            TraceProblem.of(
                trace,
                "unknown-element",
                f"The definition has no element '{trace.element_id}'.",
                hint=f"Did you mean '{match[0]}'?" if match else None,
            )
        )
    return problems


def generated_outside_output(
    traces: Iterable[Trace], generated_files: Collection[str]
) -> list[TraceProblem]:
    """Return a problem for each `generated` trace in a file that the generator did not write."""
    return [
        TraceProblem.of(
            trace,
            "generated-trace-in-manual-file",
            "A generated trace is in a file that the generator did not write.",
            hint=f"Change the trace to '@trace:manual {trace.element_id}' for hand-written code.",
        )
        for trace in traces
        if trace.kind == "generated" and trace.file not in generated_files
    ]
