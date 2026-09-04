# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker status is judged against each job's own schedule, not a global one."""

import re
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


def _run(session, job_name, *, minutes_ago, succeeded=True, exit_code=0, duration=3, summary=None):
    started = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    session.add(
        JobRun(
            job_name=job_name,
            started_at=started,
            finished_at=started + timedelta(seconds=duration),
            duration_seconds=duration,
            exit_code=exit_code,
            succeeded=succeeded,
            summary=summary,
        )
    )


def _worker(payload, name):
    return next(row for row in payload["workers"] if row["name"] == name)


def test_the_real_jobs_file_parses_with_a_cadence_for_every_job():
    jobs = job_catalog.load()
    # The reader covers this file's shape exactly; a structural change to
    # jobs.yaml must fail here rather than silently emptying the page.
    assert len(jobs) >= 15
    # A job declares either a cron line or continuous: true, never neither and
    # never both. Both would leave the page describing a cadence the platform
    # is not honouring; neither leaves it with no period to judge silence by.
    assert all(bool(job.schedule) != job.continuous for job in jobs)
    assert all(job.description for job in jobs)
    assert all(job.expected_interval_minutes > 0 for job in jobs)
    assert {"crawler", "people-reconcile", "people-reconcile-incremental"} <= {job.name for job in jobs}


def test_a_continuous_job_is_judged_against_its_heartbeat():
    """It has no cron line, so silence has to be measured against something."""
    scanner = next(job for job in job_catalog.load() if job.name == "repository-analysis")

    assert scanner.continuous is True
    assert scanner.schedule == ""
    assert scanner.expected_interval_minutes == job_catalog.CONTINUOUS_HEARTBEAT_MINUTES


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
        ("17 3 1,15 * *", 24480),
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


def test_every_status_the_page_can_show_is_explained():
    """A named state with no definition is the one an operator most needs explained.

    The statuses are derived from the module rather than listed here, so adding
    a sixth state to _status() fails until the page can explain it too.
    """
    statuses = {value for name, value in vars(workers).items() if name.startswith("STATUS_")}
    with db.session_scope() as session:
        payload = workers.snapshot(session)
    assert statuses <= set(payload["definitions"])
    # "recorded" explains what counts as a run at all; it is the only entry
    # that is not itself a status.
    assert payload["definitions"].keys() - statuses == {"recorded"}


def test_the_endpoint_is_public_and_counts_every_declared_worker():
    app = Flask(__name__)
    backend.register(app, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
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


# Scheduler jitter observed on the reclaim lines in people-identity-reconcile.err
# is about +/- 13s around the interval. 120s is an order of magnitude above that.
RECLAIM_MARGIN_SECONDS = 120
# Below this, a run that skips the boundary is retried soon enough that the extra
# silence is not worth designing against: the whole cost of a miss is one interval.
# Lowered from 600 when the window stopped being per-job: one number now has to
# clear every schedule at once, and the five-minute one is where a round value
# lands first -- 300 would have sat exactly on digest-deliver's period.
RECLAIM_CHECKED_ABOVE_SECONDS = 300


def _guarded_stale_after() -> dict[str, int]:
    """--stale-after per job name, read from the commands jobs.yaml declares.

    Expected to be empty now that liveness is measured rather than derived; see
    `test_no_job_derives_its_reclaim_window_from_its_own_timeout`.
    """
    declared = {}
    for line in (ROOT / "jobs.yaml").read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("command:") or "--job-name" not in stripped:
            continue
        name = re.search(r"--job-name (\S+)", stripped)
        stale = re.search(r"--stale-after (\d+)", stripped)
        if name and stale:
            declared[name.group(1)] = int(stale.group(1))
    return declared


def _guard_default(name: str) -> int:
    """One of the guard's own default assignments, e.g. STALE_AFTER=300."""
    text = (ROOT / "tools" / "job_guard.sh").read_text()
    match = re.search(rf"^{name}=\"?\$?\{{?[A-Z_]*:?-?(\d+)", text, re.MULTILINE)
    assert match, f"{name} default not found in job_guard.sh"
    return int(match.group(1))


def test_no_reclaim_threshold_lands_on_the_schedule_it_will_be_measured_against():
    """A lock is only ever inspected by a run, so its age is a multiple of the period.

    The guard reclaims at `age >= stale-after`, and a leaked lock is first seen
    by the next run at `ceil(stale / period) * period`. When stale-after is
    itself a multiple of the period those two coincide, and jitter alone decides
    whether the run reclaims or skips. people-identity-reconcile shipped exactly
    that way for one release: stale-after 3600 on an hourly schedule, where the
    24 recorded reclaims ranged 3588-3613s -- 10 of them below the threshold
    they were being compared against, each costing another silent hour.

    One number is graded now rather than one per job, because the window no
    longer depends on the job -- see the next test.
    """
    declared = _guard_default("STALE_AFTER")
    checked = []
    too_close = []
    for job in job_catalog.load():
        period = job.expected_interval_minutes * 60
        if job.continuous or period < RECLAIM_CHECKED_ABOVE_SECONDS:
            continue
        checked.append(job.name)
        first_look = -(-declared // period) * period
        if first_look - declared < RECLAIM_MARGIN_SECONDS:
            too_close.append(f"{job.name}: stale-after={declared} first inspected at {first_look}s (period {period})")
    # A filter that excluded everything would make the assertion below vacuous.
    assert len(checked) >= 10, f"only {len(checked)} jobs were actually checked"
    assert too_close == [], too_close


def test_no_job_derives_its_reclaim_window_from_its_own_timeout():
    """The window says how long a job stays silent, not whether a run could live.

    Twice the timeout answered "could this still be running", which age alone
    cannot do better. It got the other question wrong: the threshold has to be
    crossed *and then noticed by a run*, so a job scheduled tighter than its own
    threshold loses every tick in between -- measured on 2026-09-04 as 1 lost run
    for inference-enrichment, 10 for people-reconcile-incremental and 60 for
    api-cache-invalidator. The guard heartbeats its lock instead, so one short
    window is correct for every job however long it runs, and a per-job override
    would only reintroduce the coupling.
    """
    assert _guarded_stale_after() == {}, "jobs.yaml is deriving a reclaim window again"


def test_the_reclaim_window_leaves_room_for_several_missed_heartbeats():
    """A single missed touch must not hand a live run's lock away.

    The locks live on NFS, where an attribute cache can hide a fresh mtime for
    tens of seconds, so the margin has to absorb more than one interval.
    """
    stale = _guard_default("STALE_AFTER")
    heartbeat = _guard_default("HEARTBEAT_SECONDS")
    assert heartbeat > 0
    assert stale >= heartbeat * 5, f"stale-after {stale} allows only {stale // heartbeat} missed heartbeats"


def test_a_worker_page_carries_what_each_run_said_it_did():
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=30, summary={"counts": {"fetched": 12}})
        _run(session, "crawler", minutes_ago=5, summary={"counts": {"fetched": 40}})
        session.flush()
        payload = workers.detail(session, "crawler")

    assert payload["worker"]["name"] == "crawler"
    # Newest first, so the run being asked about is the one at the top.
    assert [run["summary"]["counts"]["fetched"] for run in payload["runs"]] == [40, 12]
    assert all(run["finishedAt"] for run in payload["runs"])


def test_a_run_that_never_said_what_it_did_is_null_rather_than_empty():
    """A killed run and a run that did nothing are different facts.

    Every row recorded before jobs handed their summaries over has none, and
    reporting those as {} would put them on a coverage chart at zero.
    """
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=5)
        session.flush()
        payload = workers.detail(session, "crawler")

    assert payload["runs"][0]["summary"] is None


def test_the_worker_page_and_the_list_agree_about_status():
    """The page opened to explain a red row must not compute red differently."""
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=5, succeeded=False, exit_code=1)
        session.flush()
        listed = _worker(workers.snapshot(session), "crawler")
        page = workers.detail(session, "crawler")["worker"]

    assert page["status"] == listed["status"] == workers.STATUS_FAILING
    assert {key: page[key] for key in page} == {key: listed[key] for key in page}


def test_a_worker_with_no_runs_still_has_a_page():
    """Absence is the state most worth looking at; it must not be a dead link."""
    with db.session_scope() as session:
        payload = workers.detail(session, "crawler")

    assert payload["runs"] == []
    assert payload["worker"]["status"] == workers.STATUS_UNKNOWN


def test_a_name_that_is_not_a_declared_worker_has_no_page():
    with db.session_scope() as session:
        assert workers.detail(session, "not-a-job") is None


def test_the_worker_endpoint_answers_by_name_and_404s_for_anything_else():
    app = Flask(__name__)
    backend.register(app, db_url="sqlite://", secret_key="test-secret", trusted_hosts=backend.LOCAL_TRUSTED_HOSTS + backend.DEFAULT_TRUSTED_HOSTS)
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with db.session_scope() as session:
        _run(session, "crawler", minutes_ago=5, summary={"counts": {"fetched": 3}})

    client = app.test_client()
    found = client.get("/v1/workers/crawler/")
    assert found.status_code == 200
    assert found.headers["Cache-Control"].startswith("public")
    assert found.get_json()["runs"][0]["summary"] == {"counts": {"fetched": 3}}

    assert client.get("/v1/workers/not-a-job/").status_code == 404


def test_the_recorder_attaches_the_summary_the_child_left_behind(tmp_path):
    database = f"sqlite:///{tmp_path / 'runs.sqlite'}"
    db.configure(database)
    db.init_schema()
    handoff = tmp_path / "crawler.summary.json"
    handoff.write_text('{"counts": {"fetched": 9}}', encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "--job-name",
            "crawler",
            "--started",
            "1700000000",
            "--finished",
            "1700000004",
            "--exit-code",
            "0",
            "--summary-file",
            str(handoff),
        ],
        check=True,
        capture_output=True,
        env={"TOOLHUB_DB_URL": database, "PATH": "/usr/bin:/bin"},
    )
    db.configure(database)
    with db.session_scope() as session:
        row = session.query(JobRun).filter(JobRun.job_name == "crawler").one()
    assert row.summary == {"counts": {"fetched": 9}}


@pytest.mark.parametrize(
    ("label", "written"),
    [
        ("truncated by a kill mid-write", '{"counts": {"fetch'),
        ("not an object", "[1, 2, 3]"),
        ("empty", ""),
    ],
)
def test_an_unusable_summary_still_records_the_run(tmp_path, label, written):
    """Losing the row is the one outcome worse than losing the summary.

    A run that died badly is exactly the run worth seeing on the page, and it
    is also the run most likely to have left half a line behind.
    """
    database = f"sqlite:///{tmp_path / 'runs.sqlite'}"
    db.configure(database)
    db.init_schema()
    handoff = tmp_path / "crawler.summary.json"
    handoff.write_text(written, encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "--job-name",
            "crawler",
            "--started",
            "1700000000",
            "--finished",
            "1700000004",
            "--exit-code",
            "0",
            "--summary-file",
            str(handoff),
        ],
        check=True,
        capture_output=True,
        env={"TOOLHUB_DB_URL": database, "PATH": "/usr/bin:/bin"},
    )
    db.configure(database)
    with db.session_scope() as session:
        row = session.query(JobRun).filter(JobRun.job_name == "crawler").one()
    assert row.summary is None, label
