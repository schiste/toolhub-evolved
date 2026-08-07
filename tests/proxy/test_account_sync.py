# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the resumable official Toolhub account projection."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import account_sync  # noqa: E402
from backend import db, toolhub  # noqa: E402
from backend.models import ToolhubAccountProjection, ToolhubAccountSyncState  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def account(ident, username=None, *, groups=None):
    return {
        "id": ident,
        "username": username or f"Account {ident}",
        "groups": groups or [],
        "date_joined": "2026-08-01T12:00:00Z",
        "social_auth": [
            {
                "provider": "wikimedia",
                "uid": str(100_000 + int(ident)),
                "registered": "20200102030405",
            }
        ],
    }


def test_listing_page_requests_stable_id_order_and_validates_shape(monkeypatch):
    calls = []

    def get(path, *, params):
        calls.append((path, params))
        return {"count": 1, "next": None, "results": [account(1)]}

    monkeypatch.setattr(toolhub, "public_api_get", get)

    rows, has_next, total = account_sync.listing_page(1, 100)

    assert rows[0]["id"] == 1
    assert has_next is False
    assert total == 1
    assert calls == [("/api/users/", {"ordering": "id", "page": 1, "page_size": 100})]
    for payload in (None, [], {}, {"count": "bad", "results": []}, {"count": 1, "results": [None]}):
        monkeypatch.setattr(toolhub, "public_api_get", lambda *_args, value=payload, **_kwargs: value)
        with pytest.raises(account_sync.AccountSyncError):
            account_sync.listing_page(1, 100)


def test_sync_resumes_pages_and_materializes_official_identity_fields(monkeypatch):
    calls = []

    def page(number, size):
        calls.append((number, size))
        if number == 1:
            return [account(1, "Long Account Name", groups=["bots", "admin"])], True, 2
        return [account(2)], False, 2

    monkeypatch.setattr(account_sync, "listing_page", page)

    first = account_sync.run(pages_per_run=1, sleep_fn=lambda _seconds: None)
    second = account_sync.run(pages_per_run=1, sleep_fn=lambda _seconds: None)

    assert first["completed"] is False
    assert first["next_page"] == 2
    assert second["completed"] is True
    assert calls == [(1, 100), (2, 100)]
    with db.session_scope() as s:
        rows = s.query(ToolhubAccountProjection).order_by(ToolhubAccountProjection.toolhub_user_id).all()
        assert len(rows) == 2
        assert rows[0].username == "Long Account Name"
        assert rows[0].normalized_username == "long account name"
        assert rows[0].groups == ["admin", "bots"]
        assert rows[0].groups_search == "\nadmin\nbots\n"
        assert rows[0].wikimedia_global_user_id == "100001"
        assert rows[0].wikimedia_registered_at == "20200102030405"
        assert rows[0].date_joined is not None
        state = s.get(ToolhubAccountSyncState, account_sync.STATE_KEY)
        assert state.cycles_completed == 1
        assert state.cycle_started_at is None
        assert state.next_page == 1


def test_interrupted_generation_preserves_old_rows_until_retry_completes(monkeypatch):
    monkeypatch.setattr(
        account_sync,
        "listing_page",
        lambda page, _size: ([account(page)], page == 1, 2),
    )
    account_sync.run_complete(page_size=1, sleep_fn=lambda _seconds: None)

    calls = 0

    def interrupted(page, _size):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise toolhub.ToolhubAPIError(503, {"detail": "busy"})
        return ([account(1, "Renamed")], True, 2) if page == 1 else ([account(3)], False, 2)

    monkeypatch.setattr(account_sync, "listing_page", interrupted)
    with pytest.raises(toolhub.ToolhubAPIError):
        account_sync.run(pages_per_run=2, page_size=1, sleep_fn=lambda _seconds: None)

    with db.session_scope() as s:
        assert {row.toolhub_user_id for row in s.query(ToolhubAccountProjection)} == {"1", "2"}
        assert s.get(ToolhubAccountProjection, "1").username == "Renamed"
        state = s.get(ToolhubAccountSyncState, account_sync.STATE_KEY)
        assert state.next_page == 2
        assert state.status == "error"

    recovered = account_sync.run(pages_per_run=1, page_size=1, sleep_fn=lambda _seconds: None)

    assert recovered["completed"] is True
    with db.session_scope() as s:
        assert {row.toolhub_user_id for row in s.query(ToolhubAccountProjection)} == {"1", "3"}


def test_count_mismatch_restarts_without_pruning_last_complete_generation(monkeypatch):
    monkeypatch.setattr(account_sync, "listing_page", lambda *_args: ([account(1), account(2)], False, 2))
    account_sync.run_complete(sleep_fn=lambda _seconds: None)
    monkeypatch.setattr(account_sync, "listing_page", lambda *_args: ([account(1, "Updated")], False, 2))

    with pytest.raises(account_sync.AccountSyncError, match="restarting without pruning"):
        account_sync.run_complete(sleep_fn=lambda _seconds: None)

    with db.session_scope() as s:
        assert {row.toolhub_user_id for row in s.query(ToolhubAccountProjection)} == {"1", "2"}
        state = s.get(ToolhubAccountSyncState, account_sync.STATE_KEY)
        assert state.next_page == 1
        assert state.cycle_started_at is None
        assert state.status == "error"


def test_complete_sync_handles_more_than_two_thousand_accounts(monkeypatch):
    total = 2_313

    def page(number, size):
        start = (number - 1) * size + 1
        stop = min(total + 1, start + size)
        return [account(index) for index in range(start, stop)], stop <= total, total

    monkeypatch.setattr(account_sync, "listing_page", page)

    summary = account_sync.run_complete(page_size=100, sleep_fn=lambda _seconds: None)

    assert summary["completed"] is True
    assert summary["pages"] == 24
    assert summary["records"] == total
    with db.session_scope() as s:
        assert s.query(ToolhubAccountProjection).count() == total


def test_sync_limits_keep_requests_bounded_and_paced():
    assert account_sync._bounded_pages(999) == account_sync.MAX_PAGES_PER_RUN
    assert account_sync._bounded_page_size(999) == account_sync.MAX_PAGE_SIZE
    assert account_sync._bounded_interval(0) == account_sync.DEFAULT_MIN_INTERVAL_SECONDS
