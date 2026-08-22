# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests that the platform's stop signal can actually reach job_guard.sh.

The guard traps HUP/INT/TERM so a stopped run hands its lock back instead of
orphaning it for the whole --stale-after window. Those traps are worth nothing
if the signal never arrives, and on Toolforge it does not arrive by default:
the jobs framework runs each command inside a wrapper shell that owns PID 1,
Kubernetes signals only PID 1 at the timeout, and a trapless shell waiting on a
foreground child neither handles the signal nor passes it down. The guard is
then killed outright when the grace period expires, with no chance to run any
code -- which is exactly the case its traps were written for.

`exec` in front of the command is what closes that gap: the guard replaces the
wrapper rather than forking under it, so the guard is PID 1 and is signalled
directly.
"""

import re
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "job_guard.sh"
JOBS = ROOT / "jobs.yaml"
COMMAND = re.compile(r"^  command: (.*)$", re.M)
# How the jobs framework composes a container command, read off a live CronJob:
#   /bin/sh -c -- 'exec 1>>NAME.out; exec 2>>NAME.err; <command from jobs.yaml>'
WRAPPER = "exec 1>>{out}; exec 2>>{err}; {command}"


def declared_commands() -> list[str]:
    return COMMAND.findall(JOBS.read_text())


def test_every_declared_command_execs_so_the_signal_is_not_swallowed():
    """Against the real jobs.yaml: one missing `exec` is one deaf job."""
    commands = declared_commands()

    assert commands, "no commands found; the jobs.yaml parser above is broken"
    missing = [c for c in commands if not c.startswith("exec ")]
    assert missing == [], f"these commands would run under a wrapper that drops the signal: {missing}"


def test_no_declared_command_uses_shell_syntax_that_exec_would_break():
    """`exec` takes one command, so a chain or redirect after it is a silent trap."""
    unsafe = [c for c in declared_commands() if re.search(r"&&|\|\||[;|<>`]|\$\(", c)]

    assert unsafe == [], f"these need a shell and so cannot be exec'd as written: {unsafe}"


def _wrapped_run(tmp_path: Path, command: str) -> subprocess.Popen[bytes]:
    """Start the guard the way the platform does, wrapper shell and all."""
    script = WRAPPER.format(out=tmp_path / "job.out", err=tmp_path / "job.err", command=command)
    return subprocess.Popen(
        ["/bin/sh", "-c", "--", script],
        cwd=ROOT,
        env={"HOME": str(tmp_path), "TOOLHUB_JOB_GUARD_DIR": str(tmp_path / "guard")},
    )


def _wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_the_guard_releases_its_lock_when_only_the_wrapper_is_signalled(tmp_path):
    """Signal PID 1 and nothing else, as the platform does. The lock must go.

    Drop the `exec` and this fails: the wrapper dies, the guard is never told,
    and the lock outlives the run. That is the whole reason the prefix is
    mandatory rather than tidy.
    """
    lock = tmp_path / "guard" / ".example.lock"
    guarded = f"exec sh {GUARD} --job-name example --stale-after 99999 -- sleep 60"

    wrapper = _wrapped_run(tmp_path, guarded)
    assert _wait_for(lock.exists), "the guard never took its lock"
    wrapper.send_signal(signal.SIGTERM)
    wrapper.wait(timeout=10)

    # The platform SIGKILLs whatever is left once the grace period expires, so
    # a release that arrives later than this never happens in production.
    assert _wait_for(lambda: not lock.exists(), timeout=15.0), "the stopped run orphaned its lock"
