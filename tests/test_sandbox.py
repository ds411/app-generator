"""Tests of the setup files for Claude Code cloud sessions (the sandbox)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SANDBOX_ENV = ROOT / "scripts" / "sandbox.env"
_ROW = re.compile(r"^\| `([A-Z_]+)` +\| `([^`]+)` +\|$", re.MULTILINE)


def _sandbox_variables(environment: dict[str, str]) -> dict[str, str]:
    names = sorted(_documented_variables())
    script = f'. "{SANDBOX_ENV}"; ' + "; ".join(f'printf "%s=%s\\n" {n} "${n}"' for n in names)
    output = subprocess.run(
        ["sh", "-c", script], env=environment, capture_output=True, text=True, check=True
    ).stdout
    return dict(line.split("=", 1) for line in output.splitlines())


def _documented_variables() -> dict[str, str]:
    section = (ROOT / "CONTRIBUTING.md").read_text().split("## Cloud sessions", 1)[1]
    return dict(_ROW.findall(section.split("\n## ", 1)[0]))


def test_contributing_lists_the_values_of_the_sandbox_env_file() -> None:
    documented = _documented_variables()
    assert "POSTGRES_IMAGE" in documented
    assert _sandbox_variables({"PATH": "/usr/bin:/bin"}) == documented


def test_the_sandbox_env_file_keeps_the_values_of_the_environment() -> None:
    values = _sandbox_variables({"PATH": "/usr/bin:/bin", "POSTGRES_IMAGE": "postgres:18"})
    assert values["POSTGRES_IMAGE"] == "postgres:18"


def test_the_sandbox_env_file_removes_the_deprecated_uv_variable() -> None:
    script = f'. "{SANDBOX_ENV}"; echo "${{UV_NATIVE_TLS-unset}}"'
    environment = {"PATH": "/usr/bin:/bin", "UV_NATIVE_TLS": "true"}
    output = subprocess.run(
        ["sh", "-c", script], env=environment, capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "unset"
