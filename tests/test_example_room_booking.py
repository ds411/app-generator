"""The second example: generate and check the room booking app with each binding.

The project tracker drives most tests. A second definition for another
domain shows which DSL features the tracker does not use (#185).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from appgen.cli import app

EXAMPLE = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"

runner = CliRunner()


@pytest.fixture(scope="module", params=["fastapi", "nextjs", "react"])
def generated(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Any:
    binding: str = request.param
    out = tmp_path_factory.mktemp(binding)
    result = runner.invoke(app, ["generate", str(EXAMPLE), "-b", binding, "-o", str(out)])
    assert result.exit_code == 0, result.output
    return binding, out


def test_the_check_of_each_app_passes(generated: Any) -> None:
    _, out = generated
    result = runner.invoke(app, ["check", str(EXAMPLE), str(out), "-f", "json"])
    report = json.loads(result.output)
    assert result.exit_code == 0
    assert report["invalid"] == []
    assert report["uncovered"] == []


def test_a_menu_without_groups_imports_no_group_content(generated: Any) -> None:
    binding, out = generated
    if binding == "fastapi":
        pytest.skip("A back end has no menu.")
    menu = (out / "src/widgets/navigation/ui/main-menu.tsx").read_text()
    assert "SidebarGroupContent" not in menu
