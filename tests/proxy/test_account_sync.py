# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the resumable official Toolhub account projection."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import account_sync  # noqa: E402
from backend import account_directory, db, toolhub  # noqa: E402
from backend.models import Person, PersonIdentifier, ToolhubAccountProjection, ToolhubAccountSyncState  # noqa: E402


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
        assert s.query(Person).count() == 2
        first_person = (
            s.query(Person)
            .join(PersonIdentifier, PersonIdentifier.person_id == Person.id)
            .filter_by(namespace="toolhub_user_id", value="1")
            .one()
        )
        assert first_person.display_name == "Long Account Name"
        assert first_person.identity_quality == "stable"
        assert {
            (row.namespace, row.value)
            for row in s.query(PersonIdentifier).filter_by(person_id=first_person.id, is_current=True)
        } == {
            ("toolhub_user_id", "1"),
            ("toolhub_username", "Long Account Name"),
            ("wikimedia_global_user_id", "100001"),
        }
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
        renamed_person = (
            s.query(Person)
            .join(PersonIdentifier, PersonIdentifier.person_id == Person.id)
            .filter_by(namespace="toolhub_user_id", value="1")
            .one()
        )
        assert renamed_person.display_name == "Renamed"
        assert {
            (row.value, row.is_current)
            for row in s.query(PersonIdentifier)
            .filter_by(person_id=renamed_person.id, namespace="toolhub_username")
            .order_by(PersonIdentifier.id)
        } == {("Account 1", False), ("Renamed", True)}
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


def test_unchanged_generation_does_not_rewrite_identity_rows(monkeypatch):
    monkeypatch.setattr(
        account_sync,
        "listing_page",
        lambda _page, _size: ([account("42", "Stable Account")], False, 1),
    )
    account_sync.run_complete(sleep_fn=lambda _seconds: None)
    with db.session_scope() as session:
        person = session.query(Person).one()
        identifier = session.query(PersonIdentifier).filter_by(namespace="toolhub_user_id").one()
        person_updated_at = person.updated_at
        identifier_updated_at = identifier.updated_at

    account_sync.run_complete(sleep_fn=lambda _seconds: None)

    with db.session_scope() as session:
        assert session.query(Person).one().updated_at == person_updated_at
        assert (
            session.query(PersonIdentifier).filter_by(namespace="toolhub_user_id").one().updated_at
            == identifier_updated_at
        )


def test_projection_refresh_owns_complete_account_generation_outside_deploy():
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")
    refresh = (ROOT / "proxy" / "projection_refresh.py").read_text(encoding="utf-8")

    assert "name: projection-refresh" in jobs
    assert "account_sync.run_complete" in refresh
    assert "toolforge jobs run --wait 900" in deploy
    assert 'run_with_tool_env account-sync "$REPO_DIR/proxy/account_sync.py --complete"' not in deploy
    assert "projection-refresh-deploy" in deploy
    assert "webservice python3.13 shell" not in deploy
    assert (
        'exec env TOOLHUB_DEPLOY_REEXECUTED=1 TOOLHUB_DEPLOY_HEAD_BEFORE="$deploy_head_before" '
        'sh "$REPO_DIR/tools/deploy.sh"'
    ) in deploy


def test_sync_payload_reports_unavailable_before_any_sync_state_exists():
    payload = account_directory._sync_payload(None)
    assert payload == {
        "status": "unavailable",
        "complete": False,
        "lastCompletedAt": "",
        "lastSuccessAt": "",
        "error": "Account projection has not been synchronized yet.",
    }


def test_complete_cli_fails_when_another_worker_holds_the_sync_lock(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/accounts.sqlite3")
    monkeypatch.setattr(
        account_sync,
        "run_complete",
        lambda **_kwargs: {"status": "locked", "pages": 0, "records": 0, "completed": False},
    )

    assert account_sync.main(["--complete", "--min-interval", "1"]) == 1
    output = capsys.readouterr()
    assert "status=locked" in output.out
    assert "complete generation was not obtained" in output.err
