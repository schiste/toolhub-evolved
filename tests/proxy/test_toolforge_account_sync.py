# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the authoritative Toolforge account and membership projection."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import toolforge_account_sync  # noqa: E402
from backend import db  # noqa: E402
from backend.models import (  # noqa: E402
    ToolforgeAccountProjection,
    ToolforgeAccountSyncState,
    ToolforgeMembershipProjection,
)


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def account(uid: str, uid_number: str, *, global_id: str = "", tools: tuple[str, ...] = ()) -> dict:
    return {
        "uid": [uid],
        "uidNumber": [uid_number],
        "wikimediaGlobalAccountId": [global_id] if global_id else [],
        "wikimediaGlobalAccountName": [uid.title()] if global_id else [],
        "memberOf": [f"cn=tools.{tool},ou=servicegroups,dc=wikimedia,dc=org" for tool in tools],
        "pwdPolicySubentry": [],
    }


def test_sync_projects_bound_and_unbound_accounts_and_memberships():
    result = toolforge_account_sync.run(
        loader=lambda: [
            account("magnus", "3067", global_id="160", tools=("mix-n-match", "magnustools")),
            account("legacy", "9001", tools=("old-tool",)),
        ]
    )

    assert result == {"status": "idle", "generation": 1, "accounts": 2, "memberships": 3}
    with db.session_scope() as session:
        magnus = session.get(ToolforgeAccountProjection, "3067")
        assert magnus is not None
        assert magnus.uid == "magnus"
        assert magnus.wikimedia_global_user_id == "160"
        legacy = session.get(ToolforgeAccountProjection, "9001")
        assert legacy is not None
        assert legacy.wikimedia_global_user_id is None
        assert {(row.uid_number, row.tool_name) for row in session.query(ToolforgeMembershipProjection)} == {
            ("3067", "magnustools"),
            ("3067", "mix-n-match"),
            ("9001", "old-tool"),
        }


def test_failed_cycle_preserves_last_complete_generation():
    toolforge_account_sync.run(loader=lambda: [account("first", "1", tools=("one",))])

    with pytest.raises(toolforge_account_sync.ToolforgeAccountSyncError):
        toolforge_account_sync.run(loader=lambda: [account("broken", "", tools=("two",))])

    with db.session_scope() as session:
        assert {row.uid_number for row in session.query(ToolforgeAccountProjection)} == {"1"}
        assert {(row.uid_number, row.tool_name) for row in session.query(ToolforgeMembershipProjection)} == {
            ("1", "one")
        }
        state = session.get(ToolforgeAccountSyncState, toolforge_account_sync.STATE_KEY)
        assert state is not None
        assert state.status == "error"
        assert state.cycles_completed == 1


def test_successful_next_generation_prunes_removed_rows_and_tracks_renames():
    toolforge_account_sync.run(loader=lambda: [account("old-name", "1", global_id="10", tools=("one", "removed"))])
    result = toolforge_account_sync.run(
        loader=lambda: [account("new-name", "1", global_id="10", tools=("one", "added"))]
    )

    assert result["generation"] == 2
    with db.session_scope() as session:
        assert session.get(ToolforgeAccountProjection, "1").uid == "new-name"
        assert {row.tool_name for row in session.query(ToolforgeMembershipProjection)} == {"one", "added"}


def test_duplicate_uid_number_rejects_the_generation():
    with pytest.raises(toolforge_account_sync.ToolforgeAccountSyncError, match="duplicate"):
        toolforge_account_sync.run(loader=lambda: [account("one", "1"), account("two", "1")])


def test_deploy_and_schedule_refresh_toolforge_before_people_reconciliation():
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")

    assert "name: toolforge-account-sync" in jobs
    assert "proxy/toolforge_account_sync.py" in jobs
    assert deploy.index("toolforge_account_sync.py") < deploy.index("public_identity_smoke.py")
