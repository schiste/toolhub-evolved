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


def account(
    uid: str,
    uid_number: str,
    *,
    developer_username: str = "",
    global_id: str = "",
    tools: tuple[str, ...] = (),
    ssh_keys: tuple[str, ...] = (),
) -> dict:
    return {
        "uid": [uid],
        "uidNumber": [uid_number],
        "cn": [developer_username or uid.title()],
        "createTimestamp": ["20130729163514Z"],
        "wikimediaGlobalAccountId": [global_id] if global_id else [],
        "wikimediaGlobalAccountName": [uid.title()] if global_id else [],
        "sshPublicKey": list(ssh_keys),
        "memberOf": [f"cn=tools.{tool},ou=servicegroups,dc=wikimedia,dc=org" for tool in tools],
        "pwdPolicySubentry": [],
    }


def test_sync_projects_bound_and_unbound_accounts_and_memberships():
    result = toolforge_account_sync.run(
        loader=lambda: [
            account("magnus", "3067", global_id="160", tools=("mix-n-match", "magnustools")),
            account("legacy", "9001", tools=("old-tool",), ssh_keys=("ssh-ed25519 AAAA",)),
        ]
    )

    assert result == {"status": "idle", "generation": 1, "accounts": 2, "memberships": 3}
    with db.session_scope() as session:
        magnus = session.get(ToolforgeAccountProjection, "3067")
        assert magnus is not None
        assert magnus.uid == "magnus"
        assert magnus.developer_username == "Magnus"
        assert magnus.normalized_developer_username == "magnus"
        assert magnus.ldap_created_at == "20130729163514Z"
        assert magnus.wikimedia_global_user_id == "160"
        legacy = session.get(ToolforgeAccountProjection, "9001")
        assert legacy is not None
        assert legacy.wikimedia_global_user_id is None
        assert legacy.ssh_key_count == 1
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
    toolforge_account_sync.run(
        loader=lambda: [
            account(
                "old-shell",
                "1",
                developer_username="OldDeveloper",
                global_id="10",
                tools=("one", "removed"),
            )
        ]
    )
    result = toolforge_account_sync.run(
        loader=lambda: [
            account(
                "new-shell",
                "1",
                developer_username="NewDeveloper",
                global_id="10",
                tools=("one", "added"),
            )
        ]
    )

    assert result["generation"] == 2
    with db.session_scope() as session:
        projected = session.get(ToolforgeAccountProjection, "1")
        assert projected.uid == "new-shell"
        assert projected.developer_username == "NewDeveloper"
        assert {row.tool_name for row in session.query(ToolforgeMembershipProjection)} == {"one", "added"}


def test_missing_developer_account_name_rejects_generation():
    row = account("shell", "1")
    row["cn"] = []

    with pytest.raises(toolforge_account_sync.ToolforgeAccountSyncError, match="developer account name"):
        toolforge_account_sync.run(loader=lambda: [row])


def test_duplicate_uid_number_rejects_the_generation():
    with pytest.raises(toolforge_account_sync.ToolforgeAccountSyncError, match="duplicate"):
        toolforge_account_sync.run(loader=lambda: [account("one", "1"), account("two", "1")])


def group(name: str, *members: str) -> dict:
    return {
        "cn": [f"tools.{name}"],
        "member": [f"uid={member},ou=people,dc=wikimedia,dc=org" for member in members],
    }


def test_tool_group_members_recover_the_memberships_memberof_omits():
    groups = [
        group("magnustools", "magnus"),
        group("mix-n-match", "magnus", "other"),
    ]

    member_dns = toolforge_account_sync.tool_group_member_dns(groups)

    assert member_dns == {
        "magnus": [
            "cn=tools.magnustools,ou=servicegroups,dc=wikimedia,dc=org",
            "cn=tools.mix-n-match,ou=servicegroups,dc=wikimedia,dc=org",
        ],
        "other": ["cn=tools.mix-n-match,ou=servicegroups,dc=wikimedia,dc=org"],
    }


def test_tool_group_members_ignore_service_accounts_and_unnamed_groups():
    groups = [
        {
            "cn": ["tools.magnustools"],
            "member": [
                "uid=tools.magnustools,ou=people,ou=servicegroups,dc=wikimedia,dc=org",
                "uid=magnus,ou=people,dc=wikimedia,dc=org",
            ],
        },
        {"cn": ["project-tools"], "member": ["uid=magnus,ou=people,dc=wikimedia,dc=org"]},
        {"cn": ["tools."], "member": ["uid=magnus,ou=people,dc=wikimedia,dc=org"]},
    ]

    assert toolforge_account_sync.tool_group_member_dns(groups) == {
        "magnus": ["cn=tools.magnustools,ou=servicegroups,dc=wikimedia,dc=org"]
    }


def test_group_membership_projects_a_tool_absent_from_memberof():
    rows = toolforge_account_sync.with_group_memberships(
        [account("magnus", "3067", tools=("mix-n-match",)), account("unrelated", "9001")],
        toolforge_account_sync.tool_group_member_dns([group("magnustools", "Magnus"), group("mix-n-match", "magnus")]),
    )

    toolforge_account_sync.run(loader=lambda: rows)

    with db.session_scope() as session:
        assert {(row.uid_number, row.tool_name) for row in session.query(ToolforgeMembershipProjection)} == {
            ("3067", "magnustools"),
            ("3067", "mix-n-match"),
        }


def test_projection_refresh_joins_toolforge_before_people_reconciliation():
    jobs = (ROOT / "jobs.yaml").read_text(encoding="utf-8")
    deploy = (ROOT / "tools" / "deploy.sh").read_text(encoding="utf-8")
    refresh = (ROOT / "proxy" / "projection_refresh.py").read_text(encoding="utf-8")

    assert "name: projection-refresh" in jobs
    assert "toolforge_account_sync.run" in refresh
    assert refresh.index('report["failurePhase"] = "parallel-sync"') < refresh.index(
        'report["failurePhase"] = "identity-publication"'
    )
    assert "toolforge_account_sync.py" not in deploy
