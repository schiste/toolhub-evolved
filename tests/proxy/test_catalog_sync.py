"""Tests for the paced, resumable official catalog synchronization worker."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db, toolhub  # noqa: E402
from backend.models import CanonicalToolCache, PersonReconciliationQueue, ToolCatalogSyncState  # noqa: E402
import catalog_sync  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def test_listing_page_validates_paginated_and_list_payloads(monkeypatch):
    payloads = iter(
        [
            {"count": 2, "results": [{"name": "first"}], "next": "https://toolhub.example/api/tools/?page=2"},
            [{"name": "last"}, "invalid"],
        ]
    )
    calls = []

    def get(*args, **kwargs):
        calls.append((args, kwargs))
        return next(payloads)

    monkeypatch.setattr(toolhub, "public_api_get", get)

    assert catalog_sync.listing_page(1, 100) == ([{"name": "first"}], True, 2)
    assert catalog_sync.listing_page(2, 100) == ([{"name": "last"}], False, 1)
    assert [kwargs["read_cache"] for _args, kwargs in calls] == [False, False]


@pytest.mark.parametrize("count", [None, "invalid", 0, -1])
def test_listing_page_rejects_an_unusable_snapshot_count(monkeypatch, count):
    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda *_args, **_kwargs: {"count": count, "results": [], "next": None},
    )

    with pytest.raises(catalog_sync.CatalogSyncError, match="valid count"):
        catalog_sync.listing_page(1, 100)


def test_run_upserts_pages_tracks_cursor_and_paces_requests(monkeypatch):
    calls = []

    def fake_page(page, page_size):
        calls.append((page, page_size))
        return ([{"name": f"tool-{page}", "title": f"Tool {page}"}], page <= 3, 4)

    sleeps = []
    monkeypatch.setattr(catalog_sync, "listing_page", fake_page)

    summary = catalog_sync.run(pages_per_run=3, min_interval_seconds=3, sleep_fn=sleeps.append)

    assert summary == {"phase": "backfill", "pages": 3, "records": 3, "next_page": 4, "completed": False}
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
    monkeypatch.setattr(catalog_sync, "listing_page", lambda *_args: ([{"name": "last"}], False, 1))

    summary = catalog_sync.run(pages_per_run=1, sleep_fn=lambda _seconds: None)

    assert summary["completed"] is True
    assert summary["next_page"] == 1
    with db.session_scope() as s:
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state is not None
        assert state.cycles_completed == 1
        assert state.last_completed_at is not None


def test_complete_snapshot_prunes_only_names_absent_from_every_official_page(monkeypatch):
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="retired-tool",
                record={"name": "retired-tool", "title": "Retired"},
                source_url="https://toolhub.example/api/tools/?page=1",
                expires_at=catalog_sync.utcnow(),
                stale_until=catalog_sync.utcnow(),
            )
        )

    pages = {
        1: ([{"name": "active-one", "title": "One"}], True, 2),
        2: ([{"name": "active-two", "title": "Two"}], False, 2),
    }
    monkeypatch.setattr(catalog_sync, "listing_page", lambda page, _page_size: pages[page])

    summary = catalog_sync.run_complete(sleep_fn=lambda _seconds: None)

    assert summary == {
        "phase": "complete",
        "pages": 2,
        "records": 2,
        "retired": 1,
        "generation": 1,
        "completed": True,
    }
    with db.session_scope() as s:
        assert {row.tool_name for row in s.query(CanonicalToolCache)} == {"active-one", "active-two"}
        assert {row.generation for row in s.query(CanonicalToolCache)} == {1}
        assert s.get(PersonReconciliationQueue, "retired-tool").reason == "canonical_retired"


def test_deploy_reuses_a_recent_completed_snapshot(monkeypatch):
    with db.session_scope() as s:
        s.add(
            ToolCatalogSyncState(
                key=catalog_sync.STATE_KEY,
                snapshot_generation=7,
                last_completed_at=catalog_sync.utcnow(),
            )
        )
    monkeypatch.setattr(
        catalog_sync,
        "listing_page",
        lambda *_args: pytest.fail("a fresh deployment snapshot should be reused"),
    )

    summary = catalog_sync.run_complete(max_age_seconds=21600)

    assert summary == {
        "phase": "complete_cached",
        "pages": 0,
        "records": 0,
        "retired": 0,
        "generation": 7,
        "completed": True,
    }


def test_interrupted_complete_snapshot_preserves_last_known_good_catalog(monkeypatch):
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="keep-until-complete",
                record={"name": "keep-until-complete", "title": "Keep"},
                source_url="https://toolhub.example/api/tools/?page=1",
                expires_at=catalog_sync.utcnow(),
                stale_until=catalog_sync.utcnow(),
            )
        )

    def page(number, _page_size):
        if number == 1:
            return ([{"name": "new-tool", "title": "New"}], True, 2)
        raise toolhub.ToolhubAPIError(503, {"detail": "busy"})

    monkeypatch.setattr(catalog_sync, "listing_page", page)

    with pytest.raises(toolhub.ToolhubAPIError):
        catalog_sync.run_complete(sleep_fn=lambda _seconds: None)

    with db.session_scope() as s:
        assert s.get(CanonicalToolCache, "keep-until-complete") is not None
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state.snapshot_next_page == 2
        assert state.snapshot_started_at is not None
        assert state.status == "error"


def test_changed_count_restarts_snapshot_without_pruning(monkeypatch):
    with db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="last-known-good",
                record={"name": "last-known-good"},
                source_url="https://toolhub.example/api/tools/?page=1",
                expires_at=catalog_sync.utcnow(),
                stale_until=catalog_sync.utcnow(),
            )
        )

    pages = {
        1: ([{"name": "new-one"}], True, 2),
        2: ([{"name": "new-two"}], False, 3),
    }
    monkeypatch.setattr(catalog_sync, "listing_page", lambda page, _page_size: pages[page])

    with pytest.raises(catalog_sync.SnapshotConsistencyError, match="count changed"):
        catalog_sync.run_complete(sleep_fn=lambda _seconds: None)

    with db.session_scope() as s:
        assert s.get(CanonicalToolCache, "last-known-good") is not None
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state.snapshot_next_page == 1
        assert state.snapshot_expected_count == 0
        assert state.snapshot_started_at is None
        assert state.status == "error"


def test_steady_state_ingests_recent_tools_and_reconciles_slowly(monkeypatch):
    with db.session_scope() as s:
        s.add(
            ToolCatalogSyncState(
                key=catalog_sync.STATE_KEY,
                cycles_completed=1,
                recent_latest_marker=catalog_sync._marker({"id": 1, "timestamp": "old"}),
            )
        )

    monkeypatch.setattr(
        catalog_sync,
        "recent_page",
        lambda: [
            {"id": 2, "timestamp": "new", "content_type": "tool", "content_id": "changed-tool"},
            {"id": 1, "timestamp": "old", "content_type": "tool", "content_id": "old-tool"},
        ],
    )
    monkeypatch.setattr(
        catalog_sync,
        "listing_page",
        lambda _page, _page_size: ([{"name": "reconcile-tool", "title": "Reconcile"}], True, 2),
    )
    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda path, **_kwargs: {"name": "changed-tool", "title": "Changed"}
        if path.endswith("/changed-tool/")
        else pytest.fail(path),
    )
    sleeps = []

    summary = catalog_sync.run(min_interval_seconds=3, sleep_fn=sleeps.append)

    assert summary["phase"] == "steady"
    assert summary["recent_tools"] == 1
    assert summary["recent_errors"] == 0
    assert summary["hydrated_tools"] == 0
    assert summary["hydration_errors"] == 0
    assert summary["reconcile_pages"] == 1
    assert summary["reconcile_records"] == 1
    assert sleeps == []
    with db.session_scope() as s:
        assert s.get(CanonicalToolCache, "changed-tool") is not None
        assert s.get(CanonicalToolCache, "reconcile-tool") is not None
        state = s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY)
        assert state is not None
        assert state.recent_pending_tools == []
        assert state.reconcile_next_page == 2


def test_steady_state_defers_reconciliation_until_interval(monkeypatch):
    with db.session_scope() as s:
        s.add(
            ToolCatalogSyncState(
                key=catalog_sync.STATE_KEY,
                cycles_completed=1,
                reconcile_last_at=catalog_sync.utcnow(),
            )
        )
    monkeypatch.setattr(catalog_sync, "recent_page", lambda: [])
    monkeypatch.setattr(catalog_sync, "listing_page", lambda *_args: pytest.fail("reconcile is not due"))

    summary = catalog_sync.run(sleep_fn=lambda _seconds: None)

    assert summary["reconcile_pages"] == 0


def test_steady_state_hydrates_graph_candidates_with_persistent_cursor(monkeypatch):
    with db.session_scope() as s:
        s.add(ToolCatalogSyncState(key=catalog_sync.STATE_KEY, cycles_completed=1))
        s.add_all(
            [
                CanonicalToolCache(
                    tool_name=name,
                    record={"name": name, "title": name, "keywords": ["graph"]},
                    source_url="https://toolhub.wikimedia.org/api/tools/?page=1",
                    expires_at=catalog_sync.utcnow(),
                    stale_until=catalog_sync.utcnow(),
                )
                for name in ("alpha", "beta")
            ]
        )
    monkeypatch.setattr(catalog_sync, "recent_page", lambda: [])
    monkeypatch.setattr(
        catalog_sync, "_reconcile_if_due", lambda _page_size: {"reconcile_pages": 0, "reconcile_records": 0}
    )
    monkeypatch.setattr(
        toolhub,
        "public_api_get",
        lambda path, **_kwargs: {
            "name": path.rstrip("/").rsplit("/", 1)[-1],
            "title": "Hydrated",
            "keywords": ["graph"],
            "tasks": ["Explore"],
        },
    )
    sleeps = []

    summary = catalog_sync.run(min_interval_seconds=3, sleep_fn=sleeps.append)

    assert summary["hydrated_tools"] == 2
    assert summary["hydration_errors"] == 0
    assert sleeps == [3]
    with db.session_scope() as s:
        assert s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY).detail_hydration_cursor == "beta"
        assert s.get(CanonicalToolCache, "alpha").record["tasks"] == ["Explore"]


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


def test_graph_hydration_retries_failures_before_advancing_the_rotation(monkeypatch):
    with db.session_scope() as s:
        s.add(ToolCatalogSyncState(key=catalog_sync.STATE_KEY, cycles_completed=1))
        s.add(
            CanonicalToolCache(
                tool_name="retry-me",
                record={"name": "retry-me", "title": "Retry", "keywords": ["graph"]},
                source_url="https://toolhub.wikimedia.org/api/tools/?page=1",
                expires_at=catalog_sync.utcnow(),
                stale_until=catalog_sync.utcnow(),
            )
        )
    monkeypatch.setattr(catalog_sync, "recent_page", lambda: [])
    monkeypatch.setattr(
        catalog_sync, "_reconcile_if_due", lambda _page_size: {"reconcile_pages": 0, "reconcile_records": 0}
    )
    calls = 0

    def detail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise toolhub.ToolhubAPIError(503, {"detail": "busy"})
        return {"name": "retry-me", "title": "Retry", "keywords": ["graph"], "for_wikis": ["wikidatawiki"]}

    monkeypatch.setattr(toolhub, "public_api_get", detail)

    first = catalog_sync.run(sleep_fn=lambda _seconds: None)
    with db.session_scope() as s:
        assert s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY).detail_hydration_pending_tools == ["retry-me"]
    second = catalog_sync.run(sleep_fn=lambda _seconds: None)

    assert first["hydration_errors"] == 1
    assert second["hydrated_tools"] == 1
    with db.session_scope() as s:
        assert s.get(ToolCatalogSyncState, catalog_sync.STATE_KEY).detail_hydration_pending_tools == []


def test_limits_cannot_reduce_the_healthy_request_interval():
    assert catalog_sync._bounded_pages(999) == catalog_sync.MAX_PAGES_PER_RUN
    assert catalog_sync._bounded_page_size(999) == catalog_sync.MAX_PAGE_SIZE
    assert catalog_sync._bounded_interval(0) == catalog_sync.DEFAULT_MIN_INTERVAL_SECONDS


def test_graph_hydration_fits_toolforge_job_timeout():
    request_wait_seconds = (
        catalog_sync.MAX_RECENT_DETAILS_PER_RUN + catalog_sync.MAX_GRAPH_DETAILS_PER_RUN - 2
    ) * catalog_sync.DEFAULT_MIN_INTERVAL_SECONDS

    assert catalog_sync.MAX_GRAPH_DETAILS_PER_RUN == 20
    assert request_wait_seconds < 300
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    assert "name: catalog-sync" in jobs
    assert "timeout: 300" in jobs
