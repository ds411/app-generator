"""The coverage of an app definition by the traces in code (ADR 0004).

- An element with a `gap` trace is an open gap, also when other traces
  refer to it: the generated code that calls a stub has a `generated`
  trace, but the stub still needs hand-written code (ADR 0005).
- An element with a `generated` or a `manual` trace, and no `gap`
  trace, is covered.
- An element with no trace is uncovered.

A trace covers only its own element.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from appgen.dsl.model import AppDefinition
from appgen.gen.elements import iter_elements
from appgen.trace.scanner import Trace

type CoverageStatus = Literal["covered", "gap", "uncovered"]


@dataclass(frozen=True, slots=True)
class ElementCoverage:
    """The coverage of one definition element."""

    element_id: str
    kind: str
    status: CoverageStatus
    traces: tuple[Trace, ...] = ()
    """The traces to the element, sorted by position."""

    @property
    def gap_traces(self) -> tuple[Trace, ...]:
        """The gap traces to the element: where the open work is."""
        return tuple(t for t in self.traces if t.kind == "gap")


@dataclass(slots=True)
class KindCoverage:
    """The counts of the elements of one kind, or of all kinds, by status."""

    kind: str
    covered: int = 0
    gaps: int = 0
    uncovered: int = 0

    @property
    def total(self) -> int:
        return self.covered + self.gaps + self.uncovered

    @property
    def percent(self) -> float:
        """The covered elements as a percentage of all elements. 100 if there are none."""
        return 100.0 if self.total == 0 else 100.0 * self.covered / self.total

    def add(self, status: CoverageStatus) -> None:
        if status == "covered":
            self.covered += 1
        elif status == "gap":
            self.gaps += 1
        else:
            self.uncovered += 1


@dataclass(slots=True)
class CoverageReport:
    """The coverage of each element of a definition, and the totals."""

    elements: list[ElementCoverage] = field(default_factory=list[ElementCoverage])
    """The elements that the coverage counts, in source order."""
    excluded: list[str] = field(default_factory=list[str])
    """The IDs of the elements that the coverage does not count, in source order."""
    by_kind: list[KindCoverage] = field(default_factory=list[KindCoverage])
    """The counts for each element kind, in the order of the first element of the kind."""
    total: KindCoverage = field(default_factory=lambda: KindCoverage("all"))

    @property
    def uncovered(self) -> list[ElementCoverage]:
        """The elements with no trace."""
        return [e for e in self.elements if e.status == "uncovered"]

    @property
    def gaps(self) -> list[ElementCoverage]:
        """The elements with a gap trace: the open gaps."""
        return [e for e in self.elements if e.status == "gap"]

    @property
    def percent(self) -> float:
        return self.total.percent


def compute_coverage(
    definition: AppDefinition, traces: Iterable[Trace], exclude_kinds: Iterable[str] = ()
) -> CoverageReport:
    """Compute the coverage of the elements of a definition by a list of valid traces.

    The coverage does not count the elements of an excluded kind, and the
    elements under them. For example, `exclude_kinds=["ui"]` excludes the
    `ui` section and all its elements. Traces to IDs that the definition
    does not have do not change the coverage.
    """
    exclude = set(exclude_kinds)
    by_id: dict[str, list[Trace]] = {}
    for trace in sorted(traces):
        by_id.setdefault(trace.element_id, []).append(trace)

    report = CoverageReport()
    kinds: dict[str, KindCoverage] = {}
    excluded_roots: list[str] = []
    for element in iter_elements(definition):
        if element.kind in exclude or any(element.id.startswith(f"{r}.") for r in excluded_roots):
            if element.kind in exclude:
                excluded_roots.append(element.id)
            report.excluded.append(element.id)
            continue
        element_traces = tuple(by_id.get(element.id, ()))
        status = _status(element_traces)
        report.elements.append(ElementCoverage(element.id, element.kind, status, element_traces))
        kinds.setdefault(element.kind, KindCoverage(element.kind)).add(status)
        report.total.add(status)
    report.by_kind = list(kinds.values())
    return report


def _status(traces: tuple[Trace, ...]) -> CoverageStatus:
    if any(t.kind == "gap" for t in traces):
        return "gap"
    if traces:
        return "covered"
    return "uncovered"
