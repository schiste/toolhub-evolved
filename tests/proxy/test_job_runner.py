# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared job scaffold keeps every entrypoint's conventions identical."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import DEFAULT_DB_URL, db, job_catalog, job_contract, job_runner  # noqa: E402


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
    # must not count toward the guard's breaker.
    assert code == job_contract.EXIT_OK
    assert ran == []
    assert json.loads(capsys.readouterr().out) == {"locked": True}


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


def test_interval_minutes_returns_zero_for_an_unclassifiable_cron_shape():
    # Specific minute, specific non-"*/" hour, specific day-of-month, and a
    # wildcard day-of-week does not match any of the coarse buckets this
    # reader distinguishes, so it falls through to the explicit 0.
    assert job_catalog._interval_minutes("30 5 15 * *") == 0


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
