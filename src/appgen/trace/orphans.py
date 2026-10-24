"""Find the orphaned extension files of a code folder (ADR 0005).

An extension file is orphaned when no rule of the last run makes it any
more, because its element left the definition, for example after a
rename. The generator keeps the file, so that the hand-written code
stays. This module lists these files, and the element that most likely
replaces the element of each file.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from appgen.dsl.model import AppDefinition
from appgen.gen.manifest import Manifest
from appgen.trace.validity import suggest_element

ORPHANS_VERSION = 1
"""The version of the JSON output. A change that breaks readers of the output changes it."""


@dataclass(frozen=True, slots=True)
class Orphan:
    """An orphaned extension file."""

    file: str
    """The path relative to the code folder, with `/` as separator."""
    element_id: str | None
    """The element of the file in the manifest."""
    suggestion: str | None
    """The element that most likely replaces the element of the file, or None."""


def find_orphans(
    definition: AppDefinition, code_folder: Path | str, manifest: Manifest
) -> list[Orphan]:
    """Return the orphaned extension files that are still in a code folder, sorted by path.

    These are the extension files that the manifest marks as orphaned, or
    whose element the definition does not have. The function reads no
    file and changes no file.
    """
    root = Path(code_folder)
    orphans: list[Orphan] = []
    for path, entry in sorted(manifest.extensions.items()):
        known = entry.element_id is not None and entry.element_id in definition.elements
        if (known and not entry.orphaned) or not (root / path).is_file():
            continue
        suggestion = None
        if entry.element_id is not None:
            suggestion = (
                entry.element_id
                if known
                else (suggest_element(definition, entry.element_id, manifest))
            )
        orphans.append(Orphan(path, entry.element_id, suggestion))
    return orphans


def render_orphans(orphans: list[Orphan], format: str) -> str:
    """Write the orphaned extension files as text or JSON. The text ends with a newline."""
    if format == "json":
        document: dict[str, Any] = {
            "version": ORPHANS_VERSION,
            "orphans": [
                {"file": o.file, "element_id": o.element_id, "suggestion": o.suggestion}
                for o in orphans
            ],
        }
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    lines = [f"Orphaned extension files: {len(orphans)}"]
    for orphan in orphans:
        lines.append(f"  {orphan.file}: {orphan.element_id or 'no element'}")
        if orphan.suggestion:
            lines.append(f"    suggestion: move the code to the element '{orphan.suggestion}'.")
        else:
            lines.append("    suggestion: move the code to another element, or delete the file.")
    return "\n".join(lines) + "\n"
