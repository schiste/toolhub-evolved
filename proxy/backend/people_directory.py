# SPDX-License-Identifier: GPL-3.0-or-later
"""Public people-directory queries and relationship summaries.

The directory owns filtering, ranking, pagination, and public relationship
aggregation. Identity resolution and evidence mutation remain in people_index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, func, or_, select

from backend import paging
from backend.models import (
    CatalogFacetValue,
    Person,
    PersonActivitySummary,
    PersonIdentifier,
    PersonProfile,
    ToolPersonRelationship,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.people_index import (
    IDENTIFIER_HANDLE,
    IDENTIFIER_STABLE,
    PERSON_REL_CATALOG_ACTOR,
    PUBLIC_HANDLE_NAMESPACES,
    PUBLIC_ROLES,
    PeopleDirectoryQuery,
    _clean,
    _current_candidate_attributions,
    _current_relationship_clause,
    _current_unresolved_clause,
    _current_verified_clause,
    _identifiers_by_person,
    _normalized,
    _person_base_payload,
    _public_identity_clause,
)
from backend.sync import AUTHOR_CLAIM_STALE, AUTHOR_CLAIM_VERIFIED

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session


def find_people(s: Session, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that only need the first page."""
    return search_people_directory(
        s,
        PeopleDirectoryQuery(query=query, page=1, page_size=limit),
    )["results"]


def _relationship_directory_filter(
    *,
    role: str,
    verification: str,
    project: str,
    checked_at: datetime,
) -> Any:  # noqa: ANN401 - correlated SQL expression
    statement = select(ToolPersonRelationship.id).where(
        ToolPersonRelationship.person_id == Person.id,
        ToolPersonRelationship.relationship_type.in_(PUBLIC_ROLES),
        _current_relationship_clause(checked_at=checked_at),
    )
    if project:
        statement = statement.join(
            CatalogFacetValue,
            CatalogFacetValue.tool_name == ToolPersonRelationship.tool_name,
        ).where(
            CatalogFacetValue.field == "wiki",
            func.lower(CatalogFacetValue.value) == project.casefold(),
        )
    if role:
        statement = statement.where(ToolPersonRelationship.relationship_type == role)
    if verification == "verified":
        statement = statement.where(_current_verified_clause(checked_at=checked_at))
    elif verification == "renewal_needed":
        statement = statement.where(
            or_(
                ToolPersonRelationship.verification_status == AUTHOR_CLAIM_STALE,
                and_(
                    ToolPersonRelationship.verification_status == AUTHOR_CLAIM_VERIFIED,
                    ToolPersonRelationship.expires_at.is_not(None),
                    ToolPersonRelationship.expires_at <= checked_at,
                ),
            )
        )
    elif verification == "unverified":
        statement = statement.where(
            ToolPersonRelationship.verification_status.not_in((AUTHOR_CLAIM_VERIFIED, AUTHOR_CLAIM_STALE))
        )
    return statement.exists()


def _empty_directory_relationship_summary() -> dict[str, Any]:
    return {
        "relationshipCount": 0,
        "verifiedRelationshipCount": 0,
        "evidenceCount": 0,
        "bestConfidence": 0,
        "types": [],
        "verifiedTypes": [],
        "toolCountsByType": dict.fromkeys(PUBLIC_ROLES, 0),
        "verifiedToolCountsByType": dict.fromkeys(PUBLIC_ROLES, 0),
    }


def _directory_relationship_summaries(
    s: Session,
    person_ids: set[int],
    *,
    checked_at: datetime,
) -> dict[int, dict[str, Any]]:
    summaries: dict[int, dict[str, Any]] = {}
    rows = s.execute(
        select(ToolPersonRelationship).where(
            ToolPersonRelationship.person_id.in_(person_ids or {-1}),
            ToolPersonRelationship.relationship_type.in_(PUBLIC_ROLES),
            _current_relationship_clause(checked_at=checked_at),
        )
    ).scalars()
    relationship_keys: set[tuple[int, str, str]] = set()
    for row in rows:
        relationship_keys.add((row.person_id, row.tool_name, row.relationship_type))
        summary = summaries.setdefault(
            row.person_id,
            _empty_directory_relationship_summary() | {"types": set(), "verifiedTypes": set()},
        )
        summary["relationshipCount"] += 1
        summary["evidenceCount"] += row.evidence_count
        summary["bestConfidence"] = max(summary["bestConfidence"], row.confidence)
        summary["types"].add(row.relationship_type)
        summary["toolCountsByType"][row.relationship_type] += 1
        is_current_verified = row.verification_status == AUTHOR_CLAIM_VERIFIED and (
            row.expires_at is None or row.expires_at > checked_at
        )
        if is_current_verified:
            summary["verifiedRelationshipCount"] += 1
            summary["verifiedTypes"].add(row.relationship_type)
            summary["verifiedToolCountsByType"][row.relationship_type] += 1
    candidate_groups: dict[tuple[int, str, str], list[UnresolvedAttributionEvidence]] = {}
    for attribution, person_id in _current_candidate_attributions(
        s,
        person_ids=person_ids,
        checked_at=checked_at,
    ):
        key = (person_id, attribution.tool_name, attribution.relationship_type)
        if key not in relationship_keys:
            candidate_groups.setdefault(key, []).append(attribution)
    candidate_tools_by_role: dict[tuple[int, str], set[str]] = {}
    for (person_id, tool_name, relationship_type), supporting in candidate_groups.items():
        summary = summaries.setdefault(
            person_id,
            _empty_directory_relationship_summary() | {"types": set(), "verifiedTypes": set()},
        )
        summary["relationshipCount"] += 1
        summary["evidenceCount"] += len(supporting)
        summary["bestConfidence"] = max(
            summary["bestConfidence"],
            max((row.confidence for row in supporting), default=0),
        )
        summary["types"].add(relationship_type)
        candidate_tools_by_role.setdefault((person_id, relationship_type), set()).add(tool_name)
    for (person_id, relationship_type), tool_names in candidate_tools_by_role.items():
        summaries[person_id]["toolCountsByType"][relationship_type] += len(tool_names)
    for summary in summaries.values():
        summary["types"] = [role for role in PUBLIC_ROLES if role in summary["types"]]
        summary["verifiedTypes"] = [role for role in PUBLIC_ROLES if role in summary["verifiedTypes"]]
    return summaries


def relationship_summaries_by_public_id(
    s: Session,
    public_ids: set[str],
    *,
    checked_at: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Return count/trust summaries for safely linked public identities."""
    people = dict(s.execute(select(Person.id, Person.public_id).where(Person.public_id.in_(public_ids or {""}))).all())
    summaries = _directory_relationship_summaries(
        s,
        set(people),
        checked_at=checked_at or utcnow(),
    )
    return {
        public_id: summaries.get(person_id, _empty_directory_relationship_summary())
        for person_id, public_id in people.items()
    }


def _directory_contributor_summaries(
    s: Session,
    person_ids: set[int],
    activities: dict[int, PersonActivitySummary],
) -> dict[int, dict[str, Any]]:
    actor_counts = dict(
        s.execute(
            select(
                ToolPersonRelationship.person_id,
                func.count(func.distinct(ToolPersonRelationship.tool_name)),
            )
            .where(
                ToolPersonRelationship.person_id.in_(person_ids or {-1}),
                ToolPersonRelationship.relationship_type == PERSON_REL_CATALOG_ACTOR,
                ToolPersonRelationship.toolhub_canonical.is_(True),
            )
            .group_by(ToolPersonRelationship.person_id)
        ).all()
    )
    summaries: dict[int, dict[str, Any]] = {}
    for person_id in person_ids:
        activity = activities.get(person_id)
        bases = []
        if actor_counts.get(person_id, 0) > 0:
            bases.append("canonical_catalog_actor")
        if activity is not None and activity.contribution_count > 0:
            bases.append("approved_public_activity")
        summaries[person_id] = {
            "eligible": bool(bases),
            "bases": ["observed_public_contribution"] if bases else [],
            "approvedPublicContributionCount": int(activity.contribution_count if activity is not None else 0),
        }
    return summaries


def search_people_directory(  # noqa: C901, PLR0915 - explicit query/ranking/filter contract
    s: Session,
    search: PeopleDirectoryQuery,
) -> dict[str, Any]:
    """Search publishable people with stable ordering, filters, and real totals."""
    clean_query = _clean(search.query)
    normalized_query = _normalized(clean_query)
    checked_at = utcnow()
    related_people = select(ToolPersonRelationship.person_id).where(
        ToolPersonRelationship.relationship_type.in_(PUBLIC_ROLES),
        _current_relationship_clause(checked_at=checked_at),
    )
    candidate_people = select(PersonIdentifier.person_id).where(
        PersonIdentifier.namespace.in_(PUBLIC_HANDLE_NAMESPACES),
        PersonIdentifier.is_current.is_(True),
        PersonIdentifier.normalized_value.in_(
            select(UnresolvedAttributionEvidence.normalized_label).where(
                _current_unresolved_clause(checked_at=checked_at),
                UnresolvedAttributionEvidence.relationship_type.in_(PUBLIC_ROLES),
            )
        ),
    )
    visible_people = related_people.union(candidate_people)
    profile_people = select(PersonProfile.person_id)
    statement = (
        select(Person)
        .outerjoin(PersonActivitySummary, PersonActivitySummary.person_id == Person.id)
        .where(
            or_(Person.id.in_(visible_people), Person.id.in_(profile_people)),
            _public_identity_clause(),
        )
    )
    if search.public_ids:
        statement = statement.where(Person.public_id.in_(search.public_ids))
    if clean_query:
        matching_ids = select(PersonIdentifier.person_id).where(
            PersonIdentifier.is_current.is_(True),
            PersonIdentifier.normalized_value.like(f"%{normalized_query}%"),
        )
        statement = statement.where(
            or_(func.lower(Person.display_name).like(f"%{clean_query.casefold()}%"), Person.id.in_(matching_ids))
        )
    if search.role or search.verification or search.project:
        statement = statement.where(
            _relationship_directory_filter(
                role=search.role,
                verification=search.verification,
                project=search.project,
                checked_at=checked_at,
            )
        )
    if search.activity:
        if search.activity == "unknown":
            statement = statement.where(
                or_(
                    PersonActivitySummary.person_id.is_(None),
                    PersonActivitySummary.activity_status == "unknown",
                )
            )
        else:
            statement = statement.where(PersonActivitySummary.activity_status == search.activity)
    if search.contributor:
        canonical_actor = (
            select(ToolPersonRelationship.id)
            .where(
                ToolPersonRelationship.person_id == Person.id,
                ToolPersonRelationship.relationship_type == PERSON_REL_CATALOG_ACTOR,
                ToolPersonRelationship.toolhub_canonical.is_(True),
            )
            .correlate(Person)
            .exists()
        )
        statement = statement.where(
            or_(
                canonical_actor,
                PersonActivitySummary.contribution_count > 0,
            )
        )

    total = int(s.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)
    identity_rank = case(
        (Person.identity_quality == IDENTIFIER_STABLE, 3),
        (Person.identity_quality == IDENTIFIER_HANDLE, 2),
        else_=1,
    )
    current_verified_confidence = (
        select(func.max(ToolPersonRelationship.confidence))
        .where(
            ToolPersonRelationship.person_id == Person.id,
            ToolPersonRelationship.relationship_type.in_(PUBLIC_ROLES),
            _current_verified_clause(checked_at=checked_at),
        )
        .correlate(Person)
        .scalar_subquery()
    )
    name_order = (func.lower(Person.display_name), Person.public_id)
    relationship_order = (
        func.coalesce(PersonActivitySummary.verified_tool_count, 0).desc(),
        func.coalesce(current_verified_confidence, 0).desc(),
        func.coalesce(PersonActivitySummary.related_tool_count, 0).desc(),
    )
    activity_order = (
        case((PersonActivitySummary.last_contribution_at.is_(None), 1), else_=0),
        PersonActivitySummary.last_contribution_at.desc(),
    )
    if search.ordering == "name":
        order = name_order
    elif search.ordering == "recent":
        order = (*activity_order, *relationship_order, *name_order)
    elif search.ordering == "relationship":
        order = (*relationship_order, *activity_order, identity_rank.desc(), *name_order)
    elif normalized_query:
        exact_stable = (
            select(PersonIdentifier.id)
            .where(
                PersonIdentifier.person_id == Person.id,
                PersonIdentifier.is_current.is_(True),
                PersonIdentifier.identifier_kind == IDENTIFIER_STABLE,
                PersonIdentifier.normalized_value == normalized_query,
            )
            .correlate(Person)
            .exists()
        )
        exact_handle = (
            select(PersonIdentifier.id)
            .where(
                PersonIdentifier.person_id == Person.id,
                PersonIdentifier.is_current.is_(True),
                PersonIdentifier.identifier_kind == IDENTIFIER_HANDLE,
                PersonIdentifier.normalized_value == normalized_query,
            )
            .correlate(Person)
            .exists()
        )
        prefix_identifier = (
            select(PersonIdentifier.id)
            .where(
                PersonIdentifier.person_id == Person.id,
                PersonIdentifier.is_current.is_(True),
                PersonIdentifier.normalized_value.like(f"{normalized_query}%"),
            )
            .correlate(Person)
            .exists()
        )
        match_rank = case(
            (exact_stable, 6),
            (exact_handle, 5),
            (func.lower(Person.display_name) == clean_query.casefold(), 4),
            (prefix_identifier, 3),
            (func.lower(Person.display_name).like(f"{clean_query.casefold()}%"), 2),
            else_=1,
        )
        order = (match_rank.desc(), identity_rank.desc(), *relationship_order, *activity_order, *name_order)
    else:
        order = (*relationship_order, *activity_order, identity_rank.desc(), *name_order)

    safe_page = max(1, search.page)
    safe_page_size = max(1, min(search.page_size, paging.MAX_PAGE_SIZE))
    people = list(
        s.execute(statement.order_by(*order).offset((safe_page - 1) * safe_page_size).limit(safe_page_size)).scalars()
    )
    person_ids = {person.id for person in people}
    identifiers = _identifiers_by_person(s, {person.id for person in people})
    activities = {
        row.person_id: row
        for row in s.execute(
            select(PersonActivitySummary).where(
                PersonActivitySummary.person_id.in_({person.id for person in people} or {-1})
            )
        ).scalars()
    }
    profiles = {
        row.person_id: row
        for row in s.execute(
            select(PersonProfile).where(
                PersonProfile.person_id.in_({person.id for person in people} or {-1}),
                PersonProfile.visibility == "public",
            )
        ).scalars()
    }
    relationship_summaries = _directory_relationship_summaries(s, person_ids, checked_at=checked_at)
    contributor_summaries = _directory_contributor_summaries(s, person_ids, activities)
    results = [
        _person_base_payload(person, identifiers.get(person.id, []), profiles.get(person.id), activities.get(person.id))
        | {
            "relationshipSummary": relationship_summaries.get(
                person.id,
                _empty_directory_relationship_summary(),
            ),
            "contributor": contributor_summaries[person.id],
        }
        for person in people
    ]
    page_count = max(1, (total + safe_page_size - 1) // safe_page_size)
    return {
        "count": total,
        "page": safe_page,
        "pageSize": safe_page_size,
        "pageCount": page_count,
        "nextPage": safe_page + 1 if safe_page < page_count else None,
        "previousPage": safe_page - 1 if safe_page > 1 else None,
        "results": results,
    }
