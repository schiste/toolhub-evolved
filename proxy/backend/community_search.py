# SPDX-License-Identifier: GPL-3.0-or-later
"""Unified public directory search across identity and relationship evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import account_directory, people_index
from backend.models import CanonicalToolCache, Person, ToolPersonRelationship, ToolRelationshipEvidence

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MAX_CANDIDATES = 100
SECTION_TOOL_LIMIT = 12
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


def _text_values(value: Any) -> list[str]:  # noqa: ANN401 - canonical JSON is untyped
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    return []


def _normalized_values(value: Any) -> list[tuple[str, str]]:  # noqa: ANN401 - canonical JSON is untyped
    return [(text, text.casefold()) for text in _text_values(value) if text.strip()]


def _tool_match(record: dict[str, Any], tool_name: str, query: str) -> tuple[int, dict[str, Any]] | None:
    """Explain the strongest canonical field that matched one tool."""
    normalized = query.casefold()
    names = [(tool_name, tool_name.casefold()), *_normalized_values(record.get("title"))]
    authors = []
    for author in record.get("author") or []:
        if isinstance(author, str):
            authors.append((author, author.casefold()))
        elif isinstance(author, dict):
            for key in ("name", "developer_username", "wiki_username"):
                authors.extend(_normalized_values(author.get(key)))
    keywords = _normalized_values(record.get("keywords"))
    descriptions = _normalized_values(record.get("description"))
    tiers = (
        (0, "exact_name", "name", (item for item in names if item[1] == normalized)),
        (1, "name_prefix", "name", (item for item in names if item[1].startswith(normalized))),
        (2, "name_contains", "name", (item for item in names if normalized in item[1])),
        (3, "structured_author", "author", (item for item in authors if normalized in item[1])),
        (4, "keyword", "keyword", (item for item in keywords if normalized in item[1])),
        (5, "description_mention", "description", (item for item in descriptions if normalized in item[1])),
    )
    for rank, reason, field, candidates in tiers:
        matched = next(candidates, None)
        if matched is not None:
            return rank, {"field": field, "reason": reason, "value": _clean(matched[0], 240)}
    return None


def _compact_tool(row: CanonicalToolCache | None, tool_name: str) -> dict[str, Any]:
    record = row.record if row is not None and isinstance(row.record, dict) else {}
    tool = {field: record[field] for field in TOOL_RESULT_FIELDS if field in record}
    tool["name"] = tool_name
    tool["origin"] = "canonical_cache"
    return tool


def _text_tool_results(s: Session, query: str) -> dict[str, Any]:
    """Classify broad catalog hits so description mentions never look primary."""
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
        ).scalars()
    )
    strong = []
    other = []
    for row in rows:
        record = row.record if isinstance(row.record, dict) else {}
        match = _tool_match(record, row.tool_name, query)
        if match is None:
            continue
        rank, explanation = match
        item = {
            "kind": "tool",
            "tool": _compact_tool(row, row.tool_name),
            "match": explanation,
            "matchBasis": [explanation["field"]],
            "_rank": rank,
        }
        (other if explanation["field"] == "description" else strong).append(item)
    for items in (strong, other):
        items.sort(key=lambda item: (item["_rank"], str(item["tool"]["name"]).casefold()))
        for item in items:
            item.pop("_rank", None)
    return {"candidateCount": total, "strong": strong, "other": other}


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
    type_rank = {"person": 0, "account": 1}.get(item.get("kind"), 2)
    summary = (item.get("person") or {}).get("relationshipSummary") or {}
    return (
        text_rank,
        type_rank,
        -int(summary.get("verifiedRelationshipCount") or 0),
        -int(summary.get("bestConfidence") or 0),
        values[0] if values else "",
    )


def _relationship_tool_results(s: Session, person_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return each related tool once with every relationship to exact people."""
    public_ids = {item["person"]["id"] for item in person_items}
    if not public_ids:
        return []
    rows = list(
        s.execute(
            select(Person, ToolPersonRelationship)
            .join(ToolPersonRelationship, ToolPersonRelationship.person_id == Person.id)
            .where(Person.public_id.in_(public_ids))
            .order_by(ToolPersonRelationship.tool_name, Person.public_id, ToolPersonRelationship.relationship_type)
        ).all()
    )
    tool_names = {relationship.tool_name for _person, relationship in rows}
    person_ids = {person.id for person, _relationship in rows}
    cache_by_name = {
        row.tool_name: row
        for row in s.execute(select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(tool_names or {""})))
        .scalars()
        .all()
    }
    evidence_by_relationship: dict[tuple[str, int, str], list[ToolRelationshipEvidence]] = {}
    evidence_rows = (
        s.execute(
            select(ToolRelationshipEvidence)
            .where(
                ToolRelationshipEvidence.tool_name.in_(tool_names or {""}),
                ToolRelationshipEvidence.person_id.in_(person_ids or {-1}),
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
            .order_by(ToolRelationshipEvidence.checked_at.desc(), ToolRelationshipEvidence.id.desc())
        )
        .scalars()
        .all()
    )
    for evidence in evidence_rows:
        key = (evidence.tool_name, evidence.person_id, evidence.relationship_type)
        evidence_by_relationship.setdefault(key, []).append(evidence)
    by_tool: dict[str, dict[str, Any]] = {}
    for person, relationship in rows:
        item = by_tool.setdefault(
            relationship.tool_name,
            {
                "kind": "tool",
                "tool": _compact_tool(cache_by_name.get(relationship.tool_name), relationship.tool_name),
                "match": {"field": "relationship", "reason": "person_relationship", "value": person.display_name},
                "matchBasis": ["relationship"],
                "relationships": [],
            },
        )
        payload = people_index.public_relationship_payload(
            person,
            relationship,
            evidence_by_relationship.get(
                (relationship.tool_name, person.id, relationship.relationship_type),
                [],
            ),
        )
        payload.update({"personId": person.public_id, "personName": person.display_name})
        item["relationships"].append(payload)
    status_rank = {"verified": 0, "stale": 1, "unverified": 2}
    role_rank = {role: index for index, role in enumerate(people_index.PUBLIC_ROLES)}
    for item in by_tool.values():
        item["relationships"].sort(
            key=lambda relationship: (
                status_rank.get(relationship["status"], 3),
                role_rank.get(relationship["type"], len(role_rank)),
            )
        )
    return sorted(
        by_tool.values(),
        key=lambda item: (
            min(status_rank.get(relationship["status"], 3) for relationship in item["relationships"]),
            str(item["tool"]["name"]).casefold(),
        ),
    )


def _section(count: int, results: list[dict[str, Any]], *, limit: int | None = None) -> dict[str, Any]:
    visible = results[:limit] if limit is not None else results
    return {"count": count, "results": visible, "truncated": len(results) > len(visible)}


def _fold_same_label_evidence(
    person_items: list[dict[str, Any]],
    attributions: list[dict[str, Any]],
    normalized_query: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Attach same-label evidence to one exact person without merging records."""
    exact_people = [item for item in person_items if normalized_query in _result_values(item)]
    by_label: dict[str, list[dict[str, Any]]] = {}
    for item in exact_people:
        label = str(item["person"].get("displayName") or "").casefold()
        by_label.setdefault(label, []).append(item)
    standalone = []
    folded = 0
    for attribution in attributions:
        matches = by_label.get(str(attribution.get("label") or "").casefold(), [])
        if len(matches) == 1:
            matches[0].setdefault("supportingEvidence", []).append(attribution)
            folded += 1
        else:
            standalone.append(attribution)
    return exact_people, standalone, folded


def _tool_sections(
    s: Session,
    query: str,
    exact_people: list[dict[str, Any]],
    *,
    include_text_matches: bool,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    relationship_tools = _relationship_tool_results(s, exact_people)
    text_tools = (
        _text_tool_results(s, query) if include_text_matches else {"candidateCount": 0, "strong": [], "other": []}
    )
    related_by_name = {item["tool"]["name"]: item for item in relationship_tools}
    for item in text_tools["strong"]:
        name = item["tool"]["name"]
        if name in related_by_name:
            related_by_name[name]["textMatch"] = item["match"]
            related_by_name[name]["matchBasis"] = ["relationship", item["match"]["field"]]
        else:
            related_by_name[name] = item
    relationship_names = {item["tool"]["name"] for item in relationship_tools}
    related_tools = sorted(
        related_by_name.values(),
        key=lambda item: (
            0 if item["tool"]["name"] in relationship_names else 1,
            str(item["tool"]["name"]).casefold(),
        ),
    )
    other_matches = [item for item in text_tools["other"] if item["tool"]["name"] not in related_by_name]
    return (
        _section(len(related_tools), related_tools, limit=SECTION_TOOL_LIMIT),
        _section(len(other_matches), other_matches, limit=SECTION_TOOL_LIMIT),
        text_tools["candidateCount"],
    )


def _primary_page(primary: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    count = len(primary)
    page_count = max(1, (count + page_size - 1) // page_size)
    safe_page = min(page, page_count)
    start = (safe_page - 1) * page_size
    return {
        "count": count,
        "page": safe_page,
        "pageSize": page_size,
        "pageCount": page_count,
        "nextPage": safe_page + 1 if safe_page < page_count else None,
        "previousPage": safe_page - 1 if safe_page > 1 else None,
        "results": primary[start : start + page_size],
    }


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
        primary_results = [_person_item(person, {"directory"}, []) for person in people["results"]]
        empty_section = _section(0, [])
        return {
            **people,
            "results": primary_results,
            "primaryResults": primary_results,
            "relatedTools": empty_section,
            "unresolvedEvidence": empty_section,
            "otherMatches": empty_section,
            "totalCount": people["count"],
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
    exact_people, standalone_evidence, folded_evidence_count = _fold_same_label_evidence(
        person_items, unresolved["results"], normalized
    )
    primary = [*person_items, *account_only]
    if search.ordering == "name":
        primary.sort(key=lambda item: ((_result_values(item) or [""])[0], item.get("kind", "")))
    else:
        primary.sort(key=lambda item: _result_rank(item, normalized))
    page_payload = _primary_page(primary, page, page_size)
    related_section, other_section, tool_candidate_count = _tool_sections(
        s, query, exact_people, include_text_matches=not filters_require_relationship
    )
    evidence_section = _section(len(standalone_evidence), standalone_evidence, limit=SECTION_TOOL_LIMIT)
    total_count = page_payload["count"] + related_section["count"] + evidence_section["count"] + other_section["count"]
    return {
        **page_payload,
        "totalCount": total_count,
        "primaryResults": page_payload["results"],
        "relatedTools": related_section,
        "unresolvedEvidence": evidence_section,
        "otherMatches": other_section,
        "counts": {
            "people": len(person_items),
            "accounts": len(account_only),
            "tools": related_section["count"],
            "otherToolMatches": other_section["count"],
            "unresolvedAttributions": evidence_section["count"],
            "foldedUnresolvedAttributions": folded_evidence_count,
        },
        "candidateLimit": MAX_CANDIDATES,
        "truncated": any(
            count > MAX_CANDIDATES
            for count in (
                text_people["count"],
                accounts["count"],
                unresolved.get("count", 0),
                tool_candidate_count,
            )
        ),
        "accountSync": accounts["sync"],
    }
