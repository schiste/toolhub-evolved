# SPDX-License-Identifier: GPL-3.0-or-later
"""Local-only search and safe person linking for official Toolhub accounts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, or_, select

from backend import paging, people_index
from backend.models import Person, PersonIdentifier, ToolhubAccountProjection, ToolhubAccountSyncState

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

STATE_KEY = "official_accounts"
ORDER_NAME = "name"
ORDER_RECENT = "recent"
ORDERINGS = {ORDER_NAME, ORDER_RECENT}


@dataclass(frozen=True)
class AccountDirectoryQuery:
    """Validated official-account directory parameters."""

    query: str = ""
    page: int = 1
    page_size: int = 24
    group: str = ""
    ordering: str = ORDER_NAME


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - request/cache values are untrusted
    return str(value or "").strip()[:limit]


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value is not None else ""


def _sync_payload(state: ToolhubAccountSyncState | None) -> dict[str, Any]:
    if state is None:
        return {
            "status": "unavailable",
            "complete": False,
            "lastCompletedAt": "",
            "lastSuccessAt": "",
            "error": "Account projection has not been synchronized yet.",
        }
    complete = state.cycles_completed > 0
    status = (
        "stale"
        if complete and state.status == "error"
        else (
            "refreshing"
            if complete and state.cycle_started_at is not None
            else ("ready" if complete else ("building" if state.cycle_started_at is not None else "unavailable"))
        )
    )
    return {
        "status": status,
        "complete": complete,
        "lastCompletedAt": _iso(state.last_completed_at),
        "lastSuccessAt": _iso(state.last_success_at),
        "error": state.last_error or "",
    }


def _person_links(s: Session, accounts: list[ToolhubAccountProjection]) -> dict[str, dict[str, Any]]:
    toolhub_ids = {row.toolhub_user_id for row in accounts}
    wikimedia_ids = {row.wikimedia_global_user_id for row in accounts if row.wikimedia_global_user_id}
    identifiers = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.is_current.is_(True),
                or_(
                    (
                        (PersonIdentifier.namespace == people_index.NS_TOOLHUB_USER_ID)
                        & PersonIdentifier.value.in_(toolhub_ids or {""})
                    ),
                    (
                        (PersonIdentifier.namespace == people_index.NS_WIKIMEDIA_GLOBAL_USER_ID)
                        & PersonIdentifier.value.in_(wikimedia_ids or {""})
                    ),
                ),
            )
        ).scalars()
    )
    people = {
        row.id: row
        for row in s.execute(
            select(Person).where(Person.id.in_({identifier.person_id for identifier in identifiers} or {-1}))
        ).scalars()
    }
    by_identifier: dict[tuple[str, str], list[PersonIdentifier]] = {}
    for identifier in identifiers:
        by_identifier.setdefault((identifier.namespace, identifier.value), []).append(identifier)
    links: dict[str, dict[str, Any]] = {}
    for account in accounts:
        matched: dict[int, set[str]] = {}
        keys = [(people_index.NS_TOOLHUB_USER_ID, account.toolhub_user_id)]
        if account.wikimedia_global_user_id:
            keys.append((people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, account.wikimedia_global_user_id))
        for namespace, value in keys:
            for identifier in by_identifier.get((namespace, value), []):
                matched.setdefault(identifier.person_id, set()).add(namespace)
        if len(matched) == 1:
            person_id, bases = next(iter(matched.items()))
            person = people.get(person_id)
            links[account.toolhub_user_id] = {
                "personId": person.public_id if person is not None else None,
                "identityLinkStatus": "linked" if person is not None else "unlinked",
                "identityLinkBasis": sorted(bases),
            }
        elif len(matched) > 1:
            links[account.toolhub_user_id] = {
                "personId": None,
                "identityLinkStatus": "conflict",
                "identityLinkBasis": sorted({basis for bases in matched.values() for basis in bases}),
            }
        else:
            links[account.toolhub_user_id] = {
                "personId": None,
                "identityLinkStatus": "unlinked",
                "identityLinkBasis": [],
            }
    return links


def _account_payload(row: ToolhubAccountProjection, link: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.toolhub_user_id,
        "username": row.username,
        "groups": row.groups if isinstance(row.groups, list) else [],
        "dateJoined": _iso(row.date_joined),
        "wikimediaGlobalUserId": row.wikimedia_global_user_id or "",
        "wikimediaRegisteredAt": row.wikimedia_registered_at or "",
        "personId": link["personId"],
        "identityLinkStatus": link["identityLinkStatus"],
        "identityLinkBasis": link["identityLinkBasis"],
        "source": row.source,
        "syncStatus": row.sync_status,
    }


def search_accounts(s: Session, query: AccountDirectoryQuery) -> dict[str, Any]:
    """Search the complete local official-account projection."""
    clean_query = _clean(query.query)
    clean_group = _clean(query.group).casefold()
    statement = select(ToolhubAccountProjection)
    if clean_query:
        statement = statement.where(
            ToolhubAccountProjection.normalized_username.like(
                f"%{_like_literal(clean_query.casefold())}%",
                escape="\\",
            )
        )
    if clean_group:
        statement = statement.where(
            ToolhubAccountProjection.groups_search.like(f"%\n{_like_literal(clean_group)}\n%", escape="\\")
        )
    total = int(s.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)
    page_size = max(1, min(query.page_size, paging.MAX_PAGE_SIZE))
    page_count = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, query.page), page_count)
    name_order = (ToolhubAccountProjection.normalized_username, ToolhubAccountProjection.toolhub_user_id)
    order = (
        (
            case((ToolhubAccountProjection.date_joined.is_(None), 1), else_=0),
            ToolhubAccountProjection.date_joined.desc(),
            *name_order,
        )
        if query.ordering == ORDER_RECENT
        else name_order
    )
    accounts = list(s.execute(statement.order_by(*order).offset((page - 1) * page_size).limit(page_size)).scalars())
    links = _person_links(s, accounts)
    state = s.get(ToolhubAccountSyncState, STATE_KEY)
    return {
        "count": total,
        "page": page,
        "pageSize": page_size,
        "pageCount": page_count,
        "nextPage": page + 1 if page < page_count else None,
        "previousPage": page - 1 if page > 1 else None,
        "results": [_account_payload(account, links[account.toolhub_user_id]) for account in accounts],
        "sync": _sync_payload(state),
    }


def account_detail(s: Session, toolhub_user_id: str) -> dict[str, Any] | None:
    """Return one projected official account with only stable person linking."""
    account = s.get(ToolhubAccountProjection, _clean(toolhub_user_id, 64))
    if account is None:
        return None
    link = _person_links(s, [account])[account.toolhub_user_id]
    state = s.get(ToolhubAccountSyncState, STATE_KEY)
    return _account_payload(account, link) | {"sync": _sync_payload(state)}
