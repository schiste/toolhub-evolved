# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical Evolved people, relationship evidence, and public projections.

Toolhub remains authoritative for catalog records. This module records where a
fact came from, resolves identities, and materializes a local public view; none
of those rows grant or replace upstream Toolhub permissions.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend.models import (
    ActivityRow,
    CatalogCuration,
    Person,
    PersonActivitySummary,
    PersonIdentifier,
    PersonProfile,
    SourceAnalysisReport,
    ToolOverlay,
    ToolPersonRelationship,
    ToolRecord,
    ToolRelationshipEvidence,
    User,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_FAILED,
    AUTHOR_CLAIM_STALE,
    AUTHOR_CLAIM_UNVERIFIED,
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_CATALOG_ACTOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
    REVIEW_APPROVED,
    SOURCE_LOCAL,
    SYNC_OFFICIAL,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

IDENTIFIER_STABLE = "stable_id"
IDENTIFIER_HANDLE = "handle"
NS_TOOLHUB_USER_ID = "toolhub_user_id"
NS_TOOLHUB_USERNAME = "toolhub_username"
NS_WIKI_USERNAME = "wiki_username"
PUBLIC_ROLES = (PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER, PERSON_REL_RECORD_OWNER, PERSON_REL_CATALOG_ACTOR)
RECENT_ACTIVITY_DAYS = 90
ACTIVITY_STALE_DAYS = 1
ACTIVE_CONTRIBUTION_DAYS = 30
QUIET_CONTRIBUTION_DAYS = 180


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - upstream values are untrusted
    return str(value or "").strip()[:limit]


def _normalized(value: Any) -> str:  # noqa: ANN401 - upstream values are untrusted
    return _clean(value).casefold()


def _canonical_key(
    *,
    toolhub_user_id: str = "",
    toolhub_username: str = "",
    wiki_username: str = "",
    display: str = "",
    display_scope: str = "",
) -> str:
    if clean_id := _clean(toolhub_user_id, 64):
        return f"toolhub-id:{clean_id}"
    if clean_username := _normalized(toolhub_username):
        return f"toolhub:{clean_username}"
    if clean_wiki := _normalized(wiki_username):
        return f"wiki:{clean_wiki}"
    display_key = _normalized(display)
    if display_scope:
        scope_hash = hashlib.sha256(_clean(display_scope, 2000).encode()).hexdigest()[:20]
        return f"display:{display_key}:{scope_hash}"
    return f"display:{display_key}"


def _identifier_spec(namespace: str) -> tuple[str, bool]:
    return (IDENTIFIER_STABLE, True) if namespace == NS_TOOLHUB_USER_ID else (IDENTIFIER_HANDLE, False)


def _identifier_person(s: Session, namespace: str, value: str) -> Person | None:
    normalized = _normalized(value)
    if not normalized:
        return None
    identifier = s.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.namespace == namespace,
            PersonIdentifier.normalized_value == normalized,
            PersonIdentifier.is_current.is_(True),
        )
    ).scalar_one_or_none()
    return s.get(Person, identifier.person_id) if identifier is not None else None


def _upsert_identifier(  # noqa: PLR0913 - explicit identity provenance fields
    s: Session,
    person: Person,
    *,
    namespace: str,
    value: str,
    source: str,
    checked_at: datetime | None = None,
    authoritative_reassignment: bool = False,
) -> PersonIdentifier | None:
    clean_value = _clean(value)
    if not clean_value:
        return None
    normalized = _normalized(clean_value)
    row = s.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.namespace == namespace,
            PersonIdentifier.normalized_value == normalized,
        )
    ).scalar_one_or_none()
    kind, intrinsically_verified = _identifier_spec(namespace)
    now = checked_at or utcnow()
    if row is None:
        row = PersonIdentifier(
            person_id=person.id,
            namespace=namespace,
            value=clean_value,
            normalized_value=normalized,
            identifier_kind=kind,
            source=source,
            verified_at=now if intrinsically_verified else None,
        )
        s.add(row)
    elif row.person_id != person.id:
        if not authoritative_reassignment or kind == IDENTIFIER_STABLE:
            # Stable identifier collisions require audited reconciliation.
            # Handles move only when a stable Toolhub id proves their current
            # owner; unverified source observations never move identity data.
            return row
        row.person_id = person.id
    row.value = clean_value
    row.identifier_kind = kind
    row.source = source or row.source
    row.is_current = True
    row.last_seen_at = now
    row.retired_at = None
    row.updated_at = now
    return row


def _retire_superseded_handles(
    s: Session,
    person: Person,
    *,
    toolhub_username: str,
    wiki_username: str,
    retired_at: datetime,
) -> None:
    """Retire mutable handles superseded by a stable Toolhub identity."""
    for namespace, current_value in (
        (NS_TOOLHUB_USERNAME, toolhub_username),
        (NS_WIKI_USERNAME, wiki_username),
    ):
        current_normalized = _normalized(current_value)
        if not current_normalized:
            continue
        old_handles = s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.person_id == person.id,
                PersonIdentifier.namespace == namespace,
                PersonIdentifier.is_current.is_(True),
                PersonIdentifier.normalized_value != current_normalized,
            )
        ).scalars()
        for old_handle in old_handles:
            old_handle.is_current = False
            old_handle.retired_at = retired_at
            old_handle.updated_at = retired_at


def ensure_person(  # noqa: PLR0913 - source adapters provide independent identifiers
    s: Session,
    *,
    display_name: str = "",
    toolhub_user_id: str = "",
    toolhub_username: str = "",
    wiki_username: str = "",
    source: str = SOURCE_LOCAL,
    checked_at: datetime | None = None,
    display_scope: str = "",
) -> Person:
    """Resolve or create a person from strongest to weakest identity evidence."""
    # An immutable id is authoritative: a mutable handle owned by somebody
    # else must move to the stable identity, never select and merge that owner.
    candidates = (
        [_identifier_person(s, NS_TOOLHUB_USER_ID, toolhub_user_id)]
        if _clean(toolhub_user_id, 64)
        else [
            _identifier_person(s, NS_TOOLHUB_USERNAME, toolhub_username),
            _identifier_person(s, NS_WIKI_USERNAME, wiki_username),
        ]
    )
    person = next((candidate for candidate in candidates if candidate is not None), None)
    display = _clean(display_name or toolhub_username or wiki_username)
    if person is None:
        key = _canonical_key(
            toolhub_user_id=toolhub_user_id,
            toolhub_username=toolhub_username,
            wiki_username=wiki_username,
            display=display,
            display_scope=display_scope,
        )
        person = s.execute(select(Person).where(Person.canonical_key == key)).scalar_one_or_none()
    if person is None and display and not display_scope:
        matches = list(
            s.execute(
                select(Person).where(
                    func.lower(Person.display_name) == display.casefold(),
                    Person.identity_quality == "display_name",
                )
            ).scalars()
        )
        person = matches[0] if len(matches) == 1 else None
    if person is None:
        person = Person(
            canonical_key=_canonical_key(
                toolhub_user_id=toolhub_user_id,
                toolhub_username=toolhub_username,
                wiki_username=wiki_username,
                display=display,
                display_scope=display_scope,
            ),
            display_name=display,
            identity_quality="stable"
            if toolhub_user_id
            else ("handle" if toolhub_username or wiki_username else "display_name"),
        )
        s.add(person)
        s.flush()
    if display and (not person.display_name or person.identity_quality == "display_name"):
        person.display_name = display
    if toolhub_user_id:
        person.identity_quality = "stable"
        person.canonical_key = _canonical_key(toolhub_user_id=toolhub_user_id)
    elif person.identity_quality == "display_name" and (toolhub_username or wiki_username):
        person.identity_quality = "handle"
    person.updated_at = checked_at or utcnow()
    s.flush()
    if toolhub_user_id:
        _retire_superseded_handles(
            s,
            person,
            toolhub_username=toolhub_username,
            wiki_username=wiki_username,
            retired_at=checked_at or utcnow(),
        )
    for namespace, value in (
        (NS_TOOLHUB_USER_ID, toolhub_user_id),
        (NS_TOOLHUB_USERNAME, toolhub_username),
        (NS_WIKI_USERNAME, wiki_username),
    ):
        _upsert_identifier(
            s,
            person,
            namespace=namespace,
            value=value,
            source=source,
            checked_at=checked_at,
            authoritative_reassignment=bool(toolhub_user_id and namespace != NS_TOOLHUB_USER_ID),
        )
    s.flush()
    return person


def link_user(s: Session, user: User) -> Person:
    """Link an OAuth account to a person using Toolhub's immutable user id."""
    person = ensure_person(
        s,
        display_name=user.username,
        toolhub_user_id=user.wm_sub,
        toolhub_username=user.username,
        source="toolhub_oauth",
    )
    person.display_name = user.username
    person.updated_at = utcnow()
    user.person_id = person.id
    return person


def replace_source_evidence(
    s: Session,
    tool_name: str,
    source: str,
    observations: list[dict[str, Any]],
) -> list[ToolRelationshipEvidence]:
    """Replace one source's observations and resolve the affected tool."""
    clean_tool = _clean(tool_name)
    now = utcnow()
    existing = list(
        s.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == clean_tool,
                ToolRelationshipEvidence.source == source,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    )
    for row in existing:
        row.withdrawn_at = now
        row.updated_at = now
    rows = []
    for observation in observations:
        role = _clean(observation.get("relationship_type"), 32) or PERSON_REL_AUTHOR
        method = _clean(observation.get("method"), 64)
        evidence_key = _clean(observation.get("evidence_key"), 255)
        display_scope = f"{clean_tool}\x1f{source}\x1f{role}\x1f{method}\x1f{evidence_key}"
        person = ensure_person(
            s,
            display_name=_clean(observation.get("display_name")),
            toolhub_user_id=_clean(observation.get("toolhub_user_id"), 64),
            toolhub_username=_clean(observation.get("toolhub_username")),
            wiki_username=_clean(observation.get("wiki_username")),
            source=source,
            checked_at=observation.get("checked_at"),
            display_scope=display_scope,
        )
        row = s.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == clean_tool,
                ToolRelationshipEvidence.person_id == person.id,
                ToolRelationshipEvidence.relationship_type == role,
                ToolRelationshipEvidence.source == source,
                ToolRelationshipEvidence.method == method,
                ToolRelationshipEvidence.evidence_key == evidence_key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = ToolRelationshipEvidence(
                tool_name=clean_tool,
                person_id=person.id,
                relationship_type=role,
                source=source,
                method=method,
                evidence_key=evidence_key,
                first_seen_at=observation.get("first_seen_at") or now,
            )
            s.add(row)
        row.verification_status = _clean(observation.get("verification_status"), 32) or AUTHOR_CLAIM_UNVERIFIED
        row.observed_name = _clean(observation.get("display_name"))
        row.confidence = max(0, min(100, int(observation.get("confidence") or 0)))
        row.toolhub_canonical = bool(observation.get("toolhub_canonical"))
        row.evidence_url = _clean(observation.get("evidence_url"), 2000) or None
        row.evidence_payload = observation.get("evidence_payload")
        row.checked_at = observation.get("checked_at") or now
        row.expires_at = observation.get("expires_at")
        row.withdrawn_at = None
        row.last_error = _clean(observation.get("last_error"), 2000) or None
        row.updated_at = now
        rows.append(row)
    s.flush()
    resolve_tool_relationships(s, clean_tool)
    return rows


def _resolved_status(evidence: list[ToolRelationshipEvidence]) -> str:
    now = utcnow()
    current = [row for row in evidence if row.expires_at is None or row.expires_at > now]
    statuses = {row.verification_status for row in current}
    if AUTHOR_CLAIM_VERIFIED in statuses:
        return AUTHOR_CLAIM_VERIFIED
    if current:
        return AUTHOR_CLAIM_UNVERIFIED if AUTHOR_CLAIM_UNVERIFIED in statuses else AUTHOR_CLAIM_FAILED
    return AUTHOR_CLAIM_STALE


def resolve_tool_relationships(s: Session, tool_name: str) -> list[ToolPersonRelationship]:
    """Collapse active evidence into one current row per person/tool/role."""
    clean_tool = _clean(tool_name)
    evidence = list(
        s.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == clean_tool,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    )
    grouped: dict[tuple[int, str], list[ToolRelationshipEvidence]] = {}
    for row in evidence:
        grouped.setdefault((row.person_id, row.relationship_type), []).append(row)
    current_rows = list(
        s.execute(select(ToolPersonRelationship).where(ToolPersonRelationship.tool_name == clean_tool)).scalars()
    )
    current = {(row.person_id, row.relationship_type): row for row in current_rows}
    affected_person_ids = {row.person_id for row in current_rows}
    for key, row in current.items():
        if key not in grouped:
            s.delete(row)
    now = utcnow()
    resolved = []
    for (person_id, role), supporting in grouped.items():
        row = current.get((person_id, role))
        if row is None:
            row = ToolPersonRelationship(tool_name=clean_tool, person_id=person_id, relationship_type=role)
            s.add(row)
        row.verification_status = _resolved_status(supporting)
        row.confidence = max(item.confidence for item in supporting)
        row.evidence_count = len(supporting)
        row.toolhub_canonical = any(item.toolhub_canonical for item in supporting)
        expiries = [item.expires_at for item in supporting if item.expires_at is not None]
        row.expires_at = None if len(expiries) != len(supporting) else max(expiries)
        row.resolved_at = now
        row.updated_at = now
        resolved.append(row)
    s.flush()
    affected_person_ids.update(row.person_id for row in resolved)
    refresh_activity_summaries(s, person_ids=affected_person_ids)
    return resolved


def _contribution_dates(s: Session, user_id: int) -> list[datetime]:
    """Return dates of public, substantive Evolved contributions only."""
    queries = (
        select(ToolRecord.modified_at).where(
            ToolRecord.user_id == user_id,
            ToolRecord.visibility == "public",
            ToolRecord.review_status == REVIEW_APPROVED,
            ToolRecord.deleted_at.is_(None),
        ),
        select(CatalogCuration.modified_at).where(
            CatalogCuration.created_by_user_id == user_id,
            CatalogCuration.review_status == REVIEW_APPROVED,
            CatalogCuration.deleted_at.is_(None),
        ),
        select(ToolOverlay.modified_at).where(
            ToolOverlay.user_id == user_id,
            ToolOverlay.review_status == REVIEW_APPROVED,
            ToolOverlay.deleted_at.is_(None),
        ),
        select(SourceAnalysisReport.reviewed_at).where(
            SourceAnalysisReport.user_id == user_id,
            SourceAnalysisReport.review_status == REVIEW_APPROVED,
        ),
        select(ActivityRow.created_at).where(
            ActivityRow.user_id == user_id,
            ActivityRow.kind == "revisions",
            ActivityRow.official_status == SYNC_OFFICIAL,
            ActivityRow.object_type != "favorite",
        ),
    )
    dates: list[datetime] = []
    for query in queries:
        dates.extend(value for (value,) in s.execute(query).all() if value is not None)
    return dates


def refresh_activity_summaries(s: Session, *, person_ids: set[int] | None = None) -> list[PersonActivitySummary]:
    """Refresh public contribution summaries, never private account activity."""
    ids = person_ids
    if ids is None:
        ids = {row[0] for row in s.execute(select(Person.id)).all()}
    if not ids:
        return []
    now = utcnow()
    recent_after = now - timedelta(days=RECENT_ACTIVITY_DAYS)
    summaries = []
    for person_id in sorted(ids):
        users = list(s.execute(select(User).where(User.person_id == person_id)).scalars())
        dates = [date for user in users for date in _contribution_dates(s, user.id)]
        relationships = list(
            s.execute(select(ToolPersonRelationship).where(ToolPersonRelationship.person_id == person_id)).scalars()
        )
        row = s.get(PersonActivitySummary, person_id)
        if row is None:
            row = PersonActivitySummary(person_id=person_id)
            s.add(row)
        row.related_tool_count = len({item.tool_name for item in relationships})
        row.verified_tool_count = len(
            {item.tool_name for item in relationships if item.verification_status == AUTHOR_CLAIM_VERIFIED}
        )
        row.contribution_count = len(dates)
        row.recent_contribution_count = sum(date >= recent_after for date in dates)
        row.last_contribution_at = max(dates) if dates else None
        age = (now - row.last_contribution_at).days if row.last_contribution_at else None
        row.activity_status = (
            "active"
            if age is not None and age <= ACTIVE_CONTRIBUTION_DAYS
            else ("quiet" if age is not None and age <= QUIET_CONTRIBUTION_DAYS else "unknown")
        )
        row.computed_at = now
        row.stale_at = now + timedelta(days=ACTIVITY_STALE_DAYS)
        summaries.append(row)
    return summaries


def activity_payload(row: PersonActivitySummary | None) -> dict[str, Any]:
    if row is None:
        return {"status": "unknown"}
    return {
        "status": row.activity_status or "unknown",
        "contributionCount": row.contribution_count,
        "recentContributionCount": row.recent_contribution_count,
        "relatedToolCount": row.related_tool_count,
        "verifiedToolCount": row.verified_tool_count,
        "lastContributionAgeDays": (utcnow() - row.last_contribution_at).days if row.last_contribution_at else None,
        "computedAt": row.computed_at.isoformat(timespec="seconds") + "Z" if row.computed_at else "",
    }


def _identifiers_by_person(s: Session, person_ids: set[int]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    rows = s.execute(
        select(PersonIdentifier)
        .where(PersonIdentifier.person_id.in_(person_ids or {-1}), PersonIdentifier.is_current.is_(True))
        .order_by(PersonIdentifier.namespace, PersonIdentifier.value)
    ).scalars()
    for row in rows:
        result.setdefault(row.person_id, []).append(
            {"namespace": row.namespace, "value": row.value, "kind": row.identifier_kind}
        )
    return result


def _person_base_payload(
    person: Person,
    identifiers: list[dict[str, Any]],
    profile: PersonProfile | None,
    activity: PersonActivitySummary | None,
) -> dict[str, Any]:
    return {
        "id": person.public_id,
        "displayName": person.display_name,
        "identityQuality": person.identity_quality,
        "identifiers": identifiers,
        "profile": {
            "bio": profile.bio,
            "avatarUrl": profile.avatar_url,
            "websiteUrl": profile.website_url,
            "location": profile.location,
            "links": profile.links if isinstance(profile.links, list) else [],
        }
        if profile is not None and profile.visibility == "public"
        else {},
        "activity": activity_payload(activity),
    }


def public_people_summary(s: Session, tool_name: str) -> dict[str, Any]:
    """Return the canonical local people view for a Toolhub tool."""
    clean_tool = _clean(tool_name)
    relationships = list(
        s.execute(
            select(ToolPersonRelationship)
            .where(ToolPersonRelationship.tool_name == clean_tool)
            .order_by(ToolPersonRelationship.confidence.desc(), ToolPersonRelationship.id)
        ).scalars()
    )
    person_ids = {row.person_id for row in relationships}
    people = {row.id: row for row in s.execute(select(Person).where(Person.id.in_(person_ids or {-1}))).scalars()}
    identifiers = _identifiers_by_person(s, person_ids)
    profiles = {
        row.person_id: row
        for row in s.execute(select(PersonProfile).where(PersonProfile.person_id.in_(person_ids or {-1}))).scalars()
    }
    activities = {
        row.person_id: row
        for row in s.execute(
            select(PersonActivitySummary).where(PersonActivitySummary.person_id.in_(person_ids or {-1}))
        ).scalars()
    }
    evidence = list(
        s.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name == clean_tool,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).scalars()
    )
    evidence_by_key: dict[tuple[int, str], list[ToolRelationshipEvidence]] = {}
    for item in evidence:
        evidence_by_key.setdefault((item.person_id, item.relationship_type), []).append(item)
    items_by_id: dict[int, dict[str, Any]] = {}
    for relationship in relationships:
        person = people.get(relationship.person_id)
        if person is None:
            continue
        payload = items_by_id.setdefault(
            person.id,
            _person_base_payload(
                person, identifiers.get(person.id, []), profiles.get(person.id), activities.get(person.id)
            )
            | {"relationships": []},
        )
        supporting = evidence_by_key.get((person.id, relationship.relationship_type), [])
        payload["relationships"].append(
            {
                "type": relationship.relationship_type,
                "status": relationship.verification_status,
                "confidence": relationship.confidence,
                "evidenceCount": relationship.evidence_count,
                "toolhubCanonical": relationship.toolhub_canonical,
                "evidence": [
                    {
                        "source": row.source,
                        "method": row.method,
                        "observedName": row.observed_name,
                        "status": row.verification_status,
                        "confidence": row.confidence,
                        "available": bool(row.evidence_url),
                    }
                    for row in supporting
                ],
            }
        )
    items = sorted(
        items_by_id.values(),
        key=lambda item: (-max((role["confidence"] for role in item["relationships"]), default=0), item["id"]),
    )
    counts = {
        role: sum(any(relationship["type"] == role for relationship in item["relationships"]) for item in items)
        for role in PUBLIC_ROLES
    }
    return {
        "toolName": clean_tool,
        "people": items,
        "counts": counts,
        "relationshipCount": len(relationships),
        "source": SOURCE_LOCAL,
        "syncStatus": "evolved_real",
        "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
    }


def person_detail(s: Session, public_id: str) -> dict[str, Any] | None:
    person = s.execute(select(Person).where(Person.public_id == _clean(public_id, 36))).scalar_one_or_none()
    if person is None:
        return None
    identifiers = _identifiers_by_person(s, {person.id}).get(person.id, [])
    profile = s.get(PersonProfile, person.id)
    activity = s.get(PersonActivitySummary, person.id)
    relationships = list(
        s.execute(
            select(ToolPersonRelationship)
            .where(ToolPersonRelationship.person_id == person.id)
            .order_by(ToolPersonRelationship.tool_name, ToolPersonRelationship.relationship_type)
        ).scalars()
    )
    tools: dict[str, list[dict[str, Any]]] = {}
    for row in relationships:
        tools.setdefault(row.tool_name, []).append(
            {
                "type": row.relationship_type,
                "status": row.verification_status,
                "confidence": row.confidence,
                "evidenceCount": row.evidence_count,
                "toolhubCanonical": row.toolhub_canonical,
            }
        )
    return _person_base_payload(person, identifiers, profile, activity) | {
        "tools": [{"name": name, "relationships": roles} for name, roles in tools.items()],
        "toolCount": len(tools),
        "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
    }


def find_people(s: Session, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
    clean_query = _clean(query)
    related_people = select(ToolPersonRelationship.person_id)
    profile_people = select(PersonProfile.person_id)
    statement = (
        select(Person)
        .where(or_(Person.id.in_(related_people), Person.id.in_(profile_people)))
        .order_by(Person.display_name, Person.public_id)
        .limit(max(1, min(limit, 100)))
    )
    if clean_query:
        matching_ids = select(PersonIdentifier.person_id).where(
            PersonIdentifier.normalized_value.like(f"%{_normalized(clean_query)}%")
        )
        statement = statement.where(
            or_(func.lower(Person.display_name).like(f"%{clean_query.casefold()}%"), Person.id.in_(matching_ids))
        )
    people = list(s.execute(statement).scalars())
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
    return [
        _person_base_payload(person, identifiers.get(person.id, []), profiles.get(person.id), activities.get(person.id))
        for person in people
    ]
