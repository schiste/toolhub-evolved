# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic reconciliation for canonical people and evidence projections."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import db, maintainer_index, people_index, people_policy
from backend.author_claims import ToolforgeMembershipProvider
from backend.models import (
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationQueue,
    PersonReconciliationRun,
    ToolAuthorClaim,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    User,
    utcnow,
)
from backend.people_identity import ToolhubIdentityProvider

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MODE_DRY_RUN = "dry-run"
MODE_APPLY = "apply"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
DEFAULT_QUEUE_LIMIT = 100
DEFAULT_CANDIDATE_LABEL_LIMIT = 25
MAPPING_CANDIDATE = people_policy.ACTION_CANDIDATE
MAPPING_APPROVED = "approved"
MAPPING_REJECTED = "rejected"
MAPPING_SPLIT = "split"
MAPPING_DECISIONS = {MAPPING_CANDIDATE, MAPPING_APPROVED, MAPPING_REJECTED, MAPPING_SPLIT}


class PersonReconciliationError(ValueError):
    """Invalid reconciliation mode."""


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - untrusted stored data
    return str(value or "").strip()[:limit]


def enqueue_tool_names(tool_names: list[str], *, reason: str = "data_ingestion") -> int:
    names = sorted({_clean(name) for name in tool_names if _clean(name)})
    if not names:
        return 0
    now = utcnow()
    with db.session_scope() as s:
        for name in names:
            row = s.get(PersonReconciliationQueue, name)
            if row is None:
                s.add(PersonReconciliationQueue(tool_name=name, reason=_clean(reason, 64), enqueued_at=now))
            else:
                row.reason = _clean(reason, 64) or row.reason
                row.enqueued_at = now
                row.next_attempt_at = None
                row.last_error = None
    return len(names)


def _reconcile_tool(s: Session, name: str) -> None:
    cache = s.get(CanonicalToolCache, name)
    if cache is not None and isinstance(cache.record, dict):
        maintainer_index.replace_toolhub_metadata_edges(s, name, cache.record)
    maintainer_index.sync_author_claim_edges(s, tool_names=[name])
    apply_approved_mappings_for_tool(s, name)
    people_index.resolve_tool_relationships(s, name)


def _same_evidence_query(row: ToolRelationshipEvidence, target_person_id: int) -> Any:  # noqa: ANN401
    return select(ToolRelationshipEvidence).where(
        ToolRelationshipEvidence.tool_name == row.tool_name,
        ToolRelationshipEvidence.person_id == target_person_id,
        ToolRelationshipEvidence.relationship_type == row.relationship_type,
        ToolRelationshipEvidence.source == row.source,
        ToolRelationshipEvidence.method == row.method,
        ToolRelationshipEvidence.evidence_key == row.evidence_key,
    )


def _move_mapping_evidence(
    s: Session,
    mapping: PersonReconciliationMapping,
    *,
    tool_name: str | None = None,
) -> set[str]:
    """Move provenance to an approved stable identity without changing roles."""
    if mapping.source_person_id is None or mapping.target_person_id is None:
        return set()
    statement = select(ToolRelationshipEvidence).where(
        ToolRelationshipEvidence.person_id == mapping.source_person_id
    )
    if tool_name:
        statement = statement.where(ToolRelationshipEvidence.tool_name == tool_name)
    evidence = list(s.execute(statement.order_by(ToolRelationshipEvidence.id)).scalars())
    affected_tools = {row.tool_name for row in evidence}
    for row in evidence:
        duplicate = s.execute(_same_evidence_query(row, mapping.target_person_id)).scalar_one_or_none()
        if duplicate is None:
            row.person_id = mapping.target_person_id
            continue
        if row.confidence > duplicate.confidence:
            duplicate.confidence = row.confidence
            duplicate.verification_status = row.verification_status
            duplicate.evidence_url = row.evidence_url
            duplicate.evidence_payload = row.evidence_payload
            duplicate.checked_at = row.checked_at
            duplicate.expires_at = row.expires_at
            duplicate.last_error = row.last_error
            duplicate.updated_at = utcnow()
        duplicate.withdrawn_at = None if row.withdrawn_at is None else duplicate.withdrawn_at
        s.delete(row)
    s.flush()
    return affected_tools


def apply_mapping(s: Session, mapping: PersonReconciliationMapping) -> int:
    """Apply one operator-approved mapping and rebuild only affected tools."""
    if mapping.decision != MAPPING_APPROVED:
        return 0
    if mapping.source_person_id is None or mapping.target_person_id is None:
        msg = "mapping must name source and target people"
        raise PersonReconciliationError(msg)
    if mapping.source_person_id == mapping.target_person_id:
        msg = "mapping source and target must differ"
        raise PersonReconciliationError(msg)
    if mapping.target_person_id not in people_index.public_identity_ids(s, {mapping.target_person_id}):
        msg = "mapping target must have stable identity evidence"
        raise PersonReconciliationError(msg)
    source_identifiers = list(
        s.execute(
            select(PersonIdentifier).where(
                PersonIdentifier.person_id == mapping.source_person_id,
                PersonIdentifier.is_current.is_(True),
                PersonIdentifier.identifier_kind == people_index.IDENTIFIER_STABLE,
            )
        ).scalars()
    )
    if source_identifiers:
        msg = "mapping source acquired stable identity evidence and requires conflict review"
        raise PersonReconciliationError(msg)
    affected_tools = _move_mapping_evidence(s, mapping)
    for name in sorted(affected_tools):
        people_index.resolve_tool_relationships(s, name)
    mapping.updated_at = utcnow()
    return len(affected_tools)


def apply_approved_mappings_for_tool(s: Session, tool_name: str) -> int:
    """Reapply durable approvals after an upstream evidence refresh."""
    mappings = list(
        s.execute(
            select(PersonReconciliationMapping).where(PersonReconciliationMapping.decision == MAPPING_APPROVED)
        ).scalars()
    )
    applied = 0
    for mapping in mappings:
        applied += int(bool(_move_mapping_evidence(s, mapping, tool_name=tool_name)))
    return applied


def process_queue(*, limit: int = DEFAULT_QUEUE_LIMIT) -> dict[str, int]:
    capped = max(1, min(DEFAULT_QUEUE_LIMIT, int(limit or DEFAULT_QUEUE_LIMIT)))
    now = utcnow()
    with db.session_scope() as s:
        names = [
            row[0]
            for row in s.execute(
                select(PersonReconciliationQueue.tool_name)
                .where(
                    or_(
                        PersonReconciliationQueue.next_attempt_at.is_(None),
                        PersonReconciliationQueue.next_attempt_at <= now,
                    )
                )
                .order_by(PersonReconciliationQueue.enqueued_at, PersonReconciliationQueue.tool_name)
                .limit(capped)
            ).all()
        ]
    processed = 0
    failed = 0
    for name in names:
        try:
            with db.session_scope() as s:
                row = s.get(PersonReconciliationQueue, name)
                if row is None:
                    continue
                _reconcile_tool(s, name)
                s.delete(row)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - persisted bounded retry state
            failed += 1
            with db.session_scope() as s:
                row = s.get(PersonReconciliationQueue, name)
                if row is not None:
                    row.attempts += 1
                    row.next_attempt_at = utcnow() + timedelta(minutes=min(60, 2 ** min(row.attempts, 6)))
                    row.last_error = _clean(str(exc), 2000)
    return {"claimed": len(names), "processed": processed, "failed": failed}


def _ambiguous_display_names(s: Session) -> list[dict[str, Any]]:
    rows = s.execute(
        select(func.lower(Person.display_name), func.count(Person.id))
        .where(Person.display_name != "")
        .group_by(func.lower(Person.display_name))
        .having(func.count(Person.id) > 1)
    ).all()
    conflicts = []
    for name, count in rows:
        candidates = list(
            s.execute(select(Person).where(func.lower(Person.display_name) == name).order_by(Person.id)).scalars()
        )
        candidate_ids = {person.id for person in candidates}
        published_ids = people_index.public_identity_ids(s, candidate_ids)
        identifier_rows = list(
            s.execute(
                select(PersonIdentifier).where(
                    PersonIdentifier.person_id.in_(candidate_ids),
                    PersonIdentifier.is_current.is_(True),
                )
            ).scalars()
        )
        stable_ids = {
            identifier.person_id
            for identifier in identifier_rows
            if identifier.identifier_kind == people_index.IDENTIFIER_STABLE
        }
        handle_ids = {
            identifier.person_id
            for identifier in identifier_rows
            if identifier.identifier_kind == people_index.IDENTIFIER_HANDLE
        }
        conflicts.append(
            {
                "type": "ambiguous_display_name",
                "value": name,
                "details": {
                    "reason": "Display names are presentation data and are never automatic merge evidence.",
                    "candidateCount": count,
                    "resolvedCandidateCount": len(published_ids),
                    "unresolvedAttributionCount": count - len(published_ids),
                    "stableCandidateCount": len(stable_ids),
                    "handleCandidateCount": len(handle_ids),
                    "candidatePublicIds": [person.public_id for person in candidates],
                    "stableEvidenceAvailable": bool(stable_ids),
                },
            }
        )
    return conflicts


def _candidate_source_people(s: Session) -> list[Person]:
    """Return unresolved people with active tool evidence and no prior decision."""
    related_ids = select(ToolPersonRelationship.person_id)
    decided_ids = select(PersonReconciliationMapping.source_person_id).where(
        PersonReconciliationMapping.source_person_id.is_not(None)
    )
    people = list(
        s.execute(
            select(Person)
            .where(
                Person.id.in_(related_ids),
                Person.id.not_in(decided_ids),
                Person.display_name != "",
            )
            .order_by(func.lower(Person.display_name), Person.id)
        ).scalars()
    )
    public_ids = people_index.public_identity_ids(s, {person.id for person in people})
    return [person for person in people if person.id not in public_ids]


def _tool_names_for_person(s: Session, person_id: int) -> tuple[list[str], list[str]]:
    rows = list(
        s.execute(
            select(ToolPersonRelationship).where(ToolPersonRelationship.person_id == person_id)
        ).scalars()
    )
    return sorted({row.tool_name for row in rows}), sorted({row.relationship_type for row in rows})


def _membership_aliases(tool_names: list[str]) -> set[str]:
    aliases = set()
    for name in tool_names:
        clean = _clean(name).casefold()
        if clean:
            aliases.add(clean)
            aliases.add(clean.removeprefix("toolforge-"))
    return aliases


def _stable_identifier_owner(s: Session, namespace: str, value: str) -> int | None:
    clean_value = _clean(value)
    if not clean_value:
        return None
    return s.execute(
        select(PersonIdentifier.person_id).where(
            PersonIdentifier.namespace == namespace,
            PersonIdentifier.normalized_value == clean_value.casefold(),
            PersonIdentifier.is_current.is_(True),
        )
    ).scalar_one_or_none()


def _record_stable_identity_conflict(s: Session, run_id: int, identity: Any) -> bool:  # noqa: ANN401
    """Queue a cross-system stable-id disagreement and refuse a target."""
    toolhub_owner = _stable_identifier_owner(s, people_index.NS_TOOLHUB_USER_ID, identity.toolhub_user_id)
    wikimedia_owner = _stable_identifier_owner(
        s,
        people_index.NS_WIKIMEDIA_GLOBAL_USER_ID,
        identity.wikimedia_global_user_id,
    )
    if toolhub_owner is None or wikimedia_owner is None or toolhub_owner == wikimedia_owner:
        return False
    value = f"toolhub:{identity.toolhub_user_id}|wikimedia:{identity.wikimedia_global_user_id}"
    conflict = s.execute(
        select(PersonReconciliationConflict).where(
            PersonReconciliationConflict.conflict_type == people_policy.REASON_STABLE_CONFLICT,
            PersonReconciliationConflict.value == value,
            PersonReconciliationConflict.status == "pending",
        )
    ).scalar_one_or_none()
    details = {
        "reason": "Toolhub and Wikimedia stable identifiers currently resolve to different people.",
        "identity": identity.evidence_payload(),
        "toolhubPersonId": s.get(Person, toolhub_owner).public_id,
        "wikimediaPersonId": s.get(Person, wikimedia_owner).public_id,
    }
    if conflict is None:
        s.add(
            PersonReconciliationConflict(
                run_id=run_id,
                person_id=toolhub_owner,
                conflict_type=people_policy.REASON_STABLE_CONFLICT,
                value=value,
                details=details,
            )
        )
    else:
        conflict.run_id = run_id
        conflict.details = details
        conflict.last_seen_at = utcnow()
    return True


def discover_identity_candidates(
    s: Session,
    *,
    run_id: int,
    identity_provider: ToolhubIdentityProvider,
    membership_provider: ToolforgeMembershipProvider,
    label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
) -> dict[str, int]:
    """Persist exact Toolhub matches for review without merging display identities."""
    sources = _candidate_source_people(s)
    by_label: dict[str, list[Person]] = {}
    for person in sources:
        by_label.setdefault(person.display_name.casefold(), []).append(person)
    created = 0
    conflicts = 0
    for people in list(by_label.values())[: max(1, min(int(label_limit), 100))]:
        identity = identity_provider.lookup_exact(people[0].display_name)
        if identity is None:
            continue
        if _record_stable_identity_conflict(s, run_id, identity):
            conflicts += 1
            continue
        memberships = membership_provider.tool_names(identity.toolhub_username)
        target = people_index.ensure_person(
            s,
            display_name=identity.toolhub_username,
            toolhub_user_id=identity.toolhub_user_id,
            wikimedia_global_user_id=identity.wikimedia_global_user_id,
            toolhub_username=identity.toolhub_username,
            toolforge_username=identity.toolhub_username if memberships else "",
            source="toolhub_public_user",
        )
        membership_aliases = _membership_aliases(memberships)
        for source in people:
            tool_names, roles = _tool_names_for_person(s, source.id)
            matched_memberships = sorted(_membership_aliases(tool_names) & membership_aliases)
            decision = people_policy.decide_identity_link(
                exact_toolhub_candidate=True,
                same_tool_toolforge_membership=bool(matched_memberships),
            )
            mapping = PersonReconciliationMapping(
                run_id=run_id,
                source_person_id=source.id,
                target_person_id=target.id,
                source_key=source.canonical_key,
                target_key=target.canonical_key,
                decision=people_policy.ACTION_CANDIDATE,
                reason=decision.reason,
                confidence=decision.confidence,
                evidence={
                    "identity": identity.evidence_payload(),
                    "sourcePublicId": source.public_id,
                    "toolNames": tool_names,
                    "relationshipTypes": roles,
                    "toolforgeMemberships": memberships,
                    "matchedToolforgeMemberships": matched_memberships,
                },
                updated_at=utcnow(),
            )
            s.add(mapping)
            created += 1
    s.flush()
    return {"created": created, "conflicts": conflicts}


def build_plan(s: Session) -> dict[str, Any]:
    cached_tools = {row[0] for row in s.execute(select(CanonicalToolCache.tool_name)).all()}
    claim_tools = {row[0] for row in s.execute(select(ToolAuthorClaim.tool_name).distinct()).all()}
    evidence_tools = {row[0] for row in s.execute(select(ToolRelationshipEvidence.tool_name).distinct()).all()}
    return {
        "toolNames": sorted(cached_tools | claim_tools | evidence_tools),
        "peopleScanned": s.scalar(select(func.count()).select_from(Person)) or 0,
        "evidenceScanned": s.scalar(select(func.count()).select_from(ToolRelationshipEvidence)) or 0,
        "relationshipsScanned": s.scalar(select(func.count()).select_from(ToolPersonRelationship)) or 0,
        "conflicts": _ambiguous_display_names(s),
    }


def run(  # noqa: PLR0913 - explicit providers keep reconciliation deterministic in tests
    s: Session,
    *,
    mode: str = MODE_DRY_RUN,
    discover_candidates: bool = False,
    identity_provider: ToolhubIdentityProvider | None = None,
    membership_provider: ToolforgeMembershipProvider | None = None,
    candidate_label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
) -> dict[str, Any]:
    """Audit or rebuild Toolhub-backed evidence and local people projections."""
    if mode not in {MODE_DRY_RUN, MODE_APPLY}:
        raise PersonReconciliationError(mode)
    run_row = PersonReconciliationRun(mode=mode, status="running", started_at=utcnow())
    s.add(run_row)
    s.flush()
    try:
        before = build_plan(s)
        if mode == MODE_APPLY:
            for user in s.execute(select(User).order_by(User.id)).scalars():
                people_index.link_user(s, user)
            for name in before["toolNames"]:
                _reconcile_tool(s, name)
            people_index.refresh_activity_summaries(s)
            candidate_result = (
                discover_identity_candidates(
                    s,
                    run_id=run_row.id,
                    identity_provider=identity_provider or ToolhubIdentityProvider(),
                    membership_provider=membership_provider or ToolforgeMembershipProvider(),
                    label_limit=candidate_label_limit,
                )
                if discover_candidates
                else {"created": 0, "conflicts": 0}
            )
        else:
            candidate_result = {"created": 0, "conflicts": 0}
        after = build_plan(s)
        for conflict in after["conflicts"]:
            existing = s.execute(
                select(PersonReconciliationConflict).where(
                    PersonReconciliationConflict.conflict_type == conflict["type"],
                    PersonReconciliationConflict.value == conflict["value"],
                    PersonReconciliationConflict.status == "pending",
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(
                    PersonReconciliationConflict(
                        run_id=run_row.id,
                        conflict_type=conflict["type"],
                        value=conflict["value"],
                        details=conflict["details"],
                    )
                )
            else:
                existing.run_id = run_row.id
                existing.details = conflict["details"]
                existing.last_seen_at = utcnow()
        summary = {
            "mode": mode,
            "peopleScanned": after["peopleScanned"],
            "evidenceScanned": after["evidenceScanned"],
            "relationships": after["relationshipsScanned"],
            "conflicts": len(after["conflicts"]),
            "toolsRebuilt": len(after["toolNames"]) if mode == MODE_APPLY else 0,
            "identityCandidatesCreated": candidate_result["created"],
            "stableIdentityConflicts": candidate_result["conflicts"],
            "catalogAuthority": "toolhub",
        }
    except Exception as exc:
        run_row.status = RUN_FAILED
        run_row.completed_at = utcnow()
        run_row.error = _clean(str(exc), 2000)
        raise
    run_row.status = RUN_COMPLETED
    run_row.completed_at = utcnow()
    run_row.summary = summary
    return summary
