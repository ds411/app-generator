from pathlib import Path

import pytest

from appgen.gen import (
    MANIFEST_PATH,
    GeneratedFile,
    GenerationResult,
    ManualEditsError,
    read_manifest,
    write_result,
)
from appgen.gen.manifest import Manifest, ManifestError, content_hash


def _result(*files: GeneratedFile) -> GenerationResult:
    return GenerationResult(files=list(files))


def _ext(path: str, content: str, element_id: str) -> GeneratedFile:
    return GeneratedFile(path, content, kind="extension", element_id=element_id)


def test_the_manifest_lists_each_generated_file_and_its_hash(tmp_path: Path) -> None:
    report = write_result(_result(GeneratedFile("a/b.txt", "b\n")), tmp_path, "minimal")
    assert report.written == ["a/b.txt"]
    manifest = read_manifest(tmp_path)
    assert manifest == Manifest("minimal", {"a/b.txt": content_hash(b"b\n")})
    assert (tmp_path / "a" / "b.txt").read_bytes() == b"b\n"


def test_the_manifest_is_deterministic(tmp_path: Path) -> None:
    result = _result(GeneratedFile("z.txt", "z\n"), GeneratedFile("a.txt", "a\n"))
    write_result(result, tmp_path, "minimal")
    first = (tmp_path / MANIFEST_PATH).read_bytes()
    report = write_result(result, tmp_path, "minimal")
    assert (tmp_path / MANIFEST_PATH).read_bytes() == first
    assert report.written == []
    assert report.unchanged == ["a.txt", "z.txt"]
    assert first.index(b'"a.txt"') < first.index(b'"z.txt"')


def test_a_file_that_no_rule_writes_any_more_is_deleted(tmp_path: Path) -> None:
    write_result(
        _result(GeneratedFile("old/x.txt", "x\n"), GeneratedFile("keep.txt", "k\n")), tmp_path, "m"
    )
    report = write_result(_result(GeneratedFile("keep.txt", "k\n")), tmp_path, "m")
    assert report.deleted == ["old/x.txt"]
    assert not (tmp_path / "old").exists()
    manifest = read_manifest(tmp_path)
    assert manifest is not None and list(manifest.generated) == ["keep.txt"]


def test_a_file_with_manual_edits_stops_the_run(tmp_path: Path) -> None:
    write_result(
        _result(GeneratedFile("a.txt", "a\n"), GeneratedFile("b.txt", "b\n")), tmp_path, "m"
    )
    (tmp_path / "a.txt").write_text("edited\n")
    with pytest.raises(ManualEditsError, match=r"changed by hand: a\.txt") as error:
        write_result(
            _result(GeneratedFile("a.txt", "new a\n"), GeneratedFile("b.txt", "new b\n")),
            tmp_path,
            "m",
        )
    assert error.value.edited == ["a.txt"]
    # The run writes nothing.
    assert (tmp_path / "a.txt").read_text() == "edited\n"
    assert (tmp_path / "b.txt").read_text() == "b\n"


def test_a_stale_file_with_manual_edits_stops_the_run(tmp_path: Path) -> None:
    write_result(_result(GeneratedFile("a.txt", "a\n")), tmp_path, "m")
    (tmp_path / "a.txt").write_text("edited\n")
    with pytest.raises(ManualEditsError):
        write_result(_result(), tmp_path, "m")
    assert (tmp_path / "a.txt").exists()


def test_force_overwrites_manual_edits(tmp_path: Path) -> None:
    write_result(_result(GeneratedFile("a.txt", "a\n")), tmp_path, "m")
    (tmp_path / "a.txt").write_text("edited\n")
    report = write_result(_result(GeneratedFile("a.txt", "a\n")), tmp_path, "m", force=True)
    assert report.written == ["a.txt"]
    assert (tmp_path / "a.txt").read_text() == "a\n"


def test_a_file_that_appgen_did_not_make_stops_the_run(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("mine\n")
    with pytest.raises(ManualEditsError, match=r"not made by appgen: a\.txt"):
        write_result(_result(GeneratedFile("a.txt", "a\n")), tmp_path, "m")
    assert (tmp_path / "a.txt").read_text() == "mine\n"


def test_extension_files_are_listed_apart_and_created_once(tmp_path: Path) -> None:
    result = _result(GeneratedFile("a.gen.ts", "g\n"), _ext("a.ext.ts", "stub\n", "operations.a"))
    report = write_result(result, tmp_path, "m")
    assert report.created_extensions == ["a.ext.ts"]
    manifest = read_manifest(tmp_path)
    assert manifest is not None
    assert list(manifest.generated) == ["a.gen.ts"]
    assert manifest.extensions["a.ext.ts"].element_id == "operations.a"

    (tmp_path / "a.ext.ts").write_text("hand-written\n")
    report = write_result(result, tmp_path, "m")
    assert report.kept_extensions == ["a.ext.ts"]
    assert (tmp_path / "a.ext.ts").read_text() == "hand-written\n"


def test_extension_files_are_never_deleted(tmp_path: Path) -> None:
    write_result(_result(_ext("a.ext.ts", "stub\n", "operations.a")), tmp_path, "m")
    (tmp_path / "a.ext.ts").write_text("hand-written\n")
    report = write_result(_result(), tmp_path, "m")
    assert report.orphaned_extensions == ["a.ext.ts"]
    assert report.deleted == []
    assert (tmp_path / "a.ext.ts").read_text() == "hand-written\n"
    manifest = read_manifest(tmp_path)
    assert manifest is not None and manifest.extensions["a.ext.ts"].orphaned

    # When the developer deletes the orphaned file, the manifest forgets it.
    (tmp_path / "a.ext.ts").unlink()
    write_result(_result(), tmp_path, "m")
    manifest = read_manifest(tmp_path)
    assert manifest is not None and manifest.extensions == {}


def test_a_rule_cannot_generate_an_extension_file(tmp_path: Path) -> None:
    write_result(_result(_ext("a.ts", "stub\n", "operations.a")), tmp_path, "m")
    with pytest.raises(ManifestError, match="extension file"):
        write_result(_result(GeneratedFile("a.ts", "g\n")), tmp_path, "m")


def test_a_manifest_that_is_not_valid_is_an_error(tmp_path: Path) -> None:
    (tmp_path / ".appgen").mkdir()
    (tmp_path / MANIFEST_PATH).write_text("{}")
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)
