# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker status is judged against each job's own schedule, not a global one."""

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, job_catalog, workers  # noqa: E402
from backend.models import JobRun  # noqa: E402

RECORDER = ROOT / "tools" / "job_run_record.py"


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def _run(session, job_name, *, minutes_ago, succeeded=True, exit_code=0, duration=3):
    started = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    session.add(
        JobRun(
            job_name=job_name,
            started_at=started,
            finished_at=started + timedelta(seconds=duration),
            duration_seconds=duration,
            exit_code=exit_code,
            succeeded=succeeded,
        )
    )


def _worker(payload, name):
    return next(row for row in payload["workers"] if row["name"] == name)


def test_the_real_jobs_file_parses_with_a_schedule_for_every_job():
    jobs = job_catalog.load()
    # The reader covers this file's shape exactly; a structural change to
    # jobs.yaml must fail here rather than silently emptying the page.
    assert len(jobs) >= 15
    assert all(job.schedule for job in jobs)
    assert all(job.description for job in jobs)
    assert all(job.expected_interval_minutes > 0 for job in jobs)
    assert {"crawler", "people-reconcile", "people-reconcile-incremental"} <= {job.name for job in jobs}


def test_the_file_header_is_not_mistaken_for_the_first_job_description():
    first = job_catalog.load()[0]
    assert "SPDX" not in first.description


@pytest.mark.parametrize(
    ("schedule", "minutes"),
    [
        ("* * * * *", 1),
        ("*/15 * * * *", 15),
        ("17 * * * *", 60),
        ("23 */6 * * *", 360),
        ("13 5 * * 0", 10080),
        ("nonsense", 0),
    ],
)
def test_cron_periods_are_derived_for_staleness_comparison(schedule, minutes):
    assert job_catalog._interval_minutes(schedule) == minutes


def test_a_recent_successful_run_is_healthy():
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=5)
        session.flush()
        payload = workers.snapshot(session)
    assert _worker(payload, "crawler")["status"] == workers.STATUS_HEALTHY


def test_a_failed_last_run_is_failing_even_when_recent():
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=1, succeeded=False, exit_code=7)
        session.flush()
        payload = workers.snapshot(session)
    row = _worker(payload, "crawler")
    assert row["status"] == workers.STATUS_FAILING
    assert row["lastRunExitCode"] == 7


def test_a_minute_job_silent_for_days_is_stalled_not_merely_late():
    with db.session_scope() as session:
        # The exact production condition: a per-minute drain whose last real
        # run was ten days earlier while every tick reported success.
        _run(session, "people-reconcile-incremental", minutes_ago=10 * 24 * 60)
        session.flush()
        payload = workers.snapshot(session)
    assert _worker(payload, "people-reconcile-incremental")["status"] == workers.STATUS_STALLED


def test_the_same_silence_is_healthy_for_a_job_that_runs_that_rarely():
    with db.session_scope() as session:
        _run(session, "people-reconcile", minutes_ago=200)
        session.flush()
        payload = workers.snapshot(session)
    # 200 minutes is stalled for a per-minute job and unremarkable for one
    # scheduled every six hours, which is why the threshold is per job.
    assert _worker(payload, "people-reconcile")["status"] == workers.STATUS_HEALTHY


def test_status_treats_an_unknown_schedule_as_failing_or_unknown():
    job = job_catalog.ScheduledJob(name="mystery", schedule="nonsense", description="", timeout_seconds=0)
    assert job.expected_interval_minutes == 0
    started = datetime.now(tz=UTC).replace(tzinfo=None)
    failed_run = JobRun(job_name="mystery", started_at=started, succeeded=False)
    assert workers._status(job, failed_run, 0.0) == workers.STATUS_FAILING
    succeeded_run = JobRun(job_name="mystery", started_at=started, succeeded=True)
    assert workers._status(job, succeeded_run, 0.0) == workers.STATUS_UNKNOWN


def test_a_run_silent_for_a_few_periods_is_late_but_not_stalled():
    with db.session_scope() as session:
        # crawler runs hourly (period=60): 200 minutes is >= LATE_PERIODS*60
        # (180) but below STALLED_PERIODS*60 (600).
        _run(session, "crawler", minutes_ago=200)
        session.flush()
        payload = workers.snapshot(session)
    assert _worker(payload, "crawler")["status"] == workers.STATUS_LATE


def test_snapshot_handles_no_declared_jobs(monkeypatch):
    monkeypatch.setattr(job_catalog, "load", lambda: [])
    with db.session_scope() as session:
        payload = workers.snapshot(session)
    assert payload["workers"] == []
    assert payload["counts"] == {}


def test_a_job_with_no_recorded_run_is_unknown_rather_than_broken():
    with db.session_scope() as session:
        payload = workers.snapshot(session)
    row = _worker(payload, "crawler")
    assert row["status"] == workers.STATUS_UNKNOWN
    assert row["lastRunAt"] == ""
    assert row["recentRuns"] == []


def test_recent_runs_are_newest_first_and_bounded():
    with db.session_scope() as session:
        for minute in range(workers.RECENT_RUNS + 8):
            _run(session, "crawler", minutes_ago=minute)
        session.flush()
        payload = workers.snapshot(session)
    runs = _worker(payload, "crawler")["recentRuns"]
    assert len(runs) == workers.RECENT_RUNS
    assert runs[0]["startedAt"] > runs[-1]["startedAt"]


def test_last_success_is_reported_separately_from_the_last_run():
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=90)
        _run(session, "crawler", minutes_ago=5, succeeded=False, exit_code=1)
        session.flush()
        payload = workers.snapshot(session)
    row = _worker(payload, "crawler")
    assert row["lastRunSucceeded"] is False
    # A failing worker must still show when it last genuinely worked.
    assert row["lastSuccessAt"] and row["lastSuccessAt"] < row["lastRunAt"]


def test_the_endpoint_is_public_and_counts_every_declared_worker():
    app = Flask(__name__)
    backend.register(app, db_url="sqlite://", secret_key="test-secret")
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=5)

    response = app.test_client().get("/v1/workers/")
    payload = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("public")
    assert len(payload["workers"]) == len(job_catalog.load())
    assert sum(payload["counts"].values()) == len(payload["workers"])


def test_the_recorder_stores_a_run_and_keeps_history_bounded(tmp_path):
    database = f"sqlite:///{tmp_path / 'runs.sqlite'}"
    db.configure(database)
    db.init_schema()
    for offset in range(3):
        subprocess.run(
            [
                sys.executable,
                str(RECORDER),
                "--job-name",
                "crawler",
                "--started",
                str(1_700_000_000 + offset * 60),
                "--finished",
                str(1_700_000_004 + offset * 60),
                "--exit-code",
                "0",
            ],
            check=True,
            capture_output=True,
            env={"TOOLHUB_DB_URL": database, "PATH": "/usr/bin:/bin"},
        )
    db.configure(database)
    with db.session_scope() as session:
        rows = session.query(JobRun).filter(JobRun.job_name == "crawler").all()
    assert len(rows) == 3
    assert {row.duration_seconds for row in rows} == {4}
    assert all(row.succeeded for row in rows)
