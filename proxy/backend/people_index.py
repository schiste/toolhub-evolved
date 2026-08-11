# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical Evolved people, relationship evidence, and public projections.

Toolhub remains authoritative for catalog records. This module records where a
fact came from, resolves identities, and materializes a local public view; none
of those rows grant or replace upstream Toolhub permissions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, func, or_, select

from backend import people_policy
from backend.models import (
    ActivityRow,
    CanonicalToolCache,
    CatalogCuration,
    CatalogFacetValue,
    CatalogToolProjection,
    Person,
    PersonActivitySummary,
    PersonIdentifier,
    PersonProfile,
    SourceAnalysisReport,
    ToolAssetCache,
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
NS_WIKIMEDIA_GLOBAL_USER_ID = "wikimedia_global_user_id"
NS_TOOLFORGE_UID_NUMBER = "toolforge_uid_number"
NS_TOOLHUB_USERNAME = "toolhub_username"
NS_TOOLFORGE_USERNAME = "toolforge_username"
NS_WIKI_USERNAME = "wiki_username"
PUBLIC_ROLES = (PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER, PERSON_REL_RECORD_OWNER, PERSON_REL_CATALOG_ACTOR)
PUBLIC_HANDLE_NAMESPACES = (NS_TOOLHUB_USERNAME, NS_TOOLFORGE_USERNAME, NS_WIKI_USERNAME)
TRUSTED_PUBLIC_HANDLE_SOURCES = (
    "evolved_author_claim",
    "toolhub_oauth",
    "toolforge_toolsadmin",
    "wikimedia_toolforge_bridge",
)
RECENT_ACTIVITY_DAYS = 90
ACTIVITY_STALE_DAYS = 1
ACTIVE_CONTRIBUTION_DAYS = 30
QUIET_CONTRIBUTION_DAYS = 180


@dataclass(frozen=True)
class PeopleDirectoryQuery:
    """Validated directory query passed from the HTTP boundary."""

    query: str = ""
    page: int = 1
    page_size: int = 24
    role: str = ""
    verification: str = ""
    activity: str = ""
    project: str = ""
    ordering: str = "relevance"
    contributor: bool = False
    public_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnresolvedAttributionQuery:
    """Search parameters for labels that do not identify a public person."""

    query: str = ""
    page: int = 1
    page_size: int = 10
    role: str = ""
    project: str = ""
    tool_name: str = ""


@dataclass(frozen=True)
class PersonToolPage:
    """Bounded tool page embedded in one public profile response."""

    page: int = 1
    page_size: int = 24


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - upstream values are untrusted
    return str(value or "").strip()[:limit]


def _normalized(value: Any) -> str:  # noqa: ANN401 - upstream values are untrusted
    return _clean(value).casefold()


def _iso(value: datetime | None) -> str:
    """Serialize stored UTC timestamps without exposing database details."""
    if value is None:
        return ""
    normalized = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value
    return normalized.isoformat(timespec="seconds") + "Z"


def public_relationship_payload(
    person: Person,
    relationship: ToolPersonRelationship,
    supporting: list[ToolRelationshipEvidence],
) -> dict[str, Any]:
    """Project one relationship and its public-safe provenance."""
    return {
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
                "identityBasis": person.identity_quality,
                "relationshipBasis": people_policy.relationship_basis(
                    relationship.relationship_type,
                    row.method,
                ),
                "checkedAt": _iso(row.checked_at),
                "expiresAt": _iso(row.expires_at),
            }
            for row in supporting
        ],
    }


def _canonical_key(  # noqa: PLR0911, PLR0913 - explicit identifiers define precedence
    *,
    toolhub_user_id: str = "",
    wikimedia_global_user_id: str = "",
    toolforge_uid_number: str = "",
    toolhub_username: str = "",
    toolforge_username: str = "",
    wiki_username: str = "",
    display: str = "",
    display_scope: str = "",
) -> str:
    if clean_id := _clean(toolhub_user_id, 64):
        return f"toolhub-id:{clean_id}"
    if clean_global_id := _clean(wikimedia_global_user_id, 64):
        return f"wikimedia-global-id:{clean_global_id}"
    if clean_toolforge_id := _clean(toolforge_uid_number, 64):
        return f"toolforge-uid-number:{clean_toolforge_id}"
    if clean_username := _normalized(toolhub_username):
        return f"toolhub:{clean_username}"
    if clean_toolforge := _normalized(toolforge_username):
        return f"toolforge:{clean_toolforge}"
    if clean_wiki := _normalized(wiki_username):
        return f"wiki:{clean_wiki}"
    display_key = _normalized(display)
    if display_scope:
        scope_hash = hashlib.sha256(_clean(display_scope, 2000).encode()).hexdigest()[:20]
        return f"display:{display_key}:{scope_hash}"
    return f"display:{display_key}"


def _identifier_spec(namespace: str) -> tuple[str, bool]:
    stable_namespaces = {NS_TOOLHUB_USER_ID, NS_WIKIMEDIA_GLOBAL_USER_ID, NS_TOOLFORGE_UID_NUMBER}
    return (IDENTIFIER_STABLE, True) if namespace in stable_namespaces else (IDENTIFIER_HANDLE, False)


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
    if source and (
        row.identifier_kind == IDENTIFIER_STABLE
        or row.source not in TRUSTED_PUBLIC_HANDLE_SOURCES
        or source in TRUSTED_PUBLIC_HANDLE_SOURCES
    ):
        # A canonical metadata refresh must not downgrade a handle previously
        # established by OAuth, Toolsadmin, or the stable identity bridge.
        row.source = source
    row.is_current = True
    row.last_seen_at = now
    row.retired_at = None
    row.updated_at = now
    return row


def _retire_superseded_handles(  # noqa: PLR0913 - each namespace retires independently
    s: Session,
    person: Person,
    *,
    toolhub_username: str,
    toolforge_username: str,
    wiki_username: str,
    retired_at: datetime,
) -> None:
    """Retire mutable handles superseded by a stable Toolhub identity."""
    for namespace, current_value in (
        (NS_TOOLHUB_USERNAME, toolhub_username),
        (NS_TOOLFORGE_USERNAME, toolforge_username),
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
    wikimedia_global_user_id: str = "",
    toolforge_uid_number: str = "",
    toolhub_username: str = "",
    toolforge_username: str = "",
    wiki_username: str = "",
    source: str = SOURCE_LOCAL,
    checked_at: datetime | None = None,
    display_scope: str = "",
) -> Person:
    """Resolve or create a person from strongest to weakest identity evidence."""
    # An immutable id is authoritative: a mutable handle owned by somebody
    # else must move to the stable identity, never select and merge that owner.
    stable_candidates = [
        _identifier_person(s, NS_TOOLHUB_USER_ID, toolhub_user_id),
        _identifier_person(s, NS_WIKIMEDIA_GLOBAL_USER_ID, wikimedia_global_user_id),
        _identifier_person(s, NS_TOOLFORGE_UID_NUMBER, toolforge_uid_number),
    ]
    candidates = (
        stable_candidates
        if _clean(toolhub_user_id, 64) or _clean(wikimedia_global_user_id, 64) or _clean(toolforge_uid_number, 64)
        else [
            _identifier_person(s, NS_TOOLHUB_USERNAME, toolhub_username),
            _identifier_person(s, NS_TOOLFORGE_USERNAME, toolforge_username),
            _identifier_person(s, NS_WIKI_USERNAME, wiki_username),
        ]
    )
    person = next((candidate for candidate in candidates if candidate is not None), None)
    display = _clean(display_name or toolhub_username or toolforge_username or wiki_username)
    if person is None:
        key = _canonical_key(
            toolhub_user_id=toolhub_user_id,
            wikimedia_global_user_id=wikimedia_global_user_id,
            toolforge_uid_number=toolforge_uid_number,
            toolhub_username=toolhub_username,
            toolforge_username=toolforge_username,
            wiki_username=wiki_username,
            display=display,
            display_scope=display_scope,
        )
        person = s.execute(select(Person).where(Person.canonical_key == key)).scalar_one_or_none()
    has_identity_evidence = bool(
        _clean(toolhub_user_id, 64)
        or _clean(wikimedia_global_user_id, 64)
        or _clean(toolforge_uid_number, 64)
        or _clean(toolhub_username)
        or _clean(toolforge_username)
        or _clean(wiki_username)
    )
    if person is None and display and not display_scope and not has_identity_evidence:
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
                wikimedia_global_user_id=wikimedia_global_user_id,
                toolforge_uid_number=toolforge_uid_number,
                toolhub_username=toolhub_username,
                toolforge_username=toolforge_username,
                wiki_username=wiki_username,
                display=display,
                display_scope=display_scope,
            ),
            display_name=display,
            identity_quality="stable"
            if toolhub_user_id or wikimedia_global_user_id or toolforge_uid_number
            else ("handle" if toolhub_username or toolforge_username or wiki_username else "display_name"),
        )
        s.add(person)
        s.flush()
    if display and (not person.display_name or person.identity_quality == "display_name"):
        person.display_name = display
    if toolhub_user_id or wikimedia_global_user_id or toolforge_uid_number:
        person.identity_quality = "stable"
        person.canonical_key = _canonical_key(
            toolhub_user_id=toolhub_user_id,
            wikimedia_global_user_id=wikimedia_global_user_id,
            toolforge_uid_number=toolforge_uid_number,
        )
    elif person.identity_quality == "display_name" and (toolhub_username or toolforge_username or wiki_username):
        person.identity_quality = "handle"
    person.updated_at = checked_at or utcnow()
    s.flush()
    if toolhub_user_id or wikimedia_global_user_id or toolforge_uid_number:
        _retire_superseded_handles(
            s,
            person,
            toolhub_username=toolhub_username,
            toolforge_username=toolforge_username,
            wiki_username=wiki_username,
            retired_at=checked_at or utcnow(),
        )
    for namespace, value in (
        (NS_TOOLHUB_USER_ID, toolhub_user_id),
        (NS_WIKIMEDIA_GLOBAL_USER_ID, wikimedia_global_user_id),
        (NS_TOOLFORGE_UID_NUMBER, toolforge_uid_number),
        (NS_TOOLHUB_USERNAME, toolhub_username),
        (NS_TOOLFORGE_USERNAME, toolforge_username),
        (NS_WIKI_USERNAME, wiki_username),
    ):
        _upsert_identifier(
            s,
            person,
            namespace=namespace,
            value=value,
            source=source,
            checked_at=checked_at,
            authoritative_reassignment=bool(
                (toolhub_user_id or wikimedia_global_user_id or toolforge_uid_number)
                and namespace not in {NS_TOOLHUB_USER_ID, NS_WIKIMEDIA_GLOBAL_USER_ID, NS_TOOLFORGE_UID_NUMBER}
            ),
        )
    s.flush()
    return person


def ensure_official_account_person(
    s: Session,
    *,
    toolhub_user_id: str,
    username: str,
    wikimedia_global_user_id: str = "",
    checked_at: datetime | None = None,
) -> Person | None:
    """Materialize a public account identity unless its stable ids conflict."""
    toolhub_owner = _identifier_person(s, NS_TOOLHUB_USER_ID, toolhub_user_id)
    wikimedia_owner = _identifier_person(s, NS_WIKIMEDIA_GLOBAL_USER_ID, wikimedia_global_user_id)
    if toolhub_owner is not None and wikimedia_owner is not None and toolhub_owner.id != wikimedia_owner.id:
        return None
    person = ensure_person(
        s,
        display_name=username,
        toolhub_user_id=toolhub_user_id,
        wikimedia_global_user_id=wikimedia_global_user_id,
        toolhub_username=username,
        source="toolhub_public_account",
        checked_at=checked_at,
    )
    person.display_name = _clean(username)
    person.updated_at = checked_at or utcnow()
    return person


def link_user(s: Session, user: User) -> Person:
    """Link an OAuth account to a person using Toolhub's immutable user id."""
    person = ensure_person(
        s,
        display_name=user.username,
        toolhub_user_id=user.wm_sub,
        wikimedia_global_user_id=user.wikimedia_global_user_id or "",
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
            toolforge_username=_clean(observation.get("toolforge_username")),
            wiki_username=_clean(observation.get("wiki_username")),
            source=source,
            checked_at=observation.get("checked_at"),
            display_scope=display_scope,
        )
        identity_decision = people_policy.decide_identity_link(
            same_stable_identifier=bool(
                _clean(observation.get("toolhub_user_id"), 64)
                or _clean(observation.get("wikimedia_global_user_id"), 64)
            ),
            structured_handle=bool(
                _clean(observation.get("toolhub_username"))
                or _clean(observation.get("toolforge_username"))
                or _clean(observation.get("wiki_username"))
            ),
            authenticated_claim=bool(observation.get("authenticated_claim")),
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
        raw_payload = observation.get("evidence_payload")
        evidence_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        evidence_payload["identityResolution"] = {
            "action": identity_decision.action,
            "reason": identity_decision.reason,
        }
        row.evidence_payload = evidence_payload
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


def _public_identity_clause() -> Any:  # noqa: ANN401 - SQLAlchemy boolean expression
    identifier_people = select(PersonIdentifier.person_id).where(
        PersonIdentifier.is_current.is_(True),
        or_(
            PersonIdentifier.identifier_kind == IDENTIFIER_STABLE,
            and_(
                PersonIdentifier.identifier_kind == IDENTIFIER_HANDLE,
                PersonIdentifier.source.in_(TRUSTED_PUBLIC_HANDLE_SOURCES),
            ),
        ),
    )
    profile_people = select(PersonProfile.person_id)
    return or_(Person.id.in_(identifier_people), Person.id.in_(profile_people))


def public_identity_ids(s: Session, person_ids: set[int] | None = None) -> set[int]:
    """Return identities safe to publish as people, based on current evidence."""
    statement = select(Person.id).where(_public_identity_clause())
    if person_ids is not None:
        statement = statement.where(Person.id.in_(person_ids or {-1}))
    return {row[0] for row in s.execute(statement).all()}


def refresh_identity_qualities(s: Session) -> int:
    """Repair denormalized quality labels from current identifier evidence."""
    kinds_by_person: dict[int, set[str]] = {}
    rows = s.execute(
        select(PersonIdentifier.person_id, PersonIdentifier.identifier_kind).where(
            PersonIdentifier.is_current.is_(True)
        )
    ).all()
    for person_id, kind in rows:
        kinds_by_person.setdefault(person_id, set()).add(kind)
    touched = 0
    for person in s.execute(select(Person).order_by(Person.id)).scalars():
        kinds = kinds_by_person.get(person.id, set())
        quality = (
            "stable" if IDENTIFIER_STABLE in kinds else ("handle" if IDENTIFIER_HANDLE in kinds else "display_name")
        )
        if person.identity_quality != quality:
            person.identity_quality = quality
            person.updated_at = utcnow()
            touched += 1
    return touched


def unresolved_attributions(
    s: Session,
    query: str = "",
    *,
    limit: int = 50,
    tool_name: str = "",
) -> list[dict[str, Any]]:
    """Aggregate display-only relationship evidence without inventing people."""
    return search_unresolved_attributions(
        s,
        UnresolvedAttributionQuery(
            query=query,
            page=1,
            page_size=limit,
            tool_name=tool_name,
        ),
    )["results"]


def _unresolved_relationship_breakdown(
    s: Session,
    normalized_labels: set[str],
    *,
    tool_name: str,
    project: str,
    role: str,
) -> dict[str, list[dict[str, Any]]]:
    """Summarize relationship evidence without promoting labels to identities."""
    if not normalized_labels:
        return {}
    normalized_label = func.lower(Person.display_name)
    statement = (
        select(
            normalized_label,
            ToolPersonRelationship.relationship_type,
            ToolPersonRelationship.verification_status,
            func.count(func.distinct(ToolPersonRelationship.tool_name)),
            func.sum(ToolPersonRelationship.evidence_count),
            func.max(ToolPersonRelationship.confidence),
        )
        .join(ToolPersonRelationship, ToolPersonRelationship.person_id == Person.id)
        .where(~_public_identity_clause(), normalized_label.in_(normalized_labels))
        .group_by(
            normalized_label,
            ToolPersonRelationship.relationship_type,
            ToolPersonRelationship.verification_status,
        )
    )
    if tool_name:
        statement = statement.where(ToolPersonRelationship.tool_name == tool_name)
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

    result: dict[str, list[dict[str, Any]]] = {}
    for label, relationship_type, status, tool_count, evidence_count, confidence in s.execute(statement).all():
        result.setdefault(label, []).append(
            {
                "type": relationship_type,
                "status": status,
                "toolCount": int(tool_count or 0),
                "evidenceCount": int(evidence_count or 0),
                "bestConfidence": int(confidence or 0),
            }
        )
    status_order = {AUTHOR_CLAIM_VERIFIED: 0, AUTHOR_CLAIM_STALE: 1, AUTHOR_CLAIM_UNVERIFIED: 2}
    role_order = {value: index for index, value in enumerate(PUBLIC_ROLES)}
    for rows in result.values():
        rows.sort(
            key=lambda item: (
                role_order.get(item["type"], len(role_order)),
                status_order.get(item["status"], len(status_order)),
            )
        )
    return result


def search_unresolved_attributions(
    s: Session,
    search: UnresolvedAttributionQuery,
) -> dict[str, Any]:
    """Search unresolved labels with totals independent from public people."""
    clean_query = _clean(search.query)
    clean_tool = _clean(search.tool_name)
    normalized_label = func.lower(Person.display_name)
    statement = (
        select(
            normalized_label.label("normalized_label"),
            func.min(Person.display_name).label("label"),
            func.count(func.distinct(Person.id)).label("attribution_count"),
            func.count(func.distinct(ToolPersonRelationship.tool_name)).label("tool_count"),
            func.sum(ToolPersonRelationship.evidence_count).label("evidence_count"),
            func.max(ToolPersonRelationship.confidence).label("best_confidence"),
        )
        .join(ToolPersonRelationship, ToolPersonRelationship.person_id == Person.id)
        .where(~_public_identity_clause(), Person.display_name != "")
        .group_by(normalized_label)
        .order_by(normalized_label)
    )
    if search.project:
        statement = statement.join(
            CatalogFacetValue,
            CatalogFacetValue.tool_name == ToolPersonRelationship.tool_name,
        ).where(
            CatalogFacetValue.field == "wiki",
            func.lower(CatalogFacetValue.value) == search.project.casefold(),
        )
    if search.role:
        statement = statement.where(ToolPersonRelationship.relationship_type == search.role)
    if clean_query:
        statement = statement.where(normalized_label.like(f"%{clean_query.casefold()}%"))
    if clean_tool:
        statement = statement.where(ToolPersonRelationship.tool_name == clean_tool)
    total = int(s.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)
    safe_page = max(1, search.page)
    safe_page_size = max(1, min(search.page_size, 100))
    rows = list(s.execute(statement.offset((safe_page - 1) * safe_page_size).limit(safe_page_size)).all())
    relationship_breakdown = _unresolved_relationship_breakdown(
        s,
        {row.normalized_label for row in rows},
        tool_name=clean_tool,
        project=search.project,
        role=search.role,
    )
    results = [
        {
            "label": row.label,
            "identityStatus": "unresolved_attribution",
            "attributionCount": row.attribution_count,
            "toolCount": row.tool_count,
            "evidenceCount": row.evidence_count or 0,
            "bestConfidence": row.best_confidence or 0,
            "relationshipTypes": list(
                dict.fromkeys(item["type"] for item in relationship_breakdown.get(row.normalized_label, []))
            ),
            "relationshipBreakdown": relationship_breakdown.get(row.normalized_label, []),
        }
        for row in rows
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


def _person_base_payload(
    person: Person,
    identifiers: list[dict[str, Any]],
    profile: PersonProfile | None,
    activity: PersonActivitySummary | None,
) -> dict[str, Any]:
    identity_quality = (
        "stable"
        if any(identifier.get("kind") == IDENTIFIER_STABLE for identifier in identifiers)
        else (
            IDENTIFIER_HANDLE
            if any(identifier.get("kind") == IDENTIFIER_HANDLE for identifier in identifiers)
            else "profile"
        )
    )
    return {
        "id": person.public_id,
        "displayName": person.display_name,
        "identityQuality": identity_quality,
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


def resolve_legacy_handle(s: Session, query: str) -> dict[str, Any]:
    """Resolve one exact structured handle or return explicit ambiguity."""
    clean_query = _clean(query)
    normalized = _normalized(clean_query)
    if not normalized:
        return {"status": "not_found", "query": clean_query, "matchType": "none", "candidates": []}
    handle_rows = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.namespace.in_(PUBLIC_HANDLE_NAMESPACES),
                PersonIdentifier.normalized_value == normalized,
                PersonIdentifier.is_current.is_(True),
            )
        ).scalars()
    )
    handle_person_ids = public_identity_ids(s, {row.person_id for row in handle_rows})
    matched_namespaces: dict[int, set[str]] = {}
    for row in handle_rows:
        if row.person_id in handle_person_ids:
            matched_namespaces.setdefault(row.person_id, set()).add(row.namespace)

    match_type = "handle"
    candidate_ids = set(handle_person_ids)
    if not candidate_ids:
        display_ids = {
            row[0] for row in s.execute(select(Person.id).where(func.lower(Person.display_name) == normalized)).all()
        }
        candidate_ids = public_identity_ids(s, display_ids)
        match_type = "display_name" if candidate_ids else "none"

    people = list(
        s.execute(
            select(Person).where(Person.id.in_(candidate_ids or {-1})).order_by(Person.display_name, Person.public_id)
        ).scalars()
    )
    identifiers = _identifiers_by_person(s, candidate_ids)
    profiles = {
        row.person_id: row
        for row in s.execute(
            select(PersonProfile).where(
                PersonProfile.person_id.in_(candidate_ids or {-1}),
                PersonProfile.visibility == "public",
            )
        ).scalars()
    }
    activities = {
        row.person_id: row
        for row in s.execute(
            select(PersonActivitySummary).where(PersonActivitySummary.person_id.in_(candidate_ids or {-1}))
        ).scalars()
    }
    candidates = [
        _person_base_payload(person, identifiers.get(person.id, []), profiles.get(person.id), activities.get(person.id))
        | {"matchedNamespaces": sorted(matched_namespaces.get(person.id, set()))}
        for person in people
    ]
    unresolved = [
        attribution
        for attribution in unresolved_attributions(s, clean_query, limit=100)
        if _normalized(attribution.get("label")) == normalized
    ]
    if match_type == "handle" and len(candidates) == 1:
        return {
            "status": "resolved",
            "query": clean_query,
            "matchType": match_type,
            "person": candidates[0],
            "candidates": candidates,
            "unresolvedAttributions": unresolved,
        }
    if candidates or unresolved:
        return {
            "status": "ambiguous",
            "query": clean_query,
            "matchType": match_type,
            "candidates": candidates,
            "unresolvedAttributions": unresolved,
        }
    return {
        "status": "not_found",
        "query": clean_query,
        "matchType": "none",
        "candidates": [],
        "unresolvedAttributions": [],
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
    all_person_ids = {row.person_id for row in relationships}
    person_ids = public_identity_ids(s, all_person_ids)
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
            select(ToolRelationshipEvidence)
            .where(
                ToolRelationshipEvidence.tool_name == clean_tool,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
            .order_by(ToolRelationshipEvidence.checked_at.desc(), ToolRelationshipEvidence.id)
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
        payload["relationships"].append(public_relationship_payload(person, relationship, supporting))
    items = sorted(
        items_by_id.values(),
        key=lambda item: (-max((role["confidence"] for role in item["relationships"]), default=0), item["id"]),
    )
    counts = {
        role: sum(any(relationship["type"] == role for relationship in item["relationships"]) for item in items)
        for role in PUBLIC_ROLES
    }
    unresolved = unresolved_attributions(s, tool_name=clean_tool, limit=100)
    unresolved_counts = {role: sum(role in item["relationshipTypes"] for item in unresolved) for role in PUBLIC_ROLES}
    return {
        "toolName": clean_tool,
        "people": items,
        "counts": counts,
        "unresolvedAttributions": unresolved,
        "unresolvedCounts": unresolved_counts,
        "resolvedRelationshipCount": sum(len(item["relationships"]) for item in items),
        "relationshipCount": len(relationships),
        "source": SOURCE_LOCAL,
        "syncStatus": "evolved_real",
        "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
    }


PROFILE_TOOL_FIELDS = (
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
    "modified_date",
    "license",
    "repository",
    "user_docs_url",
    "developer_docs_url",
    "feedback_url",
    "bugtracker_url",
    "translate_url",
    "technology_used",
    "audiences",
    "tasks",
    "available_ui_languages",
    "author",
    "created_by",
)


def _compact_profile_tool(
    name: str,
    canonical: CanonicalToolCache | None,
    projection: CatalogToolProjection | None,
    asset: ToolAssetCache | None,
) -> tuple[dict[str, Any], str]:
    canonical_record = canonical.record if canonical is not None and isinstance(canonical.record, dict) else {}
    projected_record = (
        projection.effective_record if projection is not None and isinstance(projection.effective_record, dict) else {}
    )
    combined = {**canonical_record, **projected_record}
    if not combined:
        return (
            {
                "name": name,
                "title": name,
                "description": "",
                "origin": "profile_relationship",
                "_missingCanonical": True,
            },
            "missing",
        )
    summary = {field: combined[field] for field in PROFILE_TOOL_FIELDS if field in combined}
    summary["name"] = name
    summary["origin"] = "canonical_cache"
    if asset is not None and asset.status == "ready":
        summary["_cachedIconUrl"] = f"/v1/catalog/tools/{name}/icon/"
    return summary, "available"


def person_detail(
    s: Session,
    public_id: str,
    tool_page: PersonToolPage | None = None,
) -> dict[str, Any] | None:
    person = s.execute(select(Person).where(Person.public_id == _clean(public_id, 36))).scalar_one_or_none()
    if person is None or person.id not in public_identity_ids(s, {person.id}):
        return None
    requested = tool_page or PersonToolPage()
    requested_page = max(1, requested.page)
    page_size = max(1, min(requested.page_size, 50))
    identifiers = _identifiers_by_person(s, {person.id}).get(person.id, [])
    profile = s.get(PersonProfile, person.id)
    activity = s.get(PersonActivitySummary, person.id)
    tool_names_statement = (
        select(ToolPersonRelationship.tool_name)
        .where(ToolPersonRelationship.person_id == person.id)
        .group_by(ToolPersonRelationship.tool_name)
    )
    tool_count = int(s.scalar(select(func.count()).select_from(tool_names_statement.order_by(None).subquery())) or 0)
    page_count = max(1, (tool_count + page_size - 1) // page_size)
    page = min(requested_page, page_count)
    tool_names = list(
        s.execute(
            tool_names_statement.order_by(ToolPersonRelationship.tool_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    relationships = list(
        s.execute(
            select(ToolPersonRelationship)
            .where(
                ToolPersonRelationship.person_id == person.id,
                ToolPersonRelationship.tool_name.in_(tool_names or {""}),
            )
            .order_by(ToolPersonRelationship.tool_name, ToolPersonRelationship.relationship_type)
        ).scalars()
    )
    evidence = list(
        s.execute(
            select(ToolRelationshipEvidence)
            .where(
                ToolRelationshipEvidence.person_id == person.id,
                ToolRelationshipEvidence.tool_name.in_(tool_names or {""}),
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
            .order_by(ToolRelationshipEvidence.checked_at.desc(), ToolRelationshipEvidence.id)
        ).scalars()
    )
    evidence_by_key: dict[tuple[str, str], list[ToolRelationshipEvidence]] = {}
    for item in evidence:
        evidence_by_key.setdefault((item.tool_name, item.relationship_type), []).append(item)
    roles_by_tool: dict[str, list[dict[str, Any]]] = {}
    for row in relationships:
        roles_by_tool.setdefault(row.tool_name, []).append(
            public_relationship_payload(
                person,
                row,
                evidence_by_key.get((row.tool_name, row.relationship_type), []),
            )
        )
    canonical_by_name = {
        row.tool_name: row
        for row in s.execute(
            select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(tool_names or {""}))
        ).scalars()
    }
    projections_by_name = {
        row.tool_name: row
        for row in s.execute(
            select(CatalogToolProjection).where(CatalogToolProjection.tool_name.in_(tool_names or {""}))
        ).scalars()
    }
    assets_by_name = {
        row.tool_name: row
        for row in s.execute(select(ToolAssetCache).where(ToolAssetCache.tool_name.in_(tool_names or {""}))).scalars()
    }
    tools = []
    for name in tool_names:
        summary, summary_status = _compact_profile_tool(
            name,
            canonical_by_name.get(name),
            projections_by_name.get(name),
            assets_by_name.get(name),
        )
        tools.append(
            {
                "name": name,
                "summary": summary,
                "summaryStatus": summary_status,
                "relationships": roles_by_tool.get(name, []),
            }
        )
    return _person_base_payload(person, identifiers, profile, activity) | {
        "tools": {
            "count": tool_count,
            "page": page,
            "pageSize": page_size,
            "pageCount": page_count,
            "nextPage": page + 1 if page < page_count else None,
            "previousPage": page - 1 if page > 1 else None,
            "results": tools,
        },
        "toolCount": tool_count,
        "canonicalAuthority": {"catalog": "toolhub", "profiles": "toolhub-evolved"},
    }


def find_people(s: Session, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that only need the first page."""
    return search_people_directory(
        s,
        PeopleDirectoryQuery(query=query, page=1, page_size=limit),
    )["results"]


def _current_verified_clause(*, checked_at: datetime) -> Any:  # noqa: ANN401 - SQL expression
    return and_(
        ToolPersonRelationship.verification_status == AUTHOR_CLAIM_VERIFIED,
        or_(
            ToolPersonRelationship.expires_at.is_(None),
            ToolPersonRelationship.expires_at > checked_at,
        ),
    )


def _relationship_directory_filter(
    *,
    role: str,
    verification: str,
    project: str,
    checked_at: datetime,
) -> Any:  # noqa: ANN401 - correlated SQL expression
    statement = select(ToolPersonRelationship.id).where(ToolPersonRelationship.person_id == Person.id)
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
        select(ToolPersonRelationship).where(ToolPersonRelationship.person_id.in_(person_ids or {-1}))
    ).scalars()
    for row in rows:
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
            "bases": bases,
            "catalogActorToolCount": int(actor_counts.get(person_id, 0)),
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
    related_people = select(ToolPersonRelationship.person_id)
    profile_people = select(PersonProfile.person_id)
    statement = (
        select(Person)
        .outerjoin(PersonActivitySummary, PersonActivitySummary.person_id == Person.id)
        .where(
            or_(Person.id.in_(related_people), Person.id.in_(profile_people)),
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
    safe_page_size = max(1, min(search.page_size, 100))
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
