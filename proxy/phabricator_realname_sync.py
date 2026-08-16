# SPDX-License-Identifier: GPL-3.0-or-later
"""Paced, resumable sweep that learns the real name behind a developer handle.

Toolsadmin renders the LDAP ``cn`` as a tool's maintainer handle but copies the
Phabricator *real name* into the toolinfo ``author`` field, so the catalog says
``Gopa Vasanth`` where every handle this project holds says ``Gopavasanth``.
Those labels can never resolve against a handle namespace.

This job asks Phabricator only about handles it already holds -- a real name is
never a search key -- caches each public ``username -> real name`` pair, and
then re-decides on every sweep which pairs ``people_policy`` will let stand as
a matching key. Recording one links nothing on its own:
``corroborated_handle_person`` still demands an independent verified edge to
the same tool before any relationship is written.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import canonical_tools, db, job_runner, people_index, people_policy
from backend.models import (
    ApiCacheMeta,
    PhabricatorProfileProjection,
    ToolforgeAccountProjection,
    ToolforgeMembershipProjection,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.phabricator_identity import (
    PhabricatorProfileError,
    PhabricatorProfileProvider,
    is_probable_username,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

CURSOR_KEY = "phabricator_realname_cursor"
SOURCE = "phabricator_profile"
DEFAULT_LIMIT = 60
# The scheduled cadence is 60 accounts per hour. The ceiling is far higher so
# an operator can drain the labelled candidate set in one manual backfill,
# which is the only time a run is expected to make thousands of requests.
MAX_LIMIT = 4000
DEFAULT_MIN_INTERVAL_SECONDS = 2.0
MAX_MIN_INTERVAL_SECONDS = 60.0
# A real name changes rarely, so a known pair is re-read seasonally. A handle
# with no Phabricator account is re-asked far less often: the answer is stable
# for the many developer accounts that never registered one, and paying for
# that question every month would spend most of the request budget on it.
PROFILE_TTL = timedelta(days=90)
MISSING_TTL = timedelta(days=365)

# Which LDAP field a candidate handle came from, as ``people_policy`` names it.
KIND_DEVELOPER_USERNAME = "developer_username"
KIND_WIKIMEDIA_GLOBAL_NAME = "wikimedia_global_name"


def _bounded_limit(value: int) -> int:
    return max(1, min(MAX_LIMIT, int(value or DEFAULT_LIMIT)))


def _bounded_interval(value: float) -> float:
    return max(DEFAULT_MIN_INTERVAL_SECONDS, min(MAX_MIN_INTERVAL_SECONDS, float(value)))


def _normalized(value: str) -> str:
    return str(value or "").strip()[:255].casefold()


def candidate_handles(account: ToolforgeAccountProjection) -> list[tuple[str, str]]:
    """Return the handles worth asking Phabricator about for one account.

    The Unix login (``uid``) is deliberately absent: it is a lowercased,
    truncated shell handle that often reads as a common first name, so it is
    the one candidate likely to land on an unrelated Phabricator account.
    ``developer_username`` comes first so an account whose two fields agree is
    attributed to the LDAP ``cn`` that Toolsadmin actually renders.
    """
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for value, kind in (
        (account.developer_username, KIND_DEVELOPER_USERNAME),
        (account.wikimedia_global_name, KIND_WIKIMEDIA_GLOBAL_NAME),
    ):
        handle = str(value or "").strip()
        key = handle.casefold()
        if not handle or key in seen or not is_probable_username(handle):
            continue
        seen.add(key)
        candidates.append((handle, kind))
    return candidates


def _cursor(s: Session) -> str:
    row = s.get(ApiCacheMeta, CURSOR_KEY)
    return str(row.value or "") if row is not None else ""


def _set_cursor(s: Session, value: str) -> None:
    row = s.get(ApiCacheMeta, CURSOR_KEY)
    if row is None:
        row = ApiCacheMeta(key=CURSOR_KEY, value=value)
        s.add(row)
    else:
        row.value = value
    row.updated_at = utcnow()


def _accounts(s: Session, cursor: str, limit: int) -> list[ToolforgeAccountProjection]:
    """Return one bounded window of accounts ordered by their immutable id."""
    query = select(ToolforgeAccountProjection).order_by(ToolforgeAccountProjection.uid_number)
    if cursor:
        query = query.where(ToolforgeAccountProjection.uid_number > cursor)
    return list(s.execute(query.limit(limit)).scalars())


def _labelled_tools(s: Session) -> set[str]:
    """Return tools carrying an unresolved label shaped like a person's name.

    ``is_handle_shaped`` is the same gate the registry sweep uses, read the
    other way round: a label it refuses is one no public handle registry can
    resolve, which is exactly the population a real name can reach.
    """
    return {
        tool_name
        for tool_name, label in s.execute(
            select(UnresolvedAttributionEvidence.tool_name, UnresolvedAttributionEvidence.observed_label).where(
                UnresolvedAttributionEvidence.withdrawn_at.is_(None)
            )
        ).all()
        if label and not people_policy.is_handle_shaped(label)
    }


def _priority_uid_numbers(s: Session) -> set[str]:
    """Return accounts that maintain a tool with a name-shaped label to resolve.

    A full walk of every developer account eventually reads the same profiles,
    but most of them can resolve nothing: the account maintains no catalogued
    tool whose author label is a name. Asking about those first would spend the
    whole request budget before reaching an account that changes an answer, so
    the labels choose the candidates and the cursor walk stays the backstop.
    """
    tools = _labelled_tools(s)
    if not tools:
        return set()
    projects = {
        project.casefold()
        for item in canonical_tools.records()
        if (name := str(item.get("toolName") or "").strip()) in tools and isinstance(item.get("record"), dict)
        for project in canonical_tools.toolforge_project_names(name, item["record"])
    }
    if not projects:
        return set()
    return {
        uid_number
        for uid_number, tool_name in s.execute(
            select(ToolforgeMembershipProjection.uid_number, ToolforgeMembershipProjection.tool_name)
        ).all()
        if str(tool_name or "").casefold() in projects
    }


def _priority_accounts(s: Session, limit: int) -> list[ToolforgeAccountProjection]:
    """Return the candidate accounts, oldest account first, capped at limit."""
    uid_numbers = _priority_uid_numbers(s)
    if not uid_numbers:
        return []
    accounts = s.execute(select(ToolforgeAccountProjection).order_by(ToolforgeAccountProjection.uid_number)).scalars()
    return [account for account in accounts if account.uid_number in uid_numbers][:limit]


def _is_fresh(row: PhabricatorProfileProjection, now: Any) -> bool:  # noqa: ANN401 - datetime
    return row.checked_at > now - (MISSING_TTL if row.missing else PROFILE_TTL)


def _stale_groups(
    s: Session,
    accounts: list[ToolforgeAccountProjection],
    now: Any,  # noqa: ANN401 - datetime
) -> list[tuple[str, list[str]]]:
    """Group each account with the handles whose cached read has expired."""
    return [
        (account.uid_number, handles)
        for account in accounts
        if (
            handles := [
                handle
                for handle, _kind in candidate_handles(account)
                if (row := s.get(PhabricatorProfileProjection, _normalized(handle))) is None or not _is_fresh(row, now)
            ]
        )
    ]


def _store_profile(s: Session, handle: str, real_name: str) -> None:
    """Record one public read, keeping ``missing`` distinct from ``no name``."""
    now = utcnow()
    normalized = _normalized(handle)
    row = s.get(PhabricatorProfileProjection, normalized)
    if row is None:
        row = PhabricatorProfileProjection(normalized_username=normalized, first_seen_at=now)
        s.add(row)
    row.username = handle[:255]
    row.real_name = real_name[:255]
    row.normalized_real_name = _normalized(real_name)
    row.missing = not real_name
    row.source = SOURCE
    row.checked_at = now
    row.updated_at = now


def _read_account(
    provider: PhabricatorProfileProvider,
    handles: list[str],
    *,
    interval: float,
    sleep_fn: Callable[[float], None],
    spent: int,
) -> tuple[int, bool]:
    """Read one account's stale handles; return (requests made, interrupted)."""
    made = 0
    for handle in handles:
        if spent + made:
            sleep_fn(interval)
        made += 1
        try:
            profile = provider.lookup(handle)
        except PhabricatorProfileError:
            # Stop the window rather than record an outage as "no real name".
            # The cursor stays on the last account read in full, so the next
            # run resumes here instead of skipping the remainder.
            return made, True
        with db.session_scope() as s:
            _store_profile(s, handle, profile.real_name if profile is not None else "")
        if profile is not None:
            # The ``cn`` answered, so the SUL fallback costs a request for a
            # name this account will not be allowed to hold anyway.
            break
    return made, False


def _fetch_window(
    provider: PhabricatorProfileProvider,
    *,
    limit: int,
    interval: float,
    sleep_fn: Callable[[float], None],
) -> dict[str, int | bool]:
    """Read the candidates that can resolve a label, then continue the walk.

    Priority accounts spend the budget first and never move the cursor, so the
    background walk keeps its place while the labelled candidates drain. Only
    the leftover budget continues the walk, and the cursor advances only past
    an account whose every stale handle was read: an account whose ``cn`` has
    no Phabricator profile falls back to its SUL name on the same run, so
    advancing mid-account would silently drop that fallback.
    """
    with db.session_scope() as s:
        now = utcnow()
        priority = _stale_groups(s, _priority_accounts(s, limit), now)
        budget = max(0, limit - len(priority))
        walked = _accounts(s, _cursor(s), budget) if budget else []
        walked_uids = {account.uid_number for account in walked}
        groups = priority + _stale_groups(s, walked, now)
        last_uid = walked[-1].uid_number if walked else ""

    stale = sum(len(handles) for _uid, handles in groups)
    requests_made = 0
    reached = ""
    interrupted = False
    for uid, handles in groups:
        read, interrupted = _read_account(provider, handles, interval=interval, sleep_fn=sleep_fn, spent=requests_made)
        requests_made += read
        if interrupted:
            break
        if uid in walked_uids:
            reached = uid

    complete = not interrupted
    # A budget fully spent on priority accounts leaves the walk untouched, so
    # an empty `walked` only means "end of table" when the walk was asked at all.
    cycle_complete = budget > 0 and not walked
    with db.session_scope() as s:
        if cycle_complete:
            _set_cursor(s, "")
        elif complete and last_uid:
            _set_cursor(s, last_uid)
        elif reached:
            _set_cursor(s, reached)
    return {
        "priorityAccounts": len(priority),
        "accounts": len(priority) + len(walked),
        "requests": requests_made,
        "stale": stale,
        "cycleComplete": cycle_complete,
        "interrupted": not complete,
    }


def _account_pairs(s: Session) -> list[tuple[ToolforgeAccountProjection, str, str, str]]:
    """Join every account to the cached real name its handles resolved to."""
    cached = {
        row.normalized_username: row
        for row in s.execute(
            select(PhabricatorProfileProjection).where(PhabricatorProfileProjection.missing.is_(False))
        ).scalars()
    }
    pairs = []
    for account in s.execute(select(ToolforgeAccountProjection)).scalars():
        for handle, kind in candidate_handles(account):
            row = cached.get(_normalized(handle))
            if row is not None and row.real_name:
                pairs.append((account, row.username, row.real_name, kind))
                # One account contributes one name. Asking about the second
                # handle is a fallback for accounts whose cn has no profile,
                # not a licence to hold two names for the same person.
                break
    return pairs


def apply_identities() -> dict[str, int]:
    """Re-decide which cached pairs may stand as a matching key, and record them.

    The whole cache is re-judged on every sweep rather than at write time,
    because uniqueness is a property of the population: a name that was the
    only one of its kind last week stops being usable the moment a second
    account claims it, and only a full pass can notice that.
    """
    recorded = refused = retired = 0
    with db.session_scope() as s:
        pairs = _account_pairs(s)
        name_counts: dict[str, int] = {}
        for _account, _username, real_name, _kind in pairs:
            name_counts[_normalized(real_name)] = name_counts.get(_normalized(real_name), 0) + 1

        for account, username, real_name, kind in pairs:
            person = people_index.person_for_identifier(s, people_index.NS_TOOLFORGE_UID_NUMBER, account.uid_number)
            if person is None:
                refused += 1
                continue
            conflicting = bool(people_index.handle_owner_ids(s, real_name) - {person.id})
            if not people_policy.accept_phabricator_real_name(
                handle_kind=kind,
                real_name=real_name,
                matched_username=username,
                account_count_for_real_name=name_counts[_normalized(real_name)],
                conflicting_handle_owner=conflicting,
                account_disabled=bool(account.disabled),
            ):
                refused += 1
                continue
            if people_index.record_phabricator_real_name(s, person, real_name=real_name, source=SOURCE) is None:
                refused += 1
                continue
            recorded += 1
            retired += people_index.retire_phabricator_real_names(s, person, keep=real_name)
    return {"recorded": recorded, "refused": refused, "retired": retired}


def run(
    *,
    limit: int = DEFAULT_LIMIT,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
    provider: PhabricatorProfileProvider | None = None,
) -> dict[str, int | bool]:
    """Read one bounded window of profiles, then re-judge the whole cache."""
    fetched = _fetch_window(
        provider or PhabricatorProfileProvider(),
        limit=_bounded_limit(limit),
        interval=_bounded_interval(min_interval_seconds),
        sleep_fn=sleep_fn,
    )
    return {**fetched, **apply_identities()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cache Phabricator real names for known developer handles.")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("PHABRICATOR_REALNAME_LIMIT", DEFAULT_LIMIT)))
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=float(
            os.environ.get("PHABRICATOR_REALNAME_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS),
        ),
    )
    args = parser.parse_args(argv)
    return job_runner.run_job(
        "phabricator-realname-sync",
        lambda: run(limit=args.limit, min_interval_seconds=args.min_interval_seconds),
        lock=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
