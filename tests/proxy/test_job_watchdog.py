# SPDX-License-Identifier: GPL-3.0-or-later
"""The watchdog turns a worker's silence into the one signal Toolforge mails."""

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import job_watchdog as job  # noqa: E402
from backend import db, job_watchdog as watchdog, workers  # noqa: E402
from backend.models import JobRun  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")
    db.configure("sqlite://")
    db.init_schema()


def _run(session, job_name, *, minutes_ago, succeeded=True, exit_code=0):
    started = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    session.add(
        JobRun(
            job_name=job_name,
            started_at=started,
            finished_at=started + timedelta(seconds=3),
            duration_seconds=3,
            exit_code=exit_code,
            succeeded=succeeded,
        )
    )


def _check_with(*runs):
    with db.session_scope() as session:
        for kwargs in runs:
            _run(session, **kwargs)
        session.flush()
        return watchdog.check(session)


def test_a_recently_successful_worker_raises_nothing():
    report = _check_with({"job_name": "crawler", "minutes_ago": 5})
    assert "crawler" not in {entry["name"] for entry in report["alarming"]}


def test_a_worker_silent_for_ten_periods_is_alarming():
    # The condition that went unnoticed three times: every tick killed, so
    # nothing was ever recorded and no exit code ever reached anyone.
    report = _check_with({"job_name": "crawler", "minutes_ago": 10 * 24 * 60})
    assert "crawler" in report["stalled"]
    assert "crawler" in {entry["name"] for entry in report["alarming"]}


def test_a_failed_last_run_is_alarming():
    report = _check_with({"job_name": "crawler", "minutes_ago": 1, "succeeded": False, "exit_code": 7})
    assert "crawler" in report["failing"]


def test_a_worker_merely_running_behind_is_alarming_too():
    """`late` is in the alarm set by choice, so a slip is reported, not filtered."""
    hourly = next(job for job in _catalog() if job.expected_interval_minutes == 60 and not job.continuous)
    report = _check_with({"job_name": hourly.name, "minutes_ago": 60 * workers.LATE_PERIODS + 5})
    assert hourly.name in report["late"]


def _catalog():
    from backend import job_catalog

    return job_catalog.load()


def test_a_worker_that_never_ran_is_named_but_never_alarms():
    """The deliberate hole, pinned so it cannot close by accident.

    `unknown` reads the same for a job deployed a minute ago, one on a restored
    database, and one broken since birth. Alarming on it would mail about every
    declared job at once after a restore, so it is reported and nothing more.
    """
    report = _check_with({"job_name": "crawler", "minutes_ago": 5})
    assert report["neverRan"], "a fresh database should leave most jobs never-run"
    assert "crawler" not in report["neverRan"]
    never_ran = set(report["neverRan"])
    alarming = {entry["name"] for entry in report["alarming"]}
    assert never_ran & alarming == set()


def test_the_summary_carries_enough_to_act_without_opening_the_page():
    report = _check_with({"job_name": "crawler", "minutes_ago": 10 * 24 * 60})
    entry = next(item for item in report["alarming"] if item["name"] == "crawler")
    assert entry["lastRunAt"]
    assert entry["expectedIntervalMinutes"] > 0
    assert entry["minutesSinceLastRun"] >= 10 * 24 * 60


def test_a_quiet_fleet_exits_zero_and_a_stalled_one_does_not(monkeypatch, capsys):
    """The exit code is the whole alarm: Toolforge mails on that and nothing else."""
    monkeypatch.setattr(watchdog, "check", lambda _session: {"checked": 3, "alarming": [], "neverRan": []})
    assert job.main() == 0
    quiet = capsys.readouterr()
    assert quiet.err == "", "a healthy fleet must not cry wolf"
    assert json.loads(quiet.out.strip().removeprefix("job-watchdog: "))["checked"] == 3

    monkeypatch.setattr(
        watchdog,
        "check",
        lambda _session: {"checked": 3, "alarming": [{"name": "crawler", "status": "stalled"}], "neverRan": []},
    )
    assert job.main() != 0
    captured = capsys.readouterr()
    assert "crawler" in captured.err
    printed = json.loads(captured.out.strip().removeprefix("job-watchdog: "))
    assert printed["checked"] == 3


def test_the_watchdog_records_its_own_run(monkeypatch):
    monkeypatch.setattr(watchdog, "check", lambda _session: {"checked": 1, "alarming": [], "neverRan": []})
    job.main()
    with db.session_scope() as session:
        assert session.query(JobRun).filter(JobRun.job_name == job.JOB_NAME).count() == 1


def test_its_own_run_is_recorded_as_healthy_even_while_it_is_alarming(monkeypatch):
    """The verdict is about other jobs; recording it here would hide this one's death."""
    monkeypatch.setattr(
        watchdog,
        "check",
        lambda _session: {"checked": 1, "alarming": [{"name": "crawler", "status": "stalled"}], "neverRan": []},
    )
    assert job.main() != 0
    with db.session_scope() as session:
        recorded = session.query(JobRun).filter(JobRun.job_name == job.JOB_NAME).one()
    assert recorded.succeeded is True


def test_a_recorder_failure_does_not_swallow_the_alarm(monkeypatch, capsys):
    """Observability must never turn a real alarm into a silent success."""
    monkeypatch.setattr(
        watchdog,
        "check",
        lambda _session: {"checked": 1, "alarming": [{"name": "crawler", "status": "stalled"}], "neverRan": []},
    )
    monkeypatch.setattr(job.job_runs, "record", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert job.main() != 0
    assert "could not record run" in capsys.readouterr().err


def test_the_watchdog_is_not_wrapped_in_the_circuit_breaker():
    """A watchdog behind a breaker is not a watchdog.

    job_guard.sh disables a job after three consecutive non-zero exits, and
    this job exits non-zero exactly when something else is wrong. Wrapping it
    would let any stall lasting three ticks silence its own alarm -- the same
    way the crawler's breaker retired it for ten days in 2026-08.
    """
    block = _jobs_yaml_block("job-watchdog")
    command = next(line for line in block if line.strip().startswith("command:"))
    assert "job_guard.sh" not in command, "the watchdog must not run under the circuit breaker"
    assert "emails: onfailure" in "\n".join(block), "without this the non-zero exit reaches nobody"


def _jobs_yaml_block(name):
    lines = (ROOT / "jobs.yaml").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.fullmatch(rf"- name:\s+{re.escape(name)}", line.strip()))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip().startswith("- name:"):
            break
        block.append(line)
    return block


def test_the_watchdog_is_declared_and_therefore_watches_itself():
    """It appears in its own catalogue, so its own silence is at least visible."""
    assert job.JOB_NAME in {declared.name for declared in _catalog()}
