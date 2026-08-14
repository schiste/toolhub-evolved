# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the scheduled Toolhub recent-change cache invalidator."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

import cache_invalidation  # noqa: E402
from backend import api_cache, db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()
    api_cache.clear()


class FakeRecentResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload if payload is not None else {"results": []}
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeRecentSession:
    def __init__(self, responses=None, raises=None):
        self.responses = list(responses or [])
        self.raises = raises
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.responses.pop(0) if self.responses else FakeRecentResponse()


def _put(url):
    api_cache.put_success(
        url,
        api_cache.CacheableResponse(status=200, content_type="application/json", body=b'{"cached":true}'),
    )


def test_fetch_recent_change_rows_reads_toolhub_recent_rows():
    session = FakeRecentSession(
        [
            FakeRecentResponse(
                payload={
                    "results": [
                        {"id": 2, "content_type": "tool"},
                        "not-a-row",
                        {"id": 1, "content_type": "list"},
                    ]
                }
            )
        ]
    )

    assert cache_invalidation.fetch_recent_change_rows(session) == [
        {"id": 2, "content_type": "tool"},
        {"id": 1, "content_type": "list"},
    ]
    assert session.calls[0][0] == "https://toolhub.wikimedia.org/api/recent/?page_size=50"
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["timeout"] == 10
    assert session.calls[0][1]["headers"]["Accept"] == "application/json"


def test_fetch_recent_change_rows_treats_failures_as_no_rows():
    assert cache_invalidation.fetch_recent_change_rows(
        FakeRecentSession(raises=cache_invalidation.requests.RequestException("timeout"))
    ) == []
    assert cache_invalidation.fetch_recent_change_rows(FakeRecentSession([FakeRecentResponse(503)])) == []
    assert cache_invalidation.fetch_recent_change_rows(
        FakeRecentSession([FakeRecentResponse(json_error=ValueError("bad json"))])
    ) == []
    assert cache_invalidation.fetch_recent_change_rows(
        FakeRecentSession([FakeRecentResponse(payload={"results": "not-list"})])
    ) == []


def test_run_once_invalidates_only_cache_rows_changed_since_last_marker(monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    old_row = {"id": 1, "timestamp": "2026-01-01T11:59:00Z", "content_type": "tool", "content_id": "old-tool"}
    new_row = {"id": 2, "timestamp": "2026-01-01T12:01:00Z", "content_type": "tool", "content_id": "fresh-tool"}

    first = FakeRecentSession([FakeRecentResponse(payload={"results": [old_row]})])
    assert cache_invalidation.run_once(first) == 0

    _put("https://toolhub.wikimedia.org/api/tools/fresh-tool/")
    _put("https://toolhub.wikimedia.org/api/search/tools/?q=wiki")
    _put("https://toolhub.wikimedia.org/api/schema/")

    clock["t"] += timedelta(seconds=api_cache.RECENT_POLL_SECONDS + 1)
    second = FakeRecentSession([FakeRecentResponse(payload={"results": [new_row, old_row]})])
    assert cache_invalidation.run_once(second) == 2
    assert api_cache.get("https://toolhub.wikimedia.org/api/tools/fresh-tool/") is None
    assert api_cache.get("https://toolhub.wikimedia.org/api/search/tools/?q=wiki") is None
    assert api_cache.get("https://toolhub.wikimedia.org/api/schema/") is not None


def test_main_configures_db_runs_once_and_prints(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/cache.sqlite3")
    monkeypatch.setattr(cache_invalidation, "run_once", lambda: 7)
    monkeypatch.setattr(
        cache_invalidation.cache_prewarm,
        "run_once",
        lambda: cache_invalidation.cache_prewarm.PrewarmSummary(endpoints=3, warmed=2, skipped=1),
    )
    monkeypatch.setattr(cache_invalidation.recent_owners, "purge_expired", lambda: 4)
    assert cache_invalidation.main() == 0
    out = capsys.readouterr().out
    assert "cache-invalidation: 7 rows invalidated, 4 owner rows purged" in out
    assert "cache-prewarm: warmed=2 revalidated=0 skipped=1 failed=0 endpoints=3 owners=0 owner_cached=0" in out
    assert os.environ["TOOLHUB_DB_URL"].endswith("cache.sqlite3")


def test_policy_for_url_uses_crawler_runs_policy():
    policy = api_cache.policy_for_url("https://toolhub.wikimedia.org/api/crawler/runs/")
    assert policy.fresh_seconds == api_cache.CRAWLER_FRESH_SECONDS


def test_delete_where_returns_zero_for_no_clause():
    # No call site currently passes clause=None (every invalidate_* guards
    # against an empty key before building a clause), but the guard inside
    # _delete_where itself is still worth keeping honest.
    assert api_cache._delete_where(None) == 0


def test_backfill_index_columns_stops_on_database_error(monkeypatch):
    _put("https://toolhub.wikimedia.org/api/tools/broken-tool/")
    with db.session_scope() as s:
        s.query(api_cache.ApiCache).update({"path": ""})

    monkeypatch.setattr(
        api_cache, "select", lambda *_a, **_k: (_ for _ in ()).throw(SQLAlchemyError("boom"))
    )

    assert api_cache.backfill_index_columns() == 0


def test_upgrade_schema_skips_a_table_that_does_not_exist():
    # db.init_schema() already created both attempts-tracking tables via ORM
    # metadata, so _upgrade_schema() only ever sees the "table present"
    # branch during normal fixture setup. Dropping one here, while leaving
    # the other in place, exercises the "table missing" branch (continues
    # the loop) alongside the "table present" branch in the same pass.
    eng = db.engine()
    assert "person_reconciliation_queue" in set(inspect(eng).get_table_names())
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP TABLE repository_analysis_state")

    db._upgrade_schema()  # must not raise despite the missing table

    assert "repository_analysis_state" not in set(inspect(eng).get_table_names())


def test_advisory_lock_reports_unacquired_on_mariadb_without_masking_release(monkeypatch):
    from types import SimpleNamespace

    class FailingLockConnection:
        def __init__(self):
            self.closed = False

        def scalar(self, *_args, **_kwargs):
            # GET_LOCK returned something other than 1: another session holds it.
            return 0

        def close(self):
            self.closed = True

    connection = FailingLockConnection()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"), connect=lambda: connection)
    monkeypatch.setattr(db, "engine", lambda: fake_engine)

    with db.advisory_lock("contested-lock") as acquired:
        assert acquired is False

    assert connection.closed is True
