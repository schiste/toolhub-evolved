# SPDX-License-Identifier: GPL-3.0-or-later
"""The post-deploy smoke check must keep an interpreter on the raw-source path.

tools/deploy.sh builds dist/ only when the webservice venv exists; without it the
app serves raw source, which the script documents as a supported deployment. The
smoke check that follows is not optional in that path -- it is what decides
whether to roll back -- so invoking it through the venv interpreter would run a
nonexistent command and report every such deploy as a smoke failure, after the
restart had already happened.

The resolution block is exercised here as it ships, cut out of the real file.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "tools" / "deploy.sh"


def _resolution_fragment() -> str:
    """The shipped interpreter resolution, reporting what it chose."""
    source = DEPLOY.read_text(encoding="utf-8")
    start, end = 'VENV_PY="', 'deployment_diagnostics="'
    assert start in source and end in source, "deploy.sh no longer resolves the interpreter where this test cuts it"
    return source[source.index(start) : source.index(end)] + 'echo "TOOL_PY=$TOOL_PY"\n'


def _run(home: Path, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        # Absolute, so that starving PATH below starves only the script's own
        # lookup for python3 and not this call's lookup for the shell.
        ["/bin/sh", "-c", _resolution_fragment()],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": path},
        timeout=60,
        check=False,
    )


def test_a_deploy_without_the_venv_still_resolves_a_smoke_interpreter(tmp_path: Path) -> None:
    result = _run(tmp_path, os.environ["PATH"])

    assert result.returncode == 0, result.stderr
    resolved = result.stdout.strip().removeprefix("TOOL_PY=")
    assert resolved, "the raw-source deploy path was left without an interpreter"
    assert os.access(resolved, os.X_OK), f"{resolved} is not executable, so the smoke check would fail spuriously"


def test_the_venv_interpreter_is_still_preferred_when_it_exists(tmp_path: Path) -> None:
    """Guard the guard: falling back unconditionally would drop the venv's deps."""
    venv_bin = tmp_path / "www" / "python" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.write_text("#!/bin/sh\n")
    venv_python.chmod(0o755)

    result = _run(tmp_path, os.environ["PATH"])

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"TOOL_PY={venv_python}"


def test_no_interpreter_at_all_aborts_before_the_restart(tmp_path: Path) -> None:
    result = _run(tmp_path, "")

    assert result.returncode == 1
    assert "aborting before restart" in result.stderr
    assert "TOOL_PY=" not in result.stdout
