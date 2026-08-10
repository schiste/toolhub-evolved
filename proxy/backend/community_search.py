# SPDX-License-Identifier: GPL-3.0-or-later
"""Unified public directory search across identity and relationship evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import account_directory, people_index
from backend.models import CanonicalToolCache

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MAX_CANDIDATES = 100
TOOL_RESULT_FIELDS = (
    "name",
    "title",
    "description",
    "url",
    "icon",
    "keywords",
    "tool_type",
    "for_wikis",
    "deprecated",
    "experimental",
    "author",
)


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


def _tool_results(s: Session, query: str) -> dict[str, Any]:
    """Return matching tools directly instead of expanding every related person."""
    needle = f"%{_like_literal(query.casefold())}%"
    predicate = or_(
        func.lower(CanonicalToolCache.tool_name).like(needle, escape="\\"),
        func.lower(CanonicalToolCache.search_text).like(needle, escape="\\"),
    )
    total = int(s.scalar(select(func.count()).select_from(CanonicalToolCache).where(predicate)) or 0)
    rows = list(
        s.execute(
            select(CanonicalToolCache)
            .where(predicate)
            .order_by(func.lower(CanonicalToolCache.tool_name))
            .limit(MAX_CANDIDATES)
        )
        .scalars()
    )
    results = []
    for row in rows:
        record = row.record if isinstance(row.record, dict) else {}
        tool = {field: record[field] for field in TOOL_RESULT_FIELDS if field in record}
        tool["name"] = row.tool_name
        tool["origin"] = "canonical_cache"
        results.append({"kind": "tool", "tool": tool, "matchBasis": ["tool"]})
    return {"count": total, "results": results}


def _result_values(item: dict[str, Any]) -> list[str]:
    kind = item.get("kind")
    if kind == "person":
        person = item.get("person") or {}
        values = [person.get("displayName")]
        values.extend(identifier.get("value") for identifier in person.get("identifiers", []))
        values.extend(account.get("username") for account in item.get("officialAccountMatches", []))
    elif kind == "account":
        values = [(item.get("account") or {}).get("username")]
    elif kind == "unresolved_attribution":
        values = [(item.get("attribution") or {}).get("label")]
    else:
        tool = item.get("tool") or {}
        values = [tool.get("name"), tool.get("title")]
    return [str(value).casefold() for value in values if value]


def _result_rank(item: dict[str, Any], normalized: str) -> tuple[Any, ...]:
    values = _result_values(item)
    text_rank = 0 if normalized in values else (1 if any(value.startswith(normalized) for value in values) else 2)
    type_rank = {"person": 0, "account": 1, "unresolved_attribution": 2, "tool": 3}.get(item.get("kind"), 4)
    summary = (item.get("person") or {}).get("relationshipSummary") or {}
    return (
        text_rank,
        type_rank,
        -int(summary.get("verifiedRelationshipCount") or 0),
        -int(summary.get("bestConfidence") or 0),
        values[0] if values else "",
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
            "counts": {"people": people["count"], "accounts": 0, "tools": 0, "unresolvedAttributions": 0},
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
    linked_relationship_summaries = people_index.relationship_summaries_by_public_id(s, linked_public_ids)
    related_public_ids = linked_public_ids
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

    accounts_by_person: dict[str, list[dict[str, Any]]] = {}
    account_only = []
    for account in accounts["results"]:
        person_id = account.get("personId")
        if person_id and person_id in people_by_id:
            accounts_by_person.setdefault(person_id, []).append(account)
        elif not filters_require_relationship:
            account_only.append(
                {
                    "kind": "account",
                    "account": account,
                    "matchBasis": ["official_account"],
                    "relationshipSummary": linked_relationship_summaries.get(person_id),
                }
            )

    normalized = query.casefold()
    person_items = [
        _person_item(person, bases_by_id[public_id], accounts_by_person.get(public_id, []))
        for public_id, person in people_by_id.items()
    ]
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
    tools = _tool_results(s, query) if not filters_require_relationship else {"count": 0, "results": []}
    combined = [*person_items, *account_only, *unresolved_items, *tools["results"]]
    if search.ordering == "name":
        combined.sort(key=lambda item: ((_result_values(item) or [""])[0], item.get("kind", "")))
    else:
        combined.sort(key=lambda item: _result_rank(item, normalized))
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
            "tools": len(tools["results"]),
            "unresolvedAttributions": len(unresolved_items),
        },
        "candidateLimit": MAX_CANDIDATES,
        "truncated": any(
            count > MAX_CANDIDATES
            for count in (text_people["count"], accounts["count"], unresolved.get("count", 0), tools["count"])
        ),
        "accountSync": accounts["sync"],
    }
