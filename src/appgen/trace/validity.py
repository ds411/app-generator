"""Find the invalid traces of a code folder (ADR 0004)."""

import difflib
from collections.abc import Collection, Iterable

from appgen.dsl.model import AppDefinition
from appgen.gen.elements import iter_elements
from appgen.gen.manifest import Manifest
from appgen.trace.scanner import ScanResult, Trace, TraceProblem


def find_invalid_traces(
    definition: AppDefinition,
    scan: ScanResult,
    generated_files: Collection[str] | None = None,
    manifest: Manifest | None = None,
) -> list[TraceProblem]:
    """Return the invalid traces of a scan, sorted by position.

    These are the malformed traces that the scanner found, and the traces
    to element IDs that the definition does not have. If the list of
    generated files (from the output manifest) is given, a `generated`
    trace in another file is also invalid. The manifest, if given, helps
    the hint to find the new name of a renamed element.
    """
    problems = list(scan.problems)
    problems.extend(unknown_elements(definition, scan.traces, manifest))
    if generated_files is not None:
        problems.extend(generated_outside_output(scan.traces, generated_files))
    return sorted(problems)


def valid_traces(scan: ScanResult, problems: Iterable[TraceProblem]) -> list[Trace]:
    """Return the traces of a scan that have no problem."""
    invalid = {(p.file, p.line, p.column) for p in problems}
    return [t for t in scan.traces if (t.file, t.line, t.column) not in invalid]


def unknown_elements(
    definition: AppDefinition, traces: Iterable[Trace], manifest: Manifest | None = None
) -> list[TraceProblem]:
    """Return a problem for each trace to an element ID that the definition does not have.

    The hint of each problem suggests an element (see `suggest_element`).
    """
    problems: list[TraceProblem] = []
    for trace in traces:
        if trace.element_id in definition.elements:
            continue
        match = suggest_element(definition, trace.element_id, manifest)
        problems.append(
            TraceProblem.of(
                trace,
                "unknown-element",
                f"The definition has no element '{trace.element_id}'.",
                hint=f"Did you mean '{match}'?" if match else None,
            )
        )
    return problems


def suggest_element(
    definition: AppDefinition, element_id: str, manifest: Manifest | None = None
) -> str | None:
    """Return the element that most likely replaces an element ID that the definition does not have.

    If the manifest knows the ID as an element of an earlier run, the
    suggestion has the same kind: an element that is new since the earlier
    runs (a rename), else an element with a similar spelling. Without this
    data, the suggestion is the ID with the most similar spelling, or None.
    """
    kind = manifest.removed.get(element_id) if manifest is not None else None
    if manifest is None or kind is None:
        match = difflib.get_close_matches(element_id, list(definition.elements), n=1)
        return match[0] if match else None
    same_kind = [e.id for e in iter_elements(definition) if e.kind == kind]
    added = set(manifest.added)
    new = [i for i in same_kind if i in added]
    if new:
        return difflib.get_close_matches(element_id, new, n=1, cutoff=0)[0]
    match = difflib.get_close_matches(element_id, same_kind, n=1)
    return match[0] if match else None


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
