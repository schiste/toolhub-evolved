# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared job scaffold keeps every entrypoint's conventions identical."""

import contextlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from sqlalchemy.exc import DBAPIError  # noqa: E402

from backend import (  # noqa: E402
    DEFAULT_DB_URL,
    db,
    job_catalog,
    job_contract,
    job_runner,
    wikimedia_user_reconciliation,
)


@pytest.fixture(autouse=True)
def sqlite_db(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite://")


def test_a_set_but_empty_database_url_falls_back_instead_of_reaching_sqlalchemy(monkeypatch):
    # os.getenv(name, DEFAULT) would return "" here, and db.configure("") raises
    # ArgumentError. Three entrypoints used that spelling before this helper.
    monkeypatch.setenv("TOOLHUB_DB_URL", "")
    assert job_runner.database_url() == DEFAULT_DB_URL


def test_the_configured_url_is_used_when_present(monkeypatch):
    monkeypatch.setenv("TOOLHUB_DB_URL", "sqlite:///example.sqlite3")
    assert job_runner.database_url() == "sqlite:///example.sqlite3"


def test_a_mapping_summary_is_printed_under_the_job_name(capsys):
    code = job_runner.run_job("example-job", lambda: {"b": 2, "a": 1})
    out = capsys.readouterr().out.strip()
    assert code == job_contract.EXIT_OK
    assert out.startswith("example-job: ")
    # Sorted keys keep the line stable enough to diff between runs.
    assert json.loads(out.removeprefix("example-job: ")) == {"a": 1, "b": 2}


def test_a_body_that_printed_its_own_line_gets_no_second_summary(capsys):
    def body() -> None:
        sys.stdout.write("example-job: 3 things done\n")

    job_runner.run_job("example-job", body)
    assert capsys.readouterr().out == "example-job: 3 things done\n"


def test_losing_the_lock_is_a_successful_no_op(capsys, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def busy(_name, **_kwargs):
        yield False

    monkeypatch.setattr(db, "advisory_lock", busy)
    ran = []
    code = job_runner.run_job("example-job", lambda: ran.append(1), lock=True)

    # Losing a race with the run already doing the work is not a failure, and
    # must not count toward the guard's breaker -- but it is not a success
    # either, and reporting it as one published a run that never happened.
    assert code == job_contract.EXIT_SKIPPED
    assert ran == []
    assert json.loads(capsys.readouterr().out) == {"locked": True, "heldBy": None}


def test_the_lock_name_keeps_the_shared_prefix(monkeypatch):
    seen = []
    from contextlib import contextmanager

    @contextmanager
    def record(name, **_kwargs):
        seen.append(name)
        yield True

    monkeypatch.setattr(db, "advisory_lock", record)
    job_runner.run_job("people-reconcile", lambda: None, lock=True)
    assert seen == ["toolhub-evolved:people-reconcile"]


def test_the_lock_is_taken_without_waiting_unless_a_wait_is_asked_for(monkeypatch):
    seen = []
    from contextlib import contextmanager

    @contextmanager
    def record(name, **kwargs):
        seen.append((name, kwargs.get("timeout_seconds")))
        yield True

    monkeypatch.setattr(db, "advisory_lock", record)
    monkeypatch.setattr(db, "advisory_lock_holder", lambda _name: None)
    job_runner.run_job("example-job", lambda: None, lock=True)
    job_runner.run_job("example-job", lambda: None, lock=True, lock_wait_seconds=120)

    lock = f"{job_runner.LOCK_PREFIX}example-job"
    intent = f"{lock}{job_runner.INTENT_SUFFIX}"
    # Skipping on contact stays the default: the callers that run every minute
    # have another attempt immediately and must not queue behind a long pass.
    # A job that will not wait also never announces a wait -- it has nothing to
    # reserve -- so only the second run takes the intent lock, and it takes it
    # first, before it can be turned away from the lock it actually wants.
    assert seen == [(lock, 0), (intent, 120), (lock, 120)]


def test_a_job_that_will_not_wait_stands_aside_for_one_that_has_been_waiting(monkeypatch, capsys):
    """The starvation, in one test.

    GET_LOCK hands the lock to whoever asks at the instant it frees, so the job
    asking every minute takes it back before the job that has been queueing
    since :43 is handed anything -- eight hours of that on 2026-08-29, each hour
    reported as a run. Being unwilling to wait is affordable exactly because
    another attempt is sixty seconds away, which is also what makes stepping
    aside cost nothing.
    """
    from contextlib import contextmanager

    taken = []

    @contextmanager
    def record(name, **_kwargs):
        taken.append(name)
        yield True

    monkeypatch.setattr(db, "advisory_lock", record)
    monkeypatch.setattr(db, "advisory_lock_holder", lambda _name: 4172)

    code = job_runner.run_job("example-job", lambda: None, lock=True)

    assert code == job_contract.EXIT_SKIPPED
    assert json.loads(capsys.readouterr().out) == {"locked": True, "yieldedTo": 4172}
    # Yielded before touching the lock. Checking after losing it would be too
    # late and checking after winning it would be the starvation itself: the
    # lock being free at this instant is not evidence that nobody is owed it.
    assert taken == []


def test_a_waiter_that_loses_to_an_earlier_waiter_says_so(monkeypatch, capsys):
    """Two queueing jobs order themselves rather than both racing the holder."""
    from contextlib import contextmanager

    @contextmanager
    def busy(_name, **_kwargs):
        yield False

    monkeypatch.setattr(db, "advisory_lock", busy)
    monkeypatch.setattr(db, "advisory_lock_holder", lambda _name: 91)

    code = job_runner.run_job("example-job", lambda: None, lock=True, lock_wait_seconds=120)

    assert code == job_contract.EXIT_SKIPPED
    assert json.loads(capsys.readouterr().out) == {"locked": True, "queuedBehind": 91}


def test_announcing_a_wait_cannot_double_the_wait_the_caller_asked_for(monkeypatch):
    """Two locks, one budget.

    `lock_wait_seconds` has to stay well inside the job's own timeout, because
    waiting past that is a kill and a kill is worse than the skip it replaced.
    Time spent reserving is time not spent queueing.
    """
    from contextlib import contextmanager

    seen = []
    clock = iter([1000.0, 1090.0])

    @contextmanager
    def record(_name, **kwargs):
        seen.append(kwargs.get("timeout_seconds"))
        yield True

    monkeypatch.setattr(db, "advisory_lock", record)
    monkeypatch.setattr(db, "advisory_lock_holder", lambda _name: None)
    monkeypatch.setattr(job_runner.time, "monotonic", lambda: next(clock))

    job_runner.run_job("example-job", lambda: None, lock=True, lock_wait_seconds=120)

    assert seen == [120, 30]


def _scheduled_modes() -> dict[str, str]:
    """Map each people_reconcile.py mode flag to the job that schedules it.

    Read out of jobs.yaml rather than restated here: a flag renamed on one
    side and not the other has to fail, not quietly test a mode nobody runs.
    """
    modes: dict[str, str] = {}
    name = ""
    for line in (ROOT / "jobs.yaml").read_text().splitlines():
        if line.startswith("- name: "):
            name = line.removeprefix("- name: ").strip()
        if "people_reconcile.py" in line:
            tail = line.split("people_reconcile.py", 1)[1]
            flags = [token for token in tail.split() if token.startswith("--")]
            if flags:
                modes[flags[0]] = name
    return modes


def _run_job_kwargs(argv: list[str], monkeypatch) -> dict:
    """Ask the entrypoint itself what it would pass, rather than the constants."""
    import people_reconcile as entrypoint

    seen: list[dict] = []
    monkeypatch.setattr(
        job_runner,
        "run_job",
        lambda _name, _body, **kwargs: seen.append(kwargs) or job_contract.EXIT_OK,
    )
    entrypoint.main(argv)
    return seen[0]


def _wait_for(mode: str, monkeypatch) -> int:
    return _run_job_kwargs([mode], monkeypatch).get("lock_wait_seconds")


def _retry_budget_for(argv: list[str], monkeypatch) -> int:
    return _run_job_kwargs(argv, monkeypatch).get("retry_on_lock_timeout")


def test_each_mode_waits_in_proportion_to_how_long_until_its_next_attempt(monkeypatch):
    """One lock, four schedules that all fire on the minute, so they race.

    What a mode should spend winning that race is what losing it costs, and
    that is the gap to its next attempt -- not how much work it carries. The
    weekly pass had this backwards and skipped a whole week's run on
    2026-08-23 after losing to a drain that would have retried in a minute.
    """
    jobs = {job.name: job for job in job_catalog.load(ROOT / "jobs.yaml")}
    modes = _scheduled_modes()
    # Four modes share this lock; a parser that found fewer is not testing the
    # ordering, it is testing whichever ones it happened to match.
    assert len(modes) >= 4, modes

    observed = []
    for mode, job_name in modes.items():
        assert job_name in jobs, f"{mode} names a job jobs.yaml does not declare"
        period = jobs[job_name].expected_interval_minutes
        assert period > 0, f"{job_name} has no period to reason about"
        observed.append((period, mode, _wait_for(mode, monkeypatch)))

    ordered = sorted(observed)
    waits = [wait for _period, _mode, wait in ordered]
    assert waits == sorted(waits), ordered
    # The most frequent mode is the one that must never queue: it has another
    # attempt before a wait would even have finished.
    assert ordered[0][2] == 0, ordered[0]
    # ... and the rarest must, or nothing retries it until its next period.
    assert ordered[-1][2] > 0, ordered[-1]


def _stub_user_space(monkeypatch, order: list | None = None) -> None:
    """Stub the user-space phase, which now opens a session of its own.

    Entrypoint tests hand `session_scope` a null context, so the real
    `synchronize` would be reconciling against no session at all. Pass `order`
    to record where the phase falls relative to the lock and the remote batch.
    """
    import people_reconcile as entrypoint

    def synchronize(_session) -> dict:
        if order is not None:
            order.append(("userSpace", None))
        return wikimedia_user_reconciliation.empty_stats()

    monkeypatch.setattr(entrypoint.wikimedia_user_reconciliation, "synchronize", synchronize)


def test_a_sweep_reports_how_long_its_remote_and_local_phases_took(monkeypatch):
    """One duration for two phases cannot say which one needs the budget.

    The remote half is a bounded batch and the local half is a full scan that
    grows with the catalog, so the same total means opposite things depending
    on the split. A run killed at its timeout reports nothing at all, which
    leaves the finished runs as the only place this can be read.
    """
    import people_reconcile as entrypoint

    captured = {}
    monkeypatch.setattr(
        job_runner,
        "run_job",
        lambda _name, body, **_kwargs: captured.update(body()) or job_contract.EXIT_OK,
    )
    monkeypatch.setattr(
        entrypoint.people_reconcile,
        "resolve_remote_batches",
        lambda **_kwargs: time.sleep(0.05) or (None, None),
    )
    monkeypatch.setattr(entrypoint.people_reconcile, "run", lambda *_args, **_kwargs: {"mode": "apply"})
    monkeypatch.setattr(entrypoint.db, "session_scope", contextlib.nullcontext)
    _stub_user_space(monkeypatch)

    entrypoint.main(["--identities-only"])

    phases = captured["phaseSeconds"]
    # The rebuild phase belongs to --apply, so --identities-only must not claim
    # to have spent time in a phase it never entered.
    assert set(phases) == {"userSpace", "remote", "local"}
    # Not one total attributed twice: only the stub that slept is charged for it.
    assert phases["remote"] >= 0.05
    assert phases["local"] < phases["remote"]


def test_a_sweep_that_raises_still_reports_the_phase_it_died_in(monkeypatch):
    """Timings recorded only on success would be missing from every bad run."""
    import people_reconcile as entrypoint

    phases: dict[str, float] = {}
    with pytest.raises(RuntimeError):
        with entrypoint._timed(phases, "local"):
            raise RuntimeError("upstream went away")

    assert "local" in phases


def test_no_mode_waits_so_long_that_its_own_job_is_killed_instead(monkeypatch):
    """Waiting past the timeout would be a kill, which is worse than a skip.

    Toolforge counts the wait against the job's own timeout rather than adding
    to it, so every second spent here is a second the run that follows does
    not get.
    """
    jobs = {job.name: job for job in job_catalog.load(ROOT / "jobs.yaml")}
    modes = _scheduled_modes()
    assert len(modes) >= 4, modes

    for mode, job_name in modes.items():
        timeout = jobs[job_name].timeout_seconds
        assert timeout, f"{job_name} must declare a timeout"
        assert _wait_for(mode, monkeypatch) < timeout / 2, mode


def test_only_the_weekly_pass_outlasts_the_whole_drain_it_races(monkeypatch):
    """The deliberate line between the hourly wait and the full pass's.

    In practice the drain holds the lock for well under a minute, which any of
    these waits covers. Waiting out its declared timeout as well is insurance
    the hourly modes cannot afford inside their own timeouts and do not need,
    because they try again in an hour. The full pass tries again in a week.
    """
    jobs = {job.name: job for job in job_catalog.load(ROOT / "jobs.yaml")}
    modes = _scheduled_modes()
    drain = jobs[modes["--queue"]]
    assert drain.expected_interval_minutes == 1, "the drain is the mode that runs every minute"

    assert _wait_for("--apply", monkeypatch) > drain.timeout_seconds
    for mode in ("--reconverge", "--identities-only"):
        assert 0 < _wait_for(mode, monkeypatch) <= drain.timeout_seconds, mode


def test_an_unscheduled_mode_waits_like_the_pass_nothing_will_retry(monkeypatch):
    """--retirements and a bare dry run are only ever started by hand.

    Compared against the other modes rather than against the constant it is
    routed to, which would agree with itself whatever that constant became.
    """
    retirements = _wait_for("--retirements", monkeypatch)

    assert retirements == _wait_for("--apply", monkeypatch)
    assert retirements > _wait_for("--reconverge", monkeypatch)


def test_interval_minutes_uses_the_longest_month_for_a_monthly_schedule():
    # Worker health must tolerate the longest valid silence between two runs.
    assert job_catalog._interval_minutes("30 5 15 * *") == 31 * 24 * 60


def test_interval_minutes_rejects_a_non_numeric_day_of_month():
    assert job_catalog._interval_minutes("30 5 nope * *") == 0


def test_load_returns_no_jobs_when_the_file_is_missing():
    assert job_catalog.load(Path("/nonexistent/toolhub-evolved-jobs.yaml")) == []


def test_no_scheduled_job_entrypoint_still_configures_the_database_by_hand():
    """The whole point of the helper is that this stays true as jobs are added."""
    offenders = []
    for line in (ROOT / "jobs.yaml").read_text().splitlines():
        if "proxy/" not in line or ".py" not in line:
            continue
        for token in line.split():
            if token.startswith("/data/project") and token.endswith(".py") or token.endswith(".py"):
                name = Path(token).name
                script = ROOT / "proxy" / name
                if script.exists() and "db.configure(os.environ.get" in script.read_text():
                    offenders.append(name)
    assert sorted(set(offenders)) == []


GONE_AWAY = "MySQL server has gone away"
REJECTED = "Unknown column"


def _rejected() -> Exception:
    """Build a DBAPIError the pool never invalidated: the statement itself failed."""
    return DBAPIError("SELECT 1", {}, Exception(REJECTED))


def _disconnect() -> Exception:
    """Build the DBAPIError pymysql raises when ToolsDB drops the connection."""
    error = DBAPIError("SELECT 1", {}, Exception(GONE_AWAY))
    error.connection_invalidated = True
    return error


def test_a_connection_dropped_mid_run_is_retried_once(capsys):
    attempts = []

    def body() -> dict:
        attempts.append(1)
        if len(attempts) == 1:
            raise _disconnect()
        return {"attempt": len(attempts)}

    code = job_runner.run_job("example-job", body, retry_on_disconnect=True)
    assert code == job_contract.EXIT_OK
    assert attempts == [1, 1]
    out = capsys.readouterr()
    assert json.loads(out.out.strip().removeprefix("example-job: ")) == {"attempt": 2}
    assert "retrying once" in out.err


def test_the_retry_is_opt_in_so_a_body_with_side_effects_never_repeats():
    attempts = []

    def body() -> dict:
        attempts.append(1)
        raise _disconnect()

    with pytest.raises(DBAPIError):
        job_runner.run_job("example-job", body)
    assert attempts == [1]


def test_a_failure_that_is_not_a_disconnect_is_not_retried():
    attempts = []

    def body() -> dict:
        attempts.append(1)
        # Same exception class, but the pool never invalidated the connection:
        # the statement itself was rejected, and running it again would only
        # reject it again.
        raise _rejected()

    with pytest.raises(DBAPIError):
        job_runner.run_job("example-job", body, retry_on_disconnect=True)
    assert attempts == [1]


def _lock_timeout() -> Exception:
    """Build the DBAPIError PyMySQL raises when InnoDB stops waiting on a row."""
    return DBAPIError("UPDATE person_identifiers ...", {}, Exception(1205, "Lock wait timeout exceeded"))


def _clock(*ticks: float, monkeypatch) -> None:
    """Hand run_job a start and an elapsed reading, so the budget is testable."""
    readings = iter(ticks)
    monkeypatch.setattr(job_runner.time, "monotonic", lambda: next(readings))


def test_a_row_lock_lost_early_enough_to_try_again_is_tried_again(capsys, monkeypatch):
    """The database rolled the transaction back, so there is nothing to resume.

    This is what ended people-identity-reconcile 205s into a 1500s timeout on
    2026-08-29: an UPDATE waited out innodb_lock_wait_timeout and took the pass
    with it, an hour before the next attempt.
    """
    _clock(0.0, 205.0, monkeypatch=monkeypatch)
    attempts = []

    def body() -> dict:
        attempts.append(1)
        if len(attempts) == 1:
            raise _lock_timeout()
        return {"attempt": len(attempts)}

    code = job_runner.run_job("example-job", body, retry_on_lock_timeout=750)
    assert code == job_contract.EXIT_OK
    assert attempts == [1, 1]
    assert "lost a row lock 205s in; retrying once" in capsys.readouterr().err


def test_a_row_lock_lost_too_late_to_finish_a_second_pass_is_reported_instead(capsys, monkeypatch):
    """A retry costs what the aborted attempt cost, and past the budget the job
    would be killed part way through it -- which says nothing at all, whereas
    this failure mails."""
    _clock(0.0, 900.0, monkeypatch=monkeypatch)
    attempts = []

    def body() -> dict:
        attempts.append(1)
        raise _lock_timeout()

    with pytest.raises(DBAPIError):
        job_runner.run_job("example-job", body, retry_on_lock_timeout=750)
    assert attempts == [1]
    assert "too late in the run to retry" in capsys.readouterr().err


def test_the_lock_retry_is_opt_in_so_a_job_with_no_budget_never_repeats_its_body(monkeypatch):
    _clock(0.0, 5.0, monkeypatch=monkeypatch)
    attempts = []

    def body() -> dict:
        attempts.append(1)
        raise _lock_timeout()

    with pytest.raises(DBAPIError):
        job_runner.run_job("example-job", body)
    assert attempts == [1]


def test_a_failure_that_is_not_a_lock_conflict_does_not_spend_the_lock_budget(monkeypatch):
    _clock(0.0, 5.0, monkeypatch=monkeypatch)
    attempts = []

    def body() -> dict:
        attempts.append(1)
        # The statement was rejected rather than rolled back, so a second
        # attempt has the same argument with the same database.
        raise _rejected()

    with pytest.raises(DBAPIError):
        job_runner.run_job("example-job", body, retry_on_lock_timeout=750)
    assert attempts == [1]


def test_each_scheduled_mode_budgets_its_retry_out_of_the_timeout_jobs_yaml_declares(monkeypatch):
    """The retry has to fit inside the timeout it is racing, and only jobs.yaml
    knows what that is -- a ceiling guessed in the entrypoint is exactly how a
    retry ends up running past a timeout it never knew about."""
    import people_reconcile as entrypoint

    jobs = {job.name: job for job in job_catalog.load(ROOT / "jobs.yaml")}
    modes = _scheduled_modes()
    assert len(modes) >= 4, modes

    for mode, job_name in modes.items():
        declared = jobs[job_name].timeout_seconds
        assert declared > 0, f"{job_name} declares no timeout to budget against"
        # The four timeouts differ, so a mode that resolved the wrong job here
        # cannot land on the right number by accident.
        budget = _retry_budget_for([mode], monkeypatch)
        assert budget == declared // entrypoint.LOCK_RETRY_BUDGET_FRACTION, mode
        assert 0 < budget < declared


def test_a_mode_nothing_schedules_gets_no_budget_rather_than_a_borrowed_one(monkeypatch):
    """Nothing times out a hand-run pass, so there is no timeout to divide and
    an operator watching one does not need a retry to learn it lost a lock."""
    assert _retry_budget_for([], monkeypatch) == 0
    assert _retry_budget_for(["--retirements"], monkeypatch) == 0


def test_the_retry_re_enters_through_the_lock_rather_than_resuming_inside_it(capsys, monkeypatch):
    from contextlib import contextmanager

    acquisitions = []

    @contextmanager
    def lock(_name, **_kwargs):
        acquisitions.append(1)
        # A dropped connection released whatever locks it held, so the second
        # attempt must find out who owns it now instead of assuming it still does.
        yield acquisitions == [1]

    monkeypatch.setattr(db, "advisory_lock", lock)
    attempts = []

    def body() -> dict:
        attempts.append(1)
        raise _disconnect()

    code = job_runner.run_job("example-job", body, lock=True, retry_on_disconnect=True)
    assert code == job_contract.EXIT_SKIPPED
    assert acquisitions == [1, 1]
    # The lock was gone on the retry, so the body never ran a second time.
    assert attempts == [1]
    assert json.loads(capsys.readouterr().out.strip()) == {"locked": True, "heldBy": None}


def test_a_lock_skip_reports_who_was_holding_it(monkeypatch, capsys):
    """Eight identical `{"locked": true}` lines say nothing about which fix is needed."""
    from contextlib import contextmanager

    @contextmanager
    def busy(_name, **_kwargs):
        yield False

    asked = []
    lock = f"{job_runner.LOCK_PREFIX}example-job"
    intent = f"{lock}{job_runner.INTENT_SUFFIX}"
    monkeypatch.setattr(db, "advisory_lock", busy)
    monkeypatch.setattr(
        db,
        "advisory_lock_holder",
        lambda name: asked.append(name) or (None if name == intent else 4172),
    )

    code = job_runner.run_job("example-job", lambda: None, lock=True)

    assert code == job_contract.EXIT_SKIPPED
    assert json.loads(capsys.readouterr().out) == {"locked": True, "heldBy": 4172}
    # Asked about the prefixed lock, not the bare job name: the wrong name would
    # always answer "nobody" and quietly turn the diagnostic back into noise.
    # Nobody was queueing, so this is a plain loss to the holder rather than a
    # yield, and the two are named differently because the fixes differ.
    assert asked == [intent, lock]


def test_a_skip_is_distinguishable_from_both_of_the_outcomes_it_is_not():
    """The whole point: three states, three codes, none of them colliding."""
    assert job_contract.EXIT_SKIPPED not in {job_contract.EXIT_OK, job_contract.EXIT_SWEEP_FAILED}
    # 128+n is "killed by signal n"; a skip that landed there would read as a crash.
    assert job_contract.EXIT_SKIPPED < 128


def test_conflict_timestamp_refreshes_land_after_the_pass_has_committed(monkeypatch):
    """Deferring the write only helps if it is applied outside the transaction.

    Applied inside, it is a second connection waiting on locks the first still
    holds -- the collision the deferral exists to avoid, rebuilt one layer down.
    The ordering is the entire fix, so it is what this asserts.
    """
    import people_reconcile as entrypoint

    events = []

    @contextlib.contextmanager
    def scope():
        events.append("begin")
        yield None
        events.append("commit")

    def fake_run(*_args, deferred_conflict_refreshes=None, **_kwargs):
        deferred_conflict_refreshes.append(2700)
        return {"mode": "apply", "runId": 761}

    captured = {}
    monkeypatch.setattr(
        job_runner,
        "run_job",
        lambda _name, body, **_kwargs: captured.update(body()) or job_contract.EXIT_OK,
    )
    monkeypatch.setattr(entrypoint.people_reconcile, "resolve_remote_batches", lambda **_kwargs: (None, None))
    monkeypatch.setattr(entrypoint.people_reconcile, "run", fake_run)
    monkeypatch.setattr(
        entrypoint.people_reconcile,
        "refresh_conflicts_seen",
        lambda ids, *, run_id: events.append(("refresh", list(ids), run_id)) or {"requested": 1, "refreshed": 1},
    )
    monkeypatch.setattr(entrypoint.db, "session_scope", scope)
    _stub_user_space(monkeypatch)

    entrypoint.main(["--identities-only"])

    # Two transactions now: the user-space phase commits and releases its
    # `person_identifiers` locks before the pass that used to hold them opens.
    assert events == ["begin", "commit", "begin", "commit", ("refresh", [2700], 761)]
    # Reported, so a refresh that keeps losing its race is visible in the log
    # rather than being the silent half of an otherwise successful run.
    assert captured["conflictRefreshes"] == {"requested": 1, "refreshed": 1}


def test_the_remote_phase_of_an_identities_run_happens_before_the_lock(monkeypatch):
    """Two minutes of Wikimedia round trips are not worth a lock four jobs want.

    The pass finishes within a hundred seconds of its own 1500s timeout, and
    the remote phase needs no row at all: it reads its batch, closes the
    session, and then waits on the network. Ahead of the lock it costs the hold
    nothing, and the hold is what the other three modes are queueing behind.
    """
    import people_reconcile as entrypoint

    order = []

    @contextlib.contextmanager
    def lock(name, **_kwargs):
        order.append(("lock", name))
        yield True

    monkeypatch.setattr(entrypoint.db, "advisory_lock", lock)
    monkeypatch.setattr(entrypoint.db, "advisory_lock_holder", lambda _name: None)
    monkeypatch.setattr(entrypoint.db, "session_scope", contextlib.nullcontext)
    monkeypatch.setattr(entrypoint.job_runner, "configure", lambda **_: None)
    monkeypatch.setattr(job_runner, "configure", lambda **_: None)
    monkeypatch.setattr(
        entrypoint.people_reconcile,
        "resolve_remote_batches",
        lambda **_kwargs: order.append(("remote", None)) or (None, None),
    )
    monkeypatch.setattr(entrypoint.people_reconcile, "run", lambda *_args, **_kwargs: {"mode": "apply", "runId": 1})
    _stub_user_space(monkeypatch, order)

    assert entrypoint.main(["--identities-only"]) == job_contract.EXIT_OK

    assert order[0] == ("remote", None)
    # The user-space phase writes, so unlike the remote batch it stays inside
    # the lock -- it moved out of the pass's transaction, not out of the lock.
    assert [step for step, _name in order[1:]] == ["lock", "lock", "userSpace"]


def test_a_full_pass_still_resolves_inside_the_lock(monkeypatch):
    """Its labels are what its own rebuild phase discovers, so it cannot hoist."""
    import people_reconcile as entrypoint

    order = []

    @contextlib.contextmanager
    def lock(name, **_kwargs):
        order.append(("lock", name))
        yield True

    monkeypatch.setattr(entrypoint.db, "advisory_lock", lock)
    monkeypatch.setattr(entrypoint.db, "advisory_lock_holder", lambda _name: None)
    monkeypatch.setattr(entrypoint.db, "session_scope", contextlib.nullcontext)
    monkeypatch.setattr(entrypoint.job_runner, "configure", lambda **_: None)
    monkeypatch.setattr(job_runner, "configure", lambda **_: None)
    monkeypatch.setattr(
        entrypoint.people_reconcile,
        "resolve_remote_batches",
        lambda **_kwargs: order.append(("remote", None)) or (None, None),
    )
    monkeypatch.setattr(
        entrypoint.people_reconcile,
        "run",
        lambda *_args, **_kwargs: {"mode": "apply", "runId": 1, "toolsRebuilt": 0},
    )
    _stub_user_space(monkeypatch, order)

    assert entrypoint.main(["--apply"]) == job_contract.EXIT_OK

    assert [step for step, _name in order] == ["lock", "lock", "userSpace", "remote"]


def test_the_summary_is_left_where_the_guard_asked_for_it(monkeypatch, tmp_path, capsys):
    """The process that knows what ran cannot write the row, so the two meet in a file.

    Only the guard can tell a child that finished from one that was killed
    without a word, so it -- not the job -- writes job_runs. This is how the
    job's own account of the run reaches it.
    """
    handoff = tmp_path / "example-job.summary.json"
    monkeypatch.setenv("TOOLHUB_JOB_SUMMARY_FILE", str(handoff))

    job_runner.run_job("example-job", lambda: {"counts": {"done": 4}})

    assert json.loads(handoff.read_text()) == {"counts": {"done": 4}}
    # Still printed: the log line is what a human reads, and the file is not it.
    assert capsys.readouterr().out.startswith("example-job: ")


def test_a_job_run_outside_the_guard_just_prints(capsys):
    job_runner.run_job("example-job", lambda: {"counts": {"done": 4}})
    assert capsys.readouterr().out.startswith("example-job: ")


def test_a_summary_that_cannot_be_handed_over_does_not_fail_the_run(monkeypatch, tmp_path, capsys):
    """Publishing a summary is observability: it cannot fail a job that worked."""
    monkeypatch.setenv("TOOLHUB_JOB_SUMMARY_FILE", str(tmp_path / "no-such-dir" / "s.json"))

    code = job_runner.run_job("example-job", lambda: {"counts": {"done": 4}})

    assert code == job_contract.EXIT_OK
    assert capsys.readouterr().out.startswith("example-job: ")


def test_a_skipped_run_hands_over_no_summary(monkeypatch, tmp_path):
    """It did no work, and a stale file would attribute someone else's to it."""
    from contextlib import contextmanager

    @contextmanager
    def busy(_name, **_kwargs):
        yield False

    monkeypatch.setattr(db, "advisory_lock", busy)
    handoff = tmp_path / "example-job.summary.json"
    monkeypatch.setenv("TOOLHUB_JOB_SUMMARY_FILE", str(handoff))

    job_runner.run_job("example-job", lambda: {"counts": {"done": 4}}, lock=True)

    assert not handoff.exists()


# --- ToolsDB connection budget -------------------------------------------
#
# One account allows 20 connections. Sizing job processes like webservice
# workers spent them twice over, which surfaced as HTTP 500s on the catalog
# search fan-out rather than as anything a job reported.


def test_a_locking_job_gets_the_four_connections_it_was_measured_holding():
    # Not derived -- measured. Two came from reading advisory_lock, three from
    # reading run_job's intent lock on top, and both were wrong: people_reconcile
    # takes a third advisory lock fourteen frames below the entrypoint, which no
    # reading of the scaffold finds. Instrumenting the pool on production on
    # 2026-09-03 gave a peak of 4 for people-identity-reconcile, 3 for
    # source-attestations and projection-refresh, 2 for the rest.
    assert sum(db.pool_limits(web=False, takes_lock=True)) == 4


def test_run_job_declares_the_lock_it_takes_to_the_pool_that_has_to_hold_it():
    # The declaration has to come from run_job: it is the code that takes the
    # lock, and a job that forgets to mention it gets a pool too small to run in.
    source = Path(job_runner.__file__).read_text(encoding="utf-8")
    assert "configure(takes_lock=lock)" in source


def test_a_job_gets_a_connection_for_its_lock_and_another_for_its_session():
    # advisory_lock() holds a connection for as long as its body runs and the
    # body then opens a session, so a one-connection ceiling would not deadlock
    # visibly -- it would wait out pool_timeout and fail the six jobs that take
    # a lock. Two is the floor for a job that runs its work on one thread.
    pool_size, max_overflow = db.pool_limits(web=False)
    assert pool_size + max_overflow == 2


def test_a_job_that_runs_work_in_parallel_is_budgeted_per_unit_not_per_process():
    # projection_refresh runs two account generations side by side and each one
    # takes a lock plus a session.
    pool_size, max_overflow = db.pool_limits(web=False, concurrency=2)
    assert pool_size + max_overflow == 4


def test_the_webservice_fleet_leaves_most_of_the_account_to_the_jobs():
    # The webservice is four workers, so its share of the account is four times
    # its per-worker ceiling -- the product, not the ceiling, is what has to stay
    # small. At 2 + 2 it claimed 16 of 20 and left four for every job together,
    # which is the arithmetic that returned HTTP 500s on 2026-09-02. Half the
    # account is the line: the jobs need the rest, and there are always several.
    fleet = db.WEBSERVICE_WORKERS * sum(db.pool_limits(web=True))
    assert fleet * 2 <= db.TOOLSDB_ACCOUNT_CONNECTION_LIMIT


def test_the_account_supplies_the_fleet_and_the_widest_job_beside_it():
    # The version of this that counted five *typical* jobs passed while
    # production returned a max_user_connections 500: projection_refresh
    # declares two units, so it costs four connections where the others cost
    # two, and the real total was 20 of 20 rather than the 18 this asserted.
    # Reading the width from the job itself is what makes raising it fail here
    # rather than in production.
    import projection_refresh

    demand = db.account_demand(widest_job_concurrency=projection_refresh.PARALLEL_SYNC_WORKERS)

    assert demand + db.ACCOUNT_HEADROOM <= db.TOOLSDB_ACCOUNT_CONNECTION_LIMIT


def test_widening_the_parallel_job_again_would_overrun_the_account():
    # The guard the earlier version of this test did not provide. It was first
    # written asserting the old setting exceeded the grant and failed, because
    # back when a locking job was counted at two the old setting spent exactly
    # the grant rather than passing it -- "spends everything" is what explains an
    # intermittent failure, and it is why ACCOUNT_HEADROOM exists at all.
    assert db.account_demand(widest_job_concurrency=2) + db.ACCOUNT_HEADROOM > db.TOOLSDB_ACCOUNT_CONNECTION_LIMIT


def test_an_undeclared_call_site_costs_the_account_a_job_pool_not_a_worker_pool(monkeypatch):
    # The expensive budget is the one that has to be asked for by name.
    monkeypatch.setenv("TOOLHUB_DB_URL", "mysql+pymysql://user:pw@example.invalid/db")
    try:
        db.configure(job_runner.database_url())
        assert db.engine().pool.size() == db.POOL_SIZE_PER_JOB
        db.configure(job_runner.database_url(), web=True)
        assert db.engine().pool.size() == db.POOL_SIZE_PER_WORKER
    finally:
        db.configure("sqlite://")


def test_projection_refresh_tells_the_pool_the_same_width_it_tells_its_thread_pool():
    # Two numbers that must agree, in two files. This is the one that notices.
    import projection_refresh

    source = Path(projection_refresh.__file__).read_text(encoding="utf-8")
    assert "ThreadPoolExecutor(max_workers=PARALLEL_SYNC_WORKERS" in source
    assert "job_runner.configure(concurrency=PARALLEL_SYNC_WORKERS, takes_lock=True)" in source


def test_every_entrypoint_that_takes_a_lock_declares_it_to_its_pool():
    """A lock the pool was not told about is a pool one connection too small.

    `run_job` declares the lock it takes, which covers the jobs that go through
    it. Five entrypoints take an advisory lock on their own instead, and the
    first fix reached only the one that happened to be open in the editor at the
    time: catalog-sync, account-sync and toolforge-account-sync kept a
    two-connection pool and catalog-sync timed out on it at 00:33:58 on
    2026-09-03. Reading the source is worth more than remembering, because the
    next entrypoint to take a lock will be written by someone who never saw this.
    """
    proxy = Path(__file__).resolve().parents[2] / "proxy"
    undeclared = []
    for path in sorted(proxy.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "db.advisory_lock(" not in source:
            continue
        # Either the scaffold takes the lock and declares it, or the entrypoint
        # configures its own engine and has to say so in that call.
        if "run_job(" in source and "lock=True" in source:
            continue
        if "takes_lock=True" in source:
            continue
        undeclared.append(path.name)

    assert not undeclared, f"these take an advisory lock without declaring it to the pool: {undeclared}"


def test_a_job_without_a_declared_timeout_gets_no_retry_budget():
    """The rule that made this change need a timeout first.

    A retry budget is half a declared timeout. Inventing one for an unbounded
    job is how a retry runs past a limit it never knew about, so the helper
    returns zero and the caller has to declare the timeout to get the retry.
    """
    assert job_runner.lock_retry_deadline_seconds("no-such-job") == 0
    assert job_runner.lock_retry_deadline_seconds(None) == 0


def test_the_source_index_declares_the_timeout_its_retry_spends_half_of():
    """toolinfo-source-index opted into the lock retry, so it needs a bound.

    900s against a measured max of 392s over twelve runs. If the timeout is
    ever removed the retry silently becomes a no-op, which is the failure this
    pins: the budget must be a real number, not zero.
    """
    budget = job_runner.lock_retry_deadline_seconds("toolinfo-source-index")

    assert budget > 0, "the source index lost its declared timeout, so its lock retry does nothing"
    assert budget == 900 // job_runner.LOCK_RETRY_BUDGET_FRACTION
