# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the scheduler circuit breaker wrapper."""

import os
import signal
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


def _running_guard(state_dir: Path, *command: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["sh", str(GUARD), "--job-name", "example", "--", *command],
        cwd=ROOT,
        env={"HOME": str(state_dir), "TOOLHUB_JOB_GUARD_DIR": str(state_dir / "guard")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _eventually(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_a_terminated_run_hands_its_lock_back_instead_of_orphaning_it(tmp_path):
    """The platform stops a job with a signal, which is when the lock must go.

    Left behind, it silences the job for the whole --stale-after window while
    every tick skips with a zero exit, so nothing is mailed and nothing runs.
    """
    lock = tmp_path / "guard" / ".example.lock"
    guard = _running_guard(tmp_path, "sh", "-c", "sleep 30")
    assert _eventually(lock.exists), "the guard never took its lock"

    guard.send_signal(signal.SIGTERM)
    guard.wait(timeout=10)

    assert not lock.exists()
    assert guard.returncode == 128 + signal.SIGTERM


def test_a_terminated_run_stops_its_child_before_releasing_the_lock(tmp_path):
    """Order matters: a released lock lets the next tick in immediately."""
    lock = tmp_path / "guard" / ".example.lock"
    marker = tmp_path / "child"
    child = f'trap "echo stopped >> {marker}; exit 0" TERM; echo started >> {marker}; sleep 30 & wait'
    guard = _running_guard(tmp_path, "sh", "-c", child)
    assert _eventually(lambda: marker.exists() and lock.exists()), "the child never started under the lock"

    guard.send_signal(signal.SIGTERM)
    guard.wait(timeout=10)

    assert marker.read_text().splitlines() == ["started", "stopped"]


def test_a_terminated_run_does_not_count_against_the_failure_breaker(tmp_path):
    """Being stopped is not the job failing, and three of them must not disable it."""
    lock = tmp_path / "guard" / ".example.lock"
    guard = _running_guard(tmp_path, "sh", "-c", "sleep 30")
    assert _eventually(lock.exists), "the guard never took its lock"

    guard.send_signal(signal.SIGTERM)
    guard.wait(timeout=10)

    assert not (tmp_path / "guard" / "example.state").exists()


def test_guard_swallows_a_lock_skip_without_recording_it_or_mailing(tmp_path):
    """backend.job_contract.EXIT_SKIPPED: the child took no lock, so it did nothing.

    Toolforge mails on any non-zero exit and job_runs publishes any recorded
    run, so a skip that reached either would be reported as a failure or as a
    success. It is neither, and the guard is where that is settled.
    """
    result = run_guard(tmp_path, "sh", "-c", "exit 75")

    assert result.returncode == 0, "a skip must not reach Toolforge, which mails on non-zero"
    assert result.stderr == "", "a deliberate non-run must not pollute the job's .err file"


def test_a_lock_skip_leaves_the_breaker_state_exactly_as_it_found_it(tmp_path):
    """A skip is no evidence that a failing job has recovered, so it must not clear the streak."""
    failing = ("sh", "-c", "exit 3")
    run_guard(tmp_path, *failing)
    run_guard(tmp_path, *failing)
    state = (tmp_path / "guard" / "example.state").read_text()
    assert "failure_streak=2" in state

    assert run_guard(tmp_path, "sh", "-c", "exit 75").returncode == 0

    after = (tmp_path / "guard" / "example.state").read_text()
    assert after == state, "the skip reset the breaker, so a broken job would never be disabled"
    # Proof that the streak survived: the next real failure is the third, not the first.
    assert run_guard(tmp_path, *failing).returncode == 3
    assert "disabled=1" in (tmp_path / "guard" / "example.state").read_text()


def test_a_lock_skip_releases_the_lock_it_took(tmp_path):
    """The guard's own lock is taken before the child runs, so a skip still has to hand it back."""
    assert run_guard(tmp_path, "sh", "-c", "exit 75").returncode == 0
    assert not (tmp_path / "guard" / ".example.lock").exists()


def test_guard_gives_the_child_somewhere_to_leave_its_summary(tmp_path):
    seen = tmp_path / "seen"
    result = run_guard(tmp_path, "sh", "-c", f'printf %s "$TOOLHUB_JOB_SUMMARY_FILE" > {seen}')

    assert result.returncode == 0
    assert seen.read_text().endswith("/example.summary.json")


def test_guard_clears_a_previous_summary_before_running_the_child(tmp_path):
    """A killed run leaves its file behind; the next run must not inherit it.

    Cleared before the child rather than matched by timestamp afterwards: the
    guard lock already means one run of this job at a time, so whatever is
    there when the child exits was written by that child.
    """
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    stale = guard_dir / "example.summary.json"
    stale.write_text('{"counts": {"done": 99}}')

    result = run_guard(tmp_path, "sh", "-c", "exit 0")

    assert result.returncode == 0
    assert not stale.exists()


def test_no_breaker_keeps_running_an_alarm_that_stays_failing(tmp_path):
    """An alarm exits non-zero while something else is broken; muting it hides the fault.

    digest-audit tripped the breaker on 2026-08-30 over a genuinely missing daily
    edition and went quiet for a day, which is the failure job-watchdog avoids by
    not being wrapped at all. --no-breaker keeps the wrapper without that.
    """
    marker = tmp_path / "runs"
    failing = ("--no-breaker", "--", "sh", "-c", f"echo run >> {marker}; exit 7")

    for _ in range(6):
        result = run_guard_with(tmp_path, *failing)
        assert result.returncode == 7
        assert "disabled" not in result.stdout

    assert marker.read_text().splitlines() == ["run"] * 6


def test_no_breaker_leaves_every_other_guarantee_of_the_guard_in_place(tmp_path):
    """Only the breaker switches off: the lock and the summary file still apply."""
    _held_lock(tmp_path, age_seconds=60)
    overlapping = run_guard_with(tmp_path, "--no-breaker", "--", "sh", "-c", "exit 7")
    assert overlapping.returncode == 0
    assert "already running; skipping" in overlapping.stdout

    (tmp_path / "guard" / ".example.lock").rmdir()
    summary = run_guard_with(
        tmp_path, "--no-breaker", "--", "sh", "-c", 'printf %s "$TOOLHUB_JOB_SUMMARY_FILE"'
    )
    assert summary.stdout.endswith("example.summary.json")


def test_a_breaker_already_tripped_is_ignored_once_no_breaker_is_set(tmp_path):
    """Recovery must not need a hand-run --reset after the flag is added."""
    for _ in range(3):
        assert run_guard_with(tmp_path, "--", "sh", "-c", "exit 7").returncode == 7
    assert run_guard_with(tmp_path, "--", "sh", "-c", "exit 7").returncode == 0

    marker = tmp_path / "runs"
    result = run_guard_with(tmp_path, "--no-breaker", "--", "sh", "-c", f"echo run >> {marker}; exit 7")

    assert result.returncode == 7
    assert marker.read_text().splitlines() == ["run"]
