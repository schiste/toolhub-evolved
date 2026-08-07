# SPDX-License-Identifier: GPL-3.0-or-later
"""Unified public directory search across identity and relationship evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import account_directory, people_index
from backend.models import CanonicalToolCache, Person, ToolPersonRelationship

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MAX_CANDIDATES = 100


@dataclass(frozen=True)
class CommunitySearchQuery:
    """One user-facing search, independent from its backing projections."""

    query: str = ""
    page: int = 1
    page_size: int = 24
    role: str = ""
    verification: str = ""
    activity: str = ""
    project: str = ""
    ordering: str = "relevance"
    contributor: bool = False


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - request values are untrusted
    return str(value or "").strip()[:limit]


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _people_query(
    search: CommunitySearchQuery,
    *,
    query: str = "",
    public_ids: set[str] | None = None,
) -> people_index.PeopleDirectoryQuery:
    return people_index.PeopleDirectoryQuery(
        query=query,
        page=1,
        page_size=MAX_CANDIDATES,
        role=search.role,
        verification=search.verification,
        activity=search.activity,
        project=search.project,
        ordering=search.ordering,
        contributor=search.contributor,
        public_ids=tuple(sorted(public_ids or set())),
    )


def _identity_evidence(person: dict[str, Any]) -> dict[str, bool]:
    namespaces = {item.get("namespace") for item in person.get("identifiers", [])}
    return {
        "officialToolhubAccount": people_index.NS_TOOLHUB_USER_ID in namespaces,
        "wikimediaIdentity": people_index.NS_WIKIMEDIA_GLOBAL_USER_ID in namespaces,
        "toolforgeHandle": people_index.NS_TOOLFORGE_USERNAME in namespaces,
        "wikiHandle": people_index.NS_WIKI_USERNAME in namespaces,
    }


def _tool_person_public_ids(s: Session, query: str) -> set[str]:
    if not query:
        return set()
    needle = f"%{_like_literal(query.casefold())}%"
    rows = s.execute(
        select(Person.public_id)
        .join(ToolPersonRelationship, ToolPersonRelationship.person_id == Person.id)
        .outerjoin(CanonicalToolCache, CanonicalToolCache.tool_name == ToolPersonRelationship.tool_name)
        .where(
            or_(
                func.lower(ToolPersonRelationship.tool_name).like(needle, escape="\\"),
                CanonicalToolCache.search_text.like(needle, escape="\\"),
            )
        )
        .distinct()
        .limit(MAX_CANDIDATES)
    ).all()
    return {row[0] for row in rows}


def _person_rank(person: dict[str, Any], normalized: str, bases: set[str]) -> tuple[Any, ...]:
    display = str(person.get("displayName") or "").casefold()
    identifiers = [str(item.get("value") or "").casefold() for item in person.get("identifiers", [])]
    exact = display == normalized or normalized in identifiers
    prefix = display.startswith(normalized) or any(value.startswith(normalized) for value in identifiers)
    basis_rank = 0 if "identity" in bases else (1 if "account" in bases else 2)
    match_rank = 0 if exact else (1 if prefix else basis_rank + 2)
    summary = person.get("relationshipSummary") or {}
    return (
        match_rank,
        -int(summary.get("verifiedRelationshipCount") or 0),
        -int(summary.get("bestConfidence") or 0),
        display,
        str(person.get("id") or ""),
    )


def _person_item(person: dict[str, Any], bases: set[str], accounts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "person",
        "person": person,
        "matchBasis": sorted(bases),
        "identityEvidence": _identity_evidence(person),
        "officialAccountMatches": [
            {
                "id": account.get("id"),
                "username": account.get("username"),
                "identityLinkBasis": account.get("identityLinkBasis") or [],
            }
            for account in accounts
        ],
    }


def search_community(s: Session, search: CommunitySearchQuery) -> dict[str, Any]:
    """Compose one ranked directory without merging identities on display names."""
    query = _clean(search.query)
    page_size = max(1, min(search.page_size, 100))
    page = max(1, search.page)
    if not query:
        people = people_index.search_people_directory(
            s,
            people_index.PeopleDirectoryQuery(
                page=page,
                page_size=page_size,
                role=search.role,
                verification=search.verification,
                activity=search.activity,
                project=search.project,
                ordering=search.ordering,
                contributor=search.contributor,
            ),
        )
        return {
            **people,
            "results": [_person_item(person, {"directory"}, []) for person in people["results"]],
            "counts": {"people": people["count"], "accounts": 0, "unresolvedAttributions": 0},
            "accountSync": account_directory._sync_payload(  # noqa: SLF001 - shared public projection state
                s.get(account_directory.ToolhubAccountSyncState, account_directory.STATE_KEY)
            ),
        }

    filters_require_relationship = bool(
        search.role or search.verification or search.activity or search.project or search.contributor
    )
    text_people = people_index.search_people_directory(s, _people_query(search, query=query))
    accounts = account_directory.search_accounts(
        s,
        account_directory.AccountDirectoryQuery(query=query, page=1, page_size=MAX_CANDIDATES),
    )
    linked_public_ids = {row["personId"] for row in accounts["results"] if row.get("personId")}
    tool_public_ids = _tool_person_public_ids(s, query)
    related_public_ids = linked_public_ids | tool_public_ids
    related_people = (
        people_index.search_people_directory(s, _people_query(search, public_ids=related_public_ids))["results"]
        if related_public_ids
        else []
    )
    people_by_id: dict[str, dict[str, Any]] = {}
    bases_by_id: dict[str, set[str]] = {}
    for person in text_people["results"]:
        people_by_id[person["id"]] = person
        bases_by_id.setdefault(person["id"], set()).add("identity")
    for person in related_people:
        people_by_id[person["id"]] = person
        bases = bases_by_id.setdefault(person["id"], set())
        if person["id"] in linked_public_ids:
            bases.add("account")
        if person["id"] in tool_public_ids:
            bases.add("tool")

    accounts_by_person: dict[str, list[dict[str, Any]]] = {}
    account_only = []
    for account in accounts["results"]:
        person_id = account.get("personId")
        if person_id and person_id in people_by_id:
            accounts_by_person.setdefault(person_id, []).append(account)
        elif not filters_require_relationship:
            account_only.append({"kind": "account", "account": account, "matchBasis": ["official_account"]})

    normalized = query.casefold()
    person_items = [
        _person_item(person, bases_by_id[public_id], accounts_by_person.get(public_id, []))
        for public_id, person in people_by_id.items()
    ]
    person_items.sort(key=lambda item: _person_rank(item["person"], normalized, set(item["matchBasis"])))
    account_only.sort(
        key=lambda item: (
            0 if str(item["account"].get("username") or "").casefold() == normalized else 1,
            str(item["account"].get("username") or "").casefold(),
            str(item["account"].get("id") or ""),
        )
    )
    unresolved = (
        people_index.search_unresolved_attributions(
            s,
            people_index.UnresolvedAttributionQuery(query=query, page=1, page_size=MAX_CANDIDATES),
        )
        if not filters_require_relationship
        else {"count": 0, "results": []}
    )
    unresolved_items = [
        {"kind": "unresolved_attribution", "attribution": item, "matchBasis": ["display_only"]}
        for item in unresolved["results"]
    ]
    unresolved_items.sort(
        key=lambda item: (
            0 if str(item["attribution"].get("label") or "").casefold() == normalized else 1,
            str(item["attribution"].get("label") or "").casefold(),
        )
    )
    combined = [*person_items, *account_only, *unresolved_items]
    total = len(combined)
    page_count = max(1, (total + page_size - 1) // page_size)
    safe_page = min(page, page_count)
    start = (safe_page - 1) * page_size
    return {
        "count": total,
        "page": safe_page,
        "pageSize": page_size,
        "pageCount": page_count,
        "nextPage": safe_page + 1 if safe_page < page_count else None,
        "previousPage": safe_page - 1 if safe_page > 1 else None,
        "results": combined[start : start + page_size],
        "counts": {
            "people": len(person_items),
            "accounts": len(account_only),
            "unresolvedAttributions": len(unresolved_items),
        },
        "candidateLimit": MAX_CANDIDATES,
        "truncated": any(
            count > MAX_CANDIDATES
            for count in (text_people["count"], accounts["count"], unresolved.get("count", 0))
        ),
        "accountSync": accounts["sync"],
    }
