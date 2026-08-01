# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalized people and typed tool relationships.

People are deduplicated by stable usernames where available. Roles are kept on
tool relationships, because the same person may author one tool, maintain
another, and own an official Toolhub record without those roles being
interchangeable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from backend.models import (
    MaintainerActivityRollup,
    Person,
    PersonIdentifier,
    ToolMaintainerEdge,
    ToolPersonRelationship,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_UNVERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_CATALOG_ACTOR,
    PERSON_REL_MAINTAINER,
    PERSON_REL_RECORD_OWNER,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - untrusted upstream values
    return str(value or "").strip()[:limit]


def _normalized(value: str) -> str:
    return _clean(value).casefold()


def relationship_type(edge: ToolMaintainerEdge) -> str:
    """Map legacy edge provenance to the least-strong truthful role."""
    source_roles = {
        "toolhub_author_metadata": PERSON_REL_AUTHOR,
        "toolhub_catalog_actor": PERSON_REL_RECORD_OWNER
        if edge.method == "toolhub_catalog_actor"
        else PERSON_REL_CATALOG_ACTOR,
    }
    method_roles = {
        AUTHOR_CLAIM_TOOLFORGE_MAINTAINER: PERSON_REL_MAINTAINER,
        AUTHOR_CLAIM_SIGNED_TOOLINFO: PERSON_REL_MAINTAINER,
        AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS: PERSON_REL_RECORD_OWNER,
        AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME: PERSON_REL_AUTHOR,
    }
    return source_roles.get(edge.source, method_roles.get(edge.method, PERSON_REL_MAINTAINER))


def _stable_identifiers(edge: ToolMaintainerEdge) -> list[tuple[str, str]]:
    identifiers = []
    if _clean(edge.toolhub_username):
        identifiers.append(("toolhub", _clean(edge.toolhub_username)))
    if _clean(edge.wiki_username):
        identifiers.append(("wiki", _clean(edge.wiki_username)))
    return identifiers


def _identifier_priority(namespace: str) -> tuple[int, str]:
    return ({"toolhub": 0, "wiki": 1}.get(namespace, 9), namespace)


def _person_candidates(s: Session, edge: ToolMaintainerEdge) -> list[Person]:
    candidates: dict[int, Person] = {}
    key = _clean(edge.maintainer_key)
    if key:
        row = s.execute(select(Person).where(Person.canonical_key == key)).scalar_one_or_none()
        if row is not None:
            candidates[row.id] = row
    for namespace, value in _stable_identifiers(edge):
        identifier = s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace == namespace,
                PersonIdentifier.normalized_value == _normalized(value),
            )
        ).scalar_one_or_none()
        if identifier is None:
            continue
        row = s.get(Person, identifier.person_id)
        if row is not None:
            candidates[row.id] = row
    return sorted(
        candidates.values(),
        key=lambda row: (_identifier_priority(row.canonical_key.split(":", 1)[0])[0], row.id),
    )


def _find_person(s: Session, edge: ToolMaintainerEdge) -> Person | None:
    candidates = _person_candidates(s, edge)
    if candidates:
        return candidates[0]
    display = _clean(edge.maintainer_display_name or edge.author_name)
    if not display:
        return None
    # A display-only person can be upgraded when a stable Toolhub identity
    # later appears. This is deliberately limited to one exact fallback row.
    candidates = list(
        s.execute(
            select(Person).where(
                func.lower(Person.display_name) == display.casefold(),
                Person.identity_quality == "display_name",
            )
        ).scalars()
    )
    return candidates[0] if len(candidates) == 1 else None


def _upsert_person(s: Session, edge: ToolMaintainerEdge) -> Person:
    key = _clean(edge.maintainer_key)
    display = _clean(edge.maintainer_display_name or edge.author_name or edge.toolhub_username)
    person = _find_person(s, edge)
    stable = bool(_stable_identifiers(edge))
    if person is None:
        person = Person(
            canonical_key=key or f"display:{_normalized(display)}",
            display_name=display,
            identity_quality="stable" if stable else "display_name",
        )
        s.add(person)
        s.flush()
    elif key and person.canonical_key != key and stable and person.identity_quality == "display_name":
        person.canonical_key = key
        person.identity_quality = "stable"
    if display and (not person.display_name or person.identity_quality == "display_name"):
        person.display_name = display
    if stable:
        person.identity_quality = "stable"
    person.updated_at = utcnow()
    s.flush()
    for namespace, value in _stable_identifiers(edge):
        normalized = _normalized(value)
        existing = s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace == namespace,
                PersonIdentifier.normalized_value == normalized,
            )
        ).scalar_one_or_none()
        if existing is None:
            s.add(PersonIdentifier(person_id=person.id, namespace=namespace, value=value, normalized_value=normalized))
        elif existing.person_id != person.id:
            # A conflicting stable identity is never auto-merged. The existing
            # identifier wins until an explicit reconciliation can review it.
            continue
    s.flush()
    return person


def _upsert_relationship(s: Session, edge: ToolMaintainerEdge, person: Person) -> ToolPersonRelationship:
    role = relationship_type(edge)
    row = s.execute(
        select(ToolPersonRelationship).where(
            ToolPersonRelationship.tool_name == edge.tool_name,
            ToolPersonRelationship.person_id == person.id,
            ToolPersonRelationship.relationship_type == role,
            ToolPersonRelationship.source == edge.source,
            ToolPersonRelationship.method == edge.method,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ToolPersonRelationship(
            tool_name=edge.tool_name,
            person_id=person.id,
            relationship_type=role,
            source=edge.source,
            method=edge.method,
        )
        s.add(row)
    row.verification_status = edge.verification_status or AUTHOR_CLAIM_UNVERIFIED
    row.confidence = max(0, min(100, int(edge.confidence or 0)))
    row.evidence_url = edge.evidence_url[:2000] if edge.evidence_url else None
    row.checked_at = edge.checked_at or utcnow()
    row.expires_at = edge.expires_at
    row.updated_at = utcnow()
    s.flush()
    return row


def sync_tool_people(s: Session, tool_name: str) -> list[ToolPersonRelationship]:
    """Rebuild typed relationships for a tool from the compatibility edges."""
    clean_name = _clean(tool_name)
    # synchronize_session: a bulk DELETE bypasses the identity map, so rows this
    # session already loaded stay behind as live persistent objects. The upsert
    # below would then find one, mutate it, and flush an UPDATE for a row that
    # no longer exists — StaleDataError, which surfaced as a 500 on /v1/me/tools/.
    s.execute(
        delete(ToolPersonRelationship).where(ToolPersonRelationship.tool_name == clean_name),
        execution_options={"synchronize_session": "fetch"},
    )
    edges = list(
        s.execute(
            select(ToolMaintainerEdge)
            .where(ToolMaintainerEdge.tool_name == clean_name)
            .order_by(ToolMaintainerEdge.confidence.desc(), ToolMaintainerEdge.id)
        ).scalars()
    )
    return [_upsert_relationship(s, edge, _upsert_person(s, edge)) for edge in edges]


def _activity_payload(rollup: Any) -> dict[str, Any]:  # noqa: ANN401 - optional SQLAlchemy model
    if rollup is None:
        return {"status": "unknown"}
    return {
        "status": rollup.activity_status or "unknown",
        "recentActivityCount": rollup.recent_activity_count,
        "activeToolCount": rollup.active_tool_count,
        "verifiedToolCount": rollup.verified_tool_count,
        "lastActivityAgeDays": (utcnow() - rollup.last_activity_at).days if rollup.last_activity_at else None,
    }


def public_people_summary(s: Session, tool_name: str) -> dict[str, Any]:
    """Return public-safe people and typed relationships for one tool."""
    clean_name = _clean(tool_name)
    relationships = list(
        s.execute(
            select(ToolPersonRelationship)
            .where(ToolPersonRelationship.tool_name == clean_name)
            .order_by(ToolPersonRelationship.confidence.desc(), ToolPersonRelationship.id)
        ).scalars()
    )
    people_by_id: dict[int, dict[str, Any]] = {}
    person_ids = {row.person_id for row in relationships}
    people = {
        row.id: row for row in s.execute(select(Person).where(Person.id.in_(person_ids or {-1}))).scalars()
    }
    identifiers = {}
    for row in s.execute(select(PersonIdentifier).where(PersonIdentifier.person_id.in_(person_ids or {-1}))).scalars():
        identifiers.setdefault(row.person_id, []).append({"namespace": row.namespace, "value": row.value})
    rollups = {
        row.maintainer_key: row
        for row in s.execute(select(MaintainerActivityRollup)).scalars()
    }
    for row in relationships:
        person = people.get(row.person_id)
        if person is None:
            continue
        payload = people_by_id.setdefault(
            person.id,
            {
                "id": person.canonical_key,
                "displayName": person.display_name,
                "identityQuality": person.identity_quality,
                "identifiers": identifiers.get(person.id, []),
                "relationships": [],
            },
        )
        payload["relationships"].append(
            {
                "type": row.relationship_type,
                "status": row.verification_status,
                "confidence": row.confidence,
                "source": row.source,
                "method": row.method,
                "activity": _activity_payload(rollups.get(person.canonical_key)),
                "evidenceAvailable": bool(row.evidence_url),
            }
        )
    items = sorted(
        people_by_id.values(),
        key=lambda item: (-max((r["confidence"] for r in item["relationships"]), default=0), item["id"]),
    )
    roles = (PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER, PERSON_REL_RECORD_OWNER, PERSON_REL_CATALOG_ACTOR)
    counts = {
        role: sum(1 for item in items if any(r["type"] == role for r in item["relationships"]))
        for role in roles
    }
    return {
        "people": items,
        "counts": counts,
        "relationshipCount": len(relationships),
        "identityPolicy": {
            "stableIdentifiers": ["toolhub", "wiki"],
            "displayNameFallback": "heuristic",
            "canonical": False,
        },
    }
