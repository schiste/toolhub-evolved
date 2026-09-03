# SPDX-License-Identifier: GPL-3.0-or-later
"""Safely mirror Toolforge developer accounts and tool memberships from LDAP."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select

from backend import DEFAULT_DB_URL, db, public_identity
from backend.models import (
    ToolforgeAccountProjection,
    ToolforgeAccountSyncState,
    ToolforgeMembershipProjection,
    utcnow,
)
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL, clean_error

STATE_KEY = "toolforge_accounts"
LOCK_NAME = "toolhub-evolved-toolforge-account-sync"
TOOLFORGE_MEMBER_FILTER = "(&(objectClass=posixAccount)(memberOf=cn=project-tools,ou=groups,dc=wikimedia,dc=org))"
LDAP_ATTRIBUTES = [
    "uid",
    "uidNumber",
    "cn",
    "createTimestamp",
    "wikimediaGlobalAccountId",
    "wikimediaGlobalAccountName",
    "sshPublicKey",
    "memberOf",
    "pwdPolicySubentry",
]
TOOLFORGE_GROUP_BASE_DN = "ou=servicegroups,dc=wikimedia,dc=org"
TOOLFORGE_GROUP_FILTER = "(&(objectClass=groupOfNames)(cn=tools.*))"
GROUP_ATTRIBUTES = ["cn", "member"]
GROUP_PREFIX = "tools."
# Only people carry tool memberships; a group may also list a tool's own service
# account (uid=tools.<name>,ou=people,ou=servicegroups,...), which is not a person.
PERSON_MEMBER_DN = re.compile(r"^uid=([^,]+),ou=people,dc=wikimedia,dc=org$", re.IGNORECASE)
LDAP_PAGE_SIZE = 500
LDAP_PAGE_TIME_LIMIT = 120
DISABLED_POLICY = "cn=disabled,ou=ppolicies,dc=wikimedia,dc=org"
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"

LdapLoader = Callable[[], Iterable[Mapping[str, Any]]]


class ToolforgeAccountSyncError(RuntimeError):
    """Raised when an LDAP generation cannot be validated safely."""


def _sync_error(message: str) -> ToolforgeAccountSyncError:
    return ToolforgeAccountSyncError(message)


def _invalid_account_error() -> ToolforgeAccountSyncError:
    return _sync_error("Toolforge LDAP row lacked uid, uidNumber, or developer account name (cn)")


def _ldap_unavailable_error() -> ToolforgeAccountSyncError:
    return _sync_error("ldap3 is unavailable")


def _empty_generation_error() -> ToolforgeAccountSyncError:
    return _sync_error("Toolforge LDAP returned no project members")


def _generation_changed_error() -> ToolforgeAccountSyncError:
    return _sync_error("Toolforge sync generation changed during the run")


def _duplicate_uid_error(uid_number: str) -> ToolforgeAccountSyncError:
    return _sync_error(f"duplicate Toolforge uidNumber {uid_number}")


def _first(value: Any) -> str:  # noqa: ANN401 - LDAP values may be scalar or list-like
    if isinstance(value, (list, tuple)):
        return str(value[0]).strip() if value else ""
    return str(value or "").strip()


def _values(value: Any) -> list[str]:  # noqa: ANN401 - LDAP values may be scalar or list-like
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    clean = str(value or "").strip()
    return [clean] if clean else []


def _normalized(row: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    uid = _first(row.get("uid"))[:255]
    uid_number = _first(row.get("uidNumber"))[:64]
    developer_username = _first(row.get("cn"))[:255]
    if not uid or not uid_number or not developer_username:
        raise _invalid_account_error()
    memberships = sorted(set(public_identity.tool_names_from_member_dns(_values(row.get("memberOf")))))
    policies = {value.casefold() for value in _values(row.get("pwdPolicySubentry"))}
    return (
        {
            "uid_number": uid_number,
            "uid": uid,
            "normalized_uid": uid.casefold(),
            "developer_username": developer_username,
            "normalized_developer_username": developer_username.casefold(),
            "wikimedia_global_user_id": _first(row.get("wikimediaGlobalAccountId"))[:64] or None,
            "wikimedia_global_name": _first(row.get("wikimediaGlobalAccountName"))[:255],
            "ldap_created_at": _first(row.get("createTimestamp"))[:32],
            "ssh_key_count": len(_values(row.get("sshPublicKey"))),
            "disabled": DISABLED_POLICY.casefold() in policies,
        },
        memberships,
    )


def tool_group_member_dns(groups: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Map each person's uid to the tool group DNs naming them as a member.

    A tool group's ``member`` attribute is the authoritative record of who
    maintains that tool. The reverse ``memberOf`` index is maintained by an
    LDAP overlay that never backfilled the groups created before it existed,
    so reading only ``memberOf`` loses those memberships entirely.
    """
    by_uid: dict[str, list[str]] = {}
    for group in groups:
        cn = _first(group.get("cn"))
        if not cn.casefold().startswith(GROUP_PREFIX) or len(cn) <= len(GROUP_PREFIX):
            continue
        group_dn = f"cn={cn},{TOOLFORGE_GROUP_BASE_DN}"
        for member in _values(group.get("member")):
            match = PERSON_MEMBER_DN.match(member)
            if match:
                by_uid.setdefault(match.group(1).casefold(), []).append(group_dn)
    return by_uid


def with_group_memberships(
    rows: Iterable[Mapping[str, Any]], member_dns: Mapping[str, Sequence[str]]
) -> list[Mapping[str, Any]]:
    """Restore the tool group DNs that each account's memberOf list omits."""
    restored: list[Mapping[str, Any]] = []
    for row in rows:
        extra = member_dns.get(_first(row.get("uid")).casefold(), ())
        restored.append({**row, "memberOf": [*_values(row.get("memberOf")), *extra]} if extra else row)
    return restored


def _paged_entries(
    connection: Any,  # noqa: ANN401 - ldap3 connection
    base_dn: str,
    ldap_filter: str,
    attributes: list[str],
) -> list[Mapping[str, Any]]:
    entries = connection.extend.standard.paged_search(
        base_dn,
        ldap_filter,
        attributes=attributes,
        paged_size=LDAP_PAGE_SIZE,
        time_limit=LDAP_PAGE_TIME_LIMIT,
        generator=True,
    )
    return [
        dict(entry["attributes"])
        for entry in entries
        if entry.get("type") == "searchResEntry" and isinstance(entry.get("attributes"), Mapping)
    ]


def load_ldap_rows() -> list[Mapping[str, Any]]:
    """Read all Toolforge project members through LDAP's paged-search control."""
    if public_identity.Connection is None or public_identity.Server is None:
        raise _ldap_unavailable_error()
    server = public_identity.Server(
        public_identity.TOOLFORGE_LDAP_URI,
        use_ssl=True,
        connect_timeout=public_identity.TOOLFORGE_LDAP_TIMEOUT,
    )
    connection = public_identity.Connection(
        server,
        receive_timeout=max(30, public_identity.TOOLFORGE_LDAP_TIMEOUT),
        auto_bind=True,
        read_only=True,
    )
    try:
        rows = _paged_entries(
            connection,
            public_identity.TOOLFORGE_LDAP_BASE_DN,
            TOOLFORGE_MEMBER_FILTER,
            LDAP_ATTRIBUTES,
        )
        groups = _paged_entries(
            connection,
            TOOLFORGE_GROUP_BASE_DN,
            TOOLFORGE_GROUP_FILTER,
            GROUP_ATTRIBUTES,
        )
        return with_group_memberships(rows, tool_group_member_dns(groups))
    finally:
        connection.unbind()


def _state(session: Any) -> ToolforgeAccountSyncState:  # noqa: ANN401 - SQLAlchemy session
    state = session.get(ToolforgeAccountSyncState, STATE_KEY)
    if state is None:
        state = ToolforgeAccountSyncState(
            key=STATE_KEY,
            active_generation=0,
            cycles_completed=0,
            accounts_seen=0,
            memberships_seen=0,
            status=STATUS_IDLE,
        )
        session.add(state)
    return state


def _mark_running() -> int:
    with db.session_scope() as session:
        state = _state(session)
        state.active_generation += 1
        state.status = STATUS_RUNNING
        state.last_started_at = utcnow()
        state.last_error = None
        state.source = SOURCE_OFFICIAL
        state.sync_status = SYNC_OFFICIAL
        return state.active_generation


def _mark_error(error: BaseException) -> None:
    with db.session_scope() as session:
        state = _state(session)
        state.status = STATUS_ERROR
        state.last_error = clean_error(str(error))


def _replace_generation(  # noqa: C901 - transaction keeps validation, upsert, and pruning atomic
    rows: list[Mapping[str, Any]], generation: int
) -> dict[str, int | str]:
    normalized: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for raw in rows:
        account, memberships = _normalized(raw)
        uid_number = account["uid_number"]
        if uid_number in normalized:
            raise _duplicate_uid_error(uid_number)
        normalized[uid_number] = (account, memberships)
    if not normalized:
        raise _empty_generation_error()

    now = utcnow()
    membership_count = sum(len(memberships) for _account, memberships in normalized.values())
    with db.session_scope() as session:
        existing_accounts = {
            row.uid_number: row
            for row in session.execute(
                select(ToolforgeAccountProjection).where(
                    ToolforgeAccountProjection.uid_number.in_(set(normalized) or {""})
                )
            ).scalars()
        }
        for uid_number, (item, memberships) in normalized.items():
            account = existing_accounts.get(uid_number)
            if account is None:
                account = ToolforgeAccountProjection(uid_number=uid_number, first_seen_at=now)
                session.add(account)
            for field, value in item.items():
                if field != "uid_number":
                    setattr(account, field, value)
            account.generation = generation
            account.source = SOURCE_OFFICIAL
            account.sync_status = SYNC_OFFICIAL
            account.last_seen_at = now
            account.updated_at = now
            for tool_name in memberships:
                membership = session.get(ToolforgeMembershipProjection, (uid_number, tool_name))
                if membership is None:
                    membership = ToolforgeMembershipProjection(
                        uid_number=uid_number,
                        tool_name=tool_name,
                        first_seen_at=now,
                    )
                    session.add(membership)
                membership.generation = generation
                membership.source = SOURCE_OFFICIAL
                membership.sync_status = SYNC_OFFICIAL
                membership.last_seen_at = now
                membership.updated_at = now

        # Prune only inside this successful, fully validated transaction.
        session.execute(
            delete(ToolforgeMembershipProjection).where(ToolforgeMembershipProjection.generation != generation)
        )
        session.execute(delete(ToolforgeAccountProjection).where(ToolforgeAccountProjection.generation != generation))
        state = _state(session)
        if state.active_generation != generation or state.status != STATUS_RUNNING:
            raise _generation_changed_error()
        state.accounts_seen = len(normalized)
        state.memberships_seen = membership_count
        state.cycles_completed += 1
        state.status = STATUS_IDLE
        state.last_success_at = now
        state.last_completed_at = now
        state.last_error = None
    return {
        "status": STATUS_IDLE,
        "generation": generation,
        "accounts": len(normalized),
        "memberships": membership_count,
    }


def run(*, loader: LdapLoader | None = None) -> dict[str, int | str]:
    """Replace the projection only after one complete, valid LDAP read."""
    with db.advisory_lock(LOCK_NAME) as acquired:
        if not acquired:
            return {"status": "locked", "generation": 0, "accounts": 0, "memberships": 0}
        generation = _mark_running()
        try:
            rows = list((loader or load_ldap_rows)())
            return _replace_generation(rows, generation)
        except Exception as error:
            _mark_error(error)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    # Configures the engine directly rather than through job_runner, and
    # takes an advisory lock below, so it declares the width itself.
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL, takes_lock=True)
    db.init_schema()
    summary = run()
    sys.stdout.write("toolforge-account-sync: " + json.dumps(summary, sort_keys=True) + "\n")
    return int(summary.get("status") == "locked")


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
