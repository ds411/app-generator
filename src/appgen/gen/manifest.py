"""The output manifest, and the safe write of a generation result to disk.

The manifest lists each generated file with the SHA-256 hash of its
content, and each extension file apart (ADR 0005). With it, a new run
can delete the generated files that no rule writes any more, and can
see the generated files that a developer changed by hand.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from appgen.gen.generator import GenerationResult

MANIFEST_PATH = ".appgen/manifest.json"
"""The path of the manifest, relative to the output folder."""
MANIFEST_VERSION = 1


def content_hash(content: bytes) -> str:
    """Return the hash of a file content, as the manifest stores it."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class ExtensionEntry:
    """An extension file in the manifest."""

    element_id: str | None
    orphaned: bool = False
    """True if no rule of the last run makes this file: its element left the definition."""


@dataclass(slots=True)
class Manifest:
    """The files that the last run wrote into an output folder."""

    binding: str
    generated: dict[str, str] = field(default_factory=dict[str, str])
    """The hash of each generated file, by path."""
    extensions: dict[str, ExtensionEntry] = field(default_factory=dict[str, ExtensionEntry])

    def to_json(self) -> str:
        """Return the manifest as JSON text, with sorted keys and a final newline."""
        data: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "binding": self.binding,
            "generated": {path: self.generated[path] for path in sorted(self.generated)},
            "extensions": {
                path: {"element": entry.element_id, "orphaned": entry.orphaned}
                for path, entry in sorted(self.extensions.items())
            },
        }
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        """Read a manifest from JSON text. Raise ManifestError if it is not valid."""
        try:
            data = json.loads(text)
            if data["version"] != MANIFEST_VERSION:
                raise ManifestError(f"The manifest version {data['version']!r} is not known.")
            return cls(
                binding=str(data["binding"]),
                generated={str(k): str(v) for k, v in data["generated"].items()},
                extensions={
                    str(k): ExtensionEntry(v["element"], bool(v["orphaned"]))
                    for k, v in data["extensions"].items()
                },
            )
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ManifestError(f"The manifest is not valid: {error}") from None


class ManifestError(Exception):
    """The manifest of the output folder cannot be read."""


class ManualEditsError(Exception):
    """Generated files have manual edits, or the run would overwrite unknown files."""

    def __init__(self, edited: list[str], unknown: list[str]) -> None:
        lines = ["The generator stops, so that it does not destroy manual work."]
        lines += [f"  changed by hand: {path}" for path in edited]
        lines += [f"  not made by appgen: {path}" for path in unknown]
        lines.append("Move the changes to an extension file, or run again with --force.")
        super().__init__("\n".join(lines))
        self.edited = edited
        self.unknown = unknown


@dataclass(slots=True)
class WriteReport:
    """What one write of a generation result did in the output folder."""

    written: list[str] = field(default_factory=list[str])
    """Generated files with new or changed content."""
    unchanged: list[str] = field(default_factory=list[str])
    deleted: list[str] = field(default_factory=list[str])
    """Generated files of the last run that no rule writes any more."""
    created_extensions: list[str] = field(default_factory=list[str])
    kept_extensions: list[str] = field(default_factory=list[str])
    orphaned_extensions: list[str] = field(default_factory=list[str])
    """Extension files whose element left the definition. The generator keeps them."""


def read_manifest(out_dir: Path) -> Manifest | None:
    """Return the manifest of an output folder, or None if it has none."""
    path = out_dir / MANIFEST_PATH
    if not path.is_file():
        return None
    return Manifest.from_json(path.read_text(encoding="utf-8"))


def write_result(
    result: GenerationResult, out_dir: Path, binding: str, *, force: bool = False
) -> WriteReport:
    """Write a generation result into an output folder, and update its manifest.

    Before it writes, the function checks the generated files of the last
    run. A file with a hash that is not the hash in the manifest has
    manual edits. A new generated file at a path that the manifest does
    not know would overwrite a file that appgen did not make. In both
    cases, the function raises ManualEditsError and writes nothing,
    unless `force` is true. The function never overwrites or deletes an
    extension file.
    """
    old = read_manifest(out_dir) or Manifest(binding=binding)
    generated = {f.path: f for f in result.files if f.kind == "generated"}
    extensions = {f.path: f for f in result.files if f.kind == "extension"}
    for path in sorted(set(generated) & set(old.extensions)):
        raise ManifestError(f"The file '{path}' is an extension file. A rule cannot generate it.")

    edited = sorted(
        path
        for path, digest in old.generated.items()
        if (out_dir / path).is_file() and content_hash((out_dir / path).read_bytes()) != digest
    )
    unknown = sorted(
        path for path in generated if path not in old.generated and (out_dir / path).exists()
    )
    if (edited or unknown) and not force:
        raise ManualEditsError(edited, unknown)

    report = WriteReport()
    new = Manifest(binding=binding)
    for path, file in sorted(generated.items()):
        data = file.content.encode("utf-8")
        target = out_dir / path
        new.generated[path] = content_hash(data)
        if target.is_file() and target.read_bytes() == data:
            report.unchanged.append(path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        report.written.append(path)

    for path in sorted(set(old.generated) - set(generated)):
        target = out_dir / path
        if target.is_file():
            target.unlink()
            _remove_empty_parents(target.parent, out_dir)
        report.deleted.append(path)

    for path, file in sorted(extensions.items()):
        target = out_dir / path
        new.extensions[path] = ExtensionEntry(file.element_id)
        if target.exists():
            report.kept_extensions.append(path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.content.encode("utf-8"))
        report.created_extensions.append(path)

    for path, entry in sorted(old.extensions.items()):
        if path not in extensions and (out_dir / path).exists():
            new.extensions[path] = ExtensionEntry(entry.element_id, orphaned=True)
            report.orphaned_extensions.append(path)

    manifest_file = out_dir / MANIFEST_PATH
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_bytes(new.to_json().encode("utf-8"))
    return report


def _remove_empty_parents(folder: Path, root: Path) -> None:
    """Remove the empty folders from `folder` up to, but not including, `root`."""
    while folder != root and folder.is_relative_to(root) and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent
