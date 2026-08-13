# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the scheduler circuit breaker wrapper."""

import os
import subprocess
import time
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


def run_guard_with(state_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(GUARD), "--job-name", "example", *args],
        cwd=ROOT,
        env={"HOME": str(state_dir), "TOOLHUB_JOB_GUARD_DIR": str(state_dir / "guard")},
        capture_output=True,
        text=True,
        check=False,
    )


def _held_lock(tmp_path: Path, age_seconds: int) -> Path:
    """Leave a lock behind as a killed run does: present, with no owner."""
    lock = tmp_path / "guard" / ".example.lock"
    lock.mkdir(parents=True)
    stamp = time.time() - age_seconds
    os.utime(lock, (stamp, stamp))
    return lock


def test_a_lock_older_than_any_legitimate_run_is_reclaimed(tmp_path):
    marker = tmp_path / "runs"
    _held_lock(tmp_path, age_seconds=7200)

    result = run_guard_with(tmp_path, "--stale-after", "3600", "--", "sh", "-c", f"echo run >> {marker}")

    assert result.returncode == 0
    assert "reclaiming example lock abandoned" in result.stderr
    assert marker.read_text().splitlines() == ["run"]


def test_a_recent_lock_is_still_treated_as_a_live_overlap(tmp_path):
    marker = tmp_path / "runs"
    _held_lock(tmp_path, age_seconds=60)

    result = run_guard_with(tmp_path, "--stale-after", "3600", "--", "sh", "-c", f"echo run >> {marker}")

    assert result.returncode == 0
    assert "already running; skipping" in result.stdout
    assert not marker.exists()


def test_reclaiming_can_be_disabled_with_a_zero_threshold(tmp_path):
    marker = tmp_path / "runs"
    _held_lock(tmp_path, age_seconds=999999)

    result = run_guard_with(tmp_path, "--stale-after", "0", "--", "sh", "-c", f"echo run >> {marker}")

    assert "already running; skipping" in result.stdout
    assert not marker.exists()


def test_a_reclaimed_lock_is_released_again_on_a_normal_exit(tmp_path):
    lock = _held_lock(tmp_path, age_seconds=7200)

    run_guard_with(tmp_path, "--stale-after", "3600", "--", "true")

    assert not lock.exists()


def test_a_non_numeric_stale_threshold_is_rejected(tmp_path):
    result = run_guard_with(tmp_path, "--stale-after", "soon", "--", "true")
    assert result.returncode == 2
    assert "stale-after must be a non-negative integer" in result.stderr


def _tripped(tmp_path: Path, *, last_failure_age: int) -> None:
    """Leave the breaker tripped, as three consecutive failures would."""
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    (guard_dir / "example.state").write_text(
        "failure_streak=3\ndisabled=1\nlast_exit=7\n"
        f"last_failure_at={int(time.time()) - last_failure_age}\n"
    )


def test_a_tripped_breaker_retries_once_after_its_cooldown(tmp_path):
    marker = tmp_path / "runs"
    _tripped(tmp_path, last_failure_age=7200)

    result = run_guard_with(tmp_path, "--retry-after", "3600", "--", "sh", "-c", f"echo run >> {marker}")

    assert "one trial run" in result.stderr
    assert marker.read_text().splitlines() == ["run"]


def test_a_successful_trial_run_clears_the_breaker(tmp_path):
    _tripped(tmp_path, last_failure_age=7200)

    run_guard_with(tmp_path, "--retry-after", "3600", "--", "true")
    state = (tmp_path / "guard" / "example.state").read_text()

    assert "failure_streak=0" in state
    assert "disabled=0" in state


def test_a_failed_trial_run_rearms_the_cooldown_instead_of_retrying_every_tick(tmp_path):
    marker = tmp_path / "runs"
    _tripped(tmp_path, last_failure_age=7200)

    first = run_guard_with(tmp_path, "--retry-after", "3600", "--", "sh", "-c", f"echo run >> {marker}; exit 7")
    second = run_guard_with(tmp_path, "--retry-after", "3600", "--", "sh", "-c", f"echo run >> {marker}; exit 7")

    assert first.returncode == 7
    assert "is disabled after" in second.stdout
    # The failure reset the clock, so the very next tick does not retry.
    assert marker.read_text().splitlines() == ["run"]


def test_a_tripped_breaker_stays_shut_before_the_cooldown_elapses(tmp_path):
    marker = tmp_path / "runs"
    _tripped(tmp_path, last_failure_age=60)

    result = run_guard_with(tmp_path, "--retry-after", "3600", "--", "sh", "-c", f"echo run >> {marker}")

    assert "is disabled after" in result.stdout
    assert not marker.exists()


def test_retrying_can_be_disabled_with_a_zero_cooldown(tmp_path):
    marker = tmp_path / "runs"
    _tripped(tmp_path, last_failure_age=999999)

    result = run_guard_with(tmp_path, "--retry-after", "0", "--", "sh", "-c", f"echo run >> {marker}")

    assert "is disabled after" in result.stdout
    assert not marker.exists()
