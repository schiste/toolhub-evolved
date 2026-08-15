# SPDX-License-Identifier: GPL-3.0-or-later
"""Failure-path coverage for the local API replica cache."""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import api_cache, db  # noqa: E402
from backend.models import ApiCache  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_local_cache_reads_fail_closed_when_storage_is_unavailable(monkeypatch):
    @contextmanager
    def broken_session():
        raise SQLAlchemyError("database unavailable")
        yield

    monkeypatch.setattr(db, "session_scope", broken_session)

    assert api_cache.get_local("https://example.test/api/tools/") is None
    assert api_cache.responses_for_path("/api/tools/") == []


def test_mark_failure_records_the_bounded_diagnostic():
    url = "https://toolhub.wikimedia.org/api/tools/"
    api_cache.put_success(url, api_cache.CacheableResponse(200, "application/json", b"{}"))

    api_cache.mark_failure(url, "x" * 3000)

    with db.session_scope() as session:
        row = session.scalar(select(ApiCache).where(ApiCache.url == url))
        assert row.last_error == "x" * 2000
