# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the scheduler circuit breaker wrapper."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "job_guard.sh"


def run_guard(state_dir: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(GUARD), "--job-name", "example", "--", *command],
        cwd=ROOT,
        env={"HOME": str(state_dir), "TOOLHUB_JOB_GUARD_DIR": str(state_dir / "guard")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_guard_disables_after_three_failures_and_skips_child(tmp_path):
    marker = tmp_path / "runs"
    failing_command = ("sh", "-c", f"echo run >> {marker}; exit 7")

    for _ in range(3):
        result = run_guard(tmp_path, *failing_command)
        assert result.returncode == 7

    assert marker.read_text().splitlines() == ["run", "run", "run"]
    disabled = run_guard(tmp_path, *failing_command)
    assert disabled.returncode == 0
    assert "disabled after 3 consecutive failures" in disabled.stdout
    assert marker.read_text().splitlines() == ["run", "run", "run"]


def test_guard_reports_a_skipped_overlap_on_stdout_without_running_the_child(tmp_path):
    """An overlap is a deliberate non-run, so it must not pollute the job's .err file."""
    marker = tmp_path / "runs"
    (tmp_path / "guard").mkdir()
    (tmp_path / "guard" / ".example.lock").mkdir()  # a previous run still holds it

    result = run_guard(tmp_path, "sh", "-c", f"echo run >> {marker}")

    assert result.returncode == 0
    assert "already running; skipping" in result.stdout
    assert result.stderr == ""
    assert not marker.exists()


def test_guard_reset_allows_success_and_success_clears_streak(tmp_path):
    failing = run_guard(tmp_path, "sh", "-c", "exit 3")
    assert failing.returncode == 3

    reset = subprocess.run(
        ["sh", str(GUARD), "--job-name", "example", "--reset"],
        cwd=ROOT,
        env={"HOME": str(tmp_path), "TOOLHUB_JOB_GUARD_DIR": str(tmp_path / "guard")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert reset.returncode == 0

    success = run_guard(tmp_path, "sh", "-c", "exit 0")
    assert success.returncode == 0
    state = (tmp_path / "guard" / "example.state").read_text()
    assert "failure_streak=0" in state
    assert "disabled=0" in state
