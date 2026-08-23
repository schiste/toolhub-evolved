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

jobs.yaml is not the only place a job command is written. tools/deploy.sh
builds two of them itself and hands them to `toolforge jobs run`, which wraps
them identically -- a checked pod showed that wrapper at PID 1 with the real
process below it, hours after every command in jobs.yaml had been fixed. Both
sources are read here, because reading only the obvious one is how those two
were missed in the first place.
"""

import re
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "job_guard.sh"
JOBS = ROOT / "jobs.yaml"
SCRIPTS = sorted((ROOT / "tools").glob("*.sh"))
COMMAND = re.compile(r"^  command: (.*)$", re.M)
# `toolforge jobs run --command "..."` as a shell script writes it. The value is
# a double-quoted shell word, so it can hold $VAR but never a bare quote.
RUN_COMMAND = re.compile(r'--command "([^"]*)"')
# How the jobs framework composes a container command, read off a live CronJob:
#   /bin/sh -c -- 'exec 1>>NAME.out; exec 2>>NAME.err; <command from jobs.yaml>'
WRAPPER = "exec 1>>{out}; exec 2>>{err}; {command}"


def declared_commands() -> list[str]:
    """Every job command this repository defines, wherever it defines it."""
    commands = COMMAND.findall(JOBS.read_text())
    for script in SCRIPTS:
        commands.extend(RUN_COMMAND.findall(script.read_text()))
    return commands


def test_both_places_a_job_command_can_be_written_are_actually_read():
    """A parser that silently matched nothing would pass every test below it.

    The counts are lower bounds rather than exact numbers, so adding a job does
    not fail this, but reducing either source to no matches does.
    """
    from_jobs = COMMAND.findall(JOBS.read_text())
    from_scripts = [c for script in SCRIPTS for c in RUN_COMMAND.findall(script.read_text())]

    assert len(from_jobs) >= 20, f"jobs.yaml parser found only {len(from_jobs)} commands"
    assert len(from_scripts) >= 2, f"tools/*.sh parser found only {len(from_scripts)} commands"


def test_every_declared_command_execs_so_the_signal_is_not_swallowed():
    """Against the real files: one missing `exec` is one deaf job."""
    commands = declared_commands()

    assert commands, "no commands found; the parsers above are broken"
    missing = [c for c in commands if not c.startswith("exec ")]
    assert missing == [], f"these commands would run under a wrapper that drops the signal: {missing}"


def test_no_declared_command_uses_shell_syntax_that_exec_would_break():
    """`exec` takes one command, so a chain or redirect after it is a silent trap.

    A $VAR is fine -- it expands to a path before exec sees it -- but a `&&`, a
    pipe or a redirect needs the very shell that `exec` has just replaced.
    """
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
