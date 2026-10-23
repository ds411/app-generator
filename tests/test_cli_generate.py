from pathlib import Path

from typer.testing import CliRunner

from appgen.cli import app
from appgen.gen import MANIFEST_PATH

runner = CliRunner()
TESTS = Path(__file__).parent
DEFINITION = TESTS / "fixtures" / "project-tracker.yaml"
GOLDEN = TESTS / "golden" / "minimal"


def _files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _generate(out: Path, *extra: str, definition: Path = DEFINITION) -> tuple[int, str]:
    result = runner.invoke(
        app, ["generate", str(definition), "--binding", "minimal", "--out", str(out), *extra]
    )
    return result.exit_code, result.output


def test_generate_writes_the_app_and_a_summary(tmp_path: Path) -> None:
    code, output = _generate(tmp_path)
    assert code == 0, output
    assert "Generated 'project-tracker' with the binding 'minimal'" in output
    assert "Files written: 4\n  app.json\n  entities/Project.md\n" in output
    assert "Files deleted: 0" in output
    assert "Gaps created: 7\n" in output
    assert "  operations.complete_task -> gaps/operations.complete_task.md\n" in output
    files = _files(tmp_path)
    assert MANIFEST_PATH in files
    assert {k: v for k, v in files.items() if k != MANIFEST_PATH} == _files(GOLDEN)


def test_two_runs_give_the_same_output(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    assert _generate(first)[0] == 0
    assert _generate(second)[0] == 0
    assert _files(first) == _files(second)
    code, output = _generate(first)
    assert code == 0
    assert "Files written: 0" in output
    assert "Files unchanged: 4" in output
    assert "Gaps created: 0" in output
    assert "Gaps kept (extension files exist): 7" in output


def test_an_invalid_definition_writes_no_file_and_exits_with_1(tmp_path: Path) -> None:
    definition = tmp_path / "bad.yaml"
    definition.write_text("version: 0\napp: { name: x }\nentities: {}\n")
    out = tmp_path / "out"
    code, output = _generate(out, definition=definition)
    assert code == 1
    assert "no file is written" in output
    assert not out.exists()


def test_an_unknown_binding_exits_with_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["generate", str(DEFINITION), "--binding", "cobol", "--out", str(tmp_path / "o")]
    )
    assert result.exit_code == 1
    assert "The binding 'cobol' does not exist" in result.output


def test_manual_edits_stop_the_run_unless_force_is_set(tmp_path: Path) -> None:
    assert _generate(tmp_path)[0] == 0
    (tmp_path / "index.md").write_text("edited\n")
    code, output = _generate(tmp_path)
    assert code == 1
    assert "changed by hand: index.md" in output
    code, output = _generate(tmp_path, "--force")
    assert code == 0
    assert "Files written: 1\n  index.md\n" in output


def test_the_trace_check_passes_on_the_generated_app(tmp_path: Path) -> None:
    assert _generate(tmp_path)[0] == 0
    result = runner.invoke(app, ["check", str(DEFINITION), str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Result: passed." in result.output
