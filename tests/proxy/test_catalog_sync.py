"""Tests for the paced, resumable official catalog synchronization worker."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, toolhub  # noqa: E402
from backend.models import CanonicalToolCache, ToolCatalogSyncState  # noqa: E402
import catalog_sync  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_listing_page_validates_paginated_and_list_payloads(monkeypatch):
    payloads = iter(
        [
            {"results": [{"name": "first"}], "next": "https://toolhub.example/api/tools/?page=2"},
            [{"name": "last"}, "invalid"],
        ]
    )
    monkeypatch.setattr(toolhub, "public_api_get", lambda *_args, **_kwargs: next(payloads))

    assert catalog_sync.listing_page(1, 100) == ([{"name": "first"}], True)
    assert catalog_sync.listing_page(2, 100) == ([{"name": "last"}], False)


def test_run_upserts_pages_tracks_cursor_and_paces_requests(monkeypatch):
    calls = []

    def fake_page(page, page_size):
        calls.append((page, page_size))
        return ([{"name": f"tool-{page}", "title": f"Tool {page}"}], page <= 3)

    sleeps = []
    monkeypatch.setattr(catalog_sync, "listing_page", fake_page)

    summary = catalog_sync.run(pages_per_run=3, min_interval_seconds=3, sleep_fn=sleeps.append)

    assert summary == {"pages": 3, "records": 3, "next_page": 4, "completed": False}
    assert calls == [(1, 100), (2, 100), (3, 100)]
    assert sleeps == [3, 3]
    with db.session_scope() as s:
        assert s.query(CanonicalToolCache).count() == 3
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state is not None
        assert state.next_page == 4
        assert state.status == "idle"
        assert state.cycles_completed == 0


def test_run_wraps_cursor_after_last_page(monkeypatch):
    monkeypatch.setattr(catalog_sync, "listing_page", lambda *_args: ([{"name": "last"}], False))

    summary = catalog_sync.run(pages_per_run=1, sleep_fn=lambda _seconds: None)

    assert summary["completed"] is True
    assert summary["next_page"] == 1
    with db.session_scope() as s:
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state is not None
        assert state.cycles_completed == 1
        assert state.last_completed_at is not None


def test_run_preserves_cursor_and_records_error(monkeypatch):
    monkeypatch.setattr(
        catalog_sync,
        "listing_page",
        lambda *_args: (_ for _ in ()).throw(toolhub.ToolhubAPIError(503, {"detail": "busy"})),
    )

    with pytest.raises(toolhub.ToolhubAPIError):
        catalog_sync.run(pages_per_run=1)

    with db.session_scope() as s:
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state is not None
        assert state.next_page == 1
        assert state.status == "error"
        assert state.last_error == "Toolhub API returned 503"


def test_limits_cannot_reduce_the_healthy_request_interval():
    assert catalog_sync._bounded_pages(999) == catalog_sync.MAX_PAGES_PER_RUN
    assert catalog_sync._bounded_page_size(999) == catalog_sync.MAX_PAGE_SIZE
    assert catalog_sync._bounded_interval(0) == catalog_sync.DEFAULT_MIN_INTERVAL_SECONDS
