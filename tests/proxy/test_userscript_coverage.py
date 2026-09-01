# SPDX-License-Identifier: GPL-3.0-or-later
"""Serving the user-script roster from a stored copy, and who pays to rebuild it.

The roster costs four aggregate queries over four tables, one of them holding
half a million rows -- 25 seconds against production, past the point where the
page gives up and renders its failure branch instead. Everything here is about
the arrangement that fixed that: the census stores the roster at the end of
every run, a request serves what is stored however old, and the cases where a
request does rebuild are bounded so that a crowd on a cold cache does not each
run the scan.
"""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import backend  # noqa: E402
from backend import db, userscript_coverage as coverage  # noqa: E402
from backend.models import ApiCacheMeta, UserScriptCensusState, utcnow  # noqa: E402

FRWIKI = "fr.wikipedia.org"
METAWIKI = "meta.wikimedia.org"


@pytest.fixture(autouse=True)
def _database():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    with application.app_context():
        yield


def _lock(*, acquired):
    """Stand in for `db.advisory_lock` with a fixed verdict on the race."""

    @contextmanager
    def advisory_lock(_name, *, timeout_seconds=0):
        yield acquired

    return advisory_lock


def _swept(*wikis):
    with db.session_scope() as session:
        for wiki in wikis:
            session.add(UserScriptCensusState(wiki=wiki))


def _row():
    with db.session_scope() as session:
        stored = session.get(ApiCacheMeta, coverage.SNAPSHOT_KEY)
        return None if stored is None else (json.loads(stored.value), stored.updated_at)


def _age(delta):
    with db.session_scope() as session:
        session.get(ApiCacheMeta, coverage.SNAPSHOT_KEY).updated_at = utcnow() - delta


# --- the census stores it, the request serves it ---


def test_the_census_stores_the_roster_it_just_made_true():
    _swept(FRWIKI, METAWIKI)

    result = coverage.refresh()

    assert result["stored"] is True
    assert result["wikis"] == 2
    stored, _at = _row()
    assert [entry["wiki"] for entry in stored["results"]] == [FRWIKI, METAWIKI]
    assert stored["generatedAt"] == result["generatedAt"]


def test_a_census_run_that_lost_the_lock_stops_instead_of_scanning_for_nothing(monkeypatch):
    _swept(FRWIKI)
    monkeypatch.setattr(coverage.db, "advisory_lock", _lock(acquired=False))

    # The rebuild is the whole cost, and this run is not allowed to store what
    # it would produce. Running it anyway would spend 25 seconds on a payload
    # that goes nowhere.
    assert coverage.refresh() == {"stored": False, "wikis": 0, "reason": "another refresh holds the lock"}
    assert _row() is None


def test_a_request_serves_the_stored_roster_without_taking_the_lock(monkeypatch):
    _swept(FRWIKI)
    coverage.refresh()
    _swept(METAWIKI)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the ordinary read path must not touch the lock")

    monkeypatch.setattr(coverage.db, "advisory_lock", forbidden)

    # One wiki, not two: the reader gets the copy the census stored. Taking the
    # lock first put a round trip in front of every read, and made every reader
    # during a census run wait out the full timeout for a copy it already had.
    assert coverage.snapshot()["count"] == 1


def test_a_roster_older_than_the_census_schedule_is_still_served(monkeypatch):
    _swept(FRWIKI)
    coverage.refresh()
    _age(coverage.SNAPSHOT_MAX_AGE * 2)
    _swept(METAWIKI)
    monkeypatch.setattr(coverage.db, "advisory_lock", _lock(acquired=True))

    # Past `MAX_AGE` a run was skipped or died. The roster carries its own
    # timestamps and the page shows them, so an hour-old count beats an error.
    assert coverage.snapshot()["count"] == 1


# --- the two cases a request does rebuild ---


def test_a_roster_stale_enough_to_mean_a_dead_census_is_rebuilt_by_the_reader():
    _swept(FRWIKI)
    coverage.refresh()
    _age(coverage.SNAPSHOT_STALE_LIMIT * 2)
    _swept(METAWIKI)

    served = coverage.snapshot()

    # This is the bound on how long a dead census can freeze the page.
    assert served["count"] == 2
    assert _row()[0]["count"] == 2


def test_a_stale_roster_is_served_whole_to_the_reader_that_lost_the_lock(monkeypatch):
    _swept(FRWIKI)
    coverage.refresh()
    _age(coverage.SNAPSHOT_STALE_LIMIT * 2)
    _swept(METAWIKI)
    monkeypatch.setattr(coverage.db, "advisory_lock", _lock(acquired=False))

    # Somebody is already rebuilding. Cache contention must not turn into half
    # a dozen concurrent full scans.
    assert coverage.snapshot()["count"] == 1


def test_a_cold_cache_rebuilds_but_leaves_the_row_to_the_rebuild_that_beat_it(monkeypatch):
    _swept(FRWIKI)
    monkeypatch.setattr(coverage.db, "advisory_lock", _lock(acquired=False))

    assert coverage.snapshot()["count"] == 1
    assert _row() is None


def test_a_forced_rebuild_ignores_a_roster_that_is_still_current():
    _swept(FRWIKI)
    coverage.refresh()
    _swept(METAWIKI)

    assert coverage.snapshot(force=True)["count"] == 2


# --- a stored row that cannot be read ---


def test_a_row_that_is_not_readable_json_is_rebuilt_rather_than_served():
    _swept(FRWIKI)
    coverage.refresh()
    with db.session_scope() as session:
        session.get(ApiCacheMeta, coverage.SNAPSHOT_KEY).value = "{not json"

    # A payload and a timestamp that can disagree would leave every caller two
    # cases to handle. An unreadable row is reported as no row at all.
    assert coverage.snapshot()["count"] == 1


def test_a_row_holding_something_that_is_not_a_roster_is_read_as_no_row():
    _swept(FRWIKI)
    coverage.refresh()
    with db.session_scope() as session:
        session.get(ApiCacheMeta, coverage.SNAPSHOT_KEY).value = "[]"

    assert coverage.snapshot()["count"] == 1


def test_a_store_that_fails_still_answers_the_reader_and_says_so(monkeypatch, caplog):
    """This shipped, and returned 500 for a roster 4.7x over the column's ceiling."""
    _swept(FRWIKI)

    def failing_store(*_args, **_kwargs):
        raise coverage.SQLAlchemyError("value too long for column")

    monkeypatch.setattr(coverage, "_store", failing_store)

    with caplog.at_level("ERROR"):
        served = coverage.snapshot()

    # Correct and slow, which is what the endpoint did before the cache existed.
    assert served["count"] == 1
    assert _row() is None
    # Loud, though: every request now rebuilds, and the rebuild is the 25-second
    # scan this cache exists to avoid.
    assert "could not be stored" in caplog.text
