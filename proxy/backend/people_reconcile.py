# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic reconciliation for canonical people and evidence projections."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import db, maintainer_index, people_index, people_policy
from backend.models import (
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationQueue,
    PersonReconciliationRun,
    ToolAuthorClaim,
    ToolhubAccountProjection,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    User,
    utcnow,
)
from backend.public_identity import PublicIdentityResolver

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MODE_DRY_RUN = "dry-run"
MODE_APPLY = "apply"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
DEFAULT_QUEUE_LIMIT = 100
DEFAULT_CANDIDATE_LABEL_LIMIT = 25
MAPPING_CANDIDATE = people_policy.ACTION_CANDIDATE
MAPPING_AUTO_LINK = people_policy.ACTION_AUTO_LINK
MAPPING_APPROVED = "approved"
MAPPING_REJECTED = "rejected"
MAPPING_SPLIT = "split"
MAPPING_DECISIONS = {MAPPING_CANDIDATE, MAPPING_AUTO_LINK, MAPPING_APPROVED, MAPPING_REJECTED, MAPPING_SPLIT}
MAPPING_APPLIED_DECISIONS = {MAPPING_AUTO_LINK, MAPPING_APPROVED}
CANDIDATE_RETRY_AFTER = timedelta(days=1)


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
    apply_durable_mappings_for_tool(s, name)
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
    statement = select(ToolRelationshipEvidence).where(ToolRelationshipEvidence.person_id == mapping.source_person_id)
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
    """Apply one durable evidence-backed mapping and rebuild affected tools."""
    if mapping.decision not in MAPPING_APPLIED_DECISIONS:
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


def apply_durable_mappings_for_tool(s: Session, tool_name: str) -> int:
    """Reapply auto-linked or operator-approved mappings after an evidence refresh."""
    mappings = list(
        s.execute(
            select(PersonReconciliationMapping).where(
                PersonReconciliationMapping.decision.in_(MAPPING_APPLIED_DECISIONS)
            )
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
    """Return non-stable evidence owners due for deterministic resolution."""
    related_ids = select(ToolPersonRelationship.person_id)
    stable_ids = select(PersonIdentifier.person_id).where(
        PersonIdentifier.identifier_kind == people_index.IDENTIFIER_STABLE,
        PersonIdentifier.is_current.is_(True),
    )
    finalized_ids = select(PersonReconciliationMapping.source_person_id).where(
        PersonReconciliationMapping.source_person_id.is_not(None),
        PersonReconciliationMapping.decision.in_(
            {MAPPING_AUTO_LINK, MAPPING_APPROVED, MAPPING_REJECTED, MAPPING_SPLIT}
        ),
    )
    deferred_candidate_ids = select(PersonReconciliationMapping.source_person_id).where(
        PersonReconciliationMapping.source_person_id.is_not(None),
        PersonReconciliationMapping.decision == MAPPING_CANDIDATE,
        PersonReconciliationMapping.updated_at > utcnow() - CANDIDATE_RETRY_AFTER,
    )
    return list(
        s.execute(
            select(Person)
            .where(
                Person.id.in_(related_ids),
                Person.id.not_in(stable_ids),
                Person.id.not_in(finalized_ids),
                Person.id.not_in(deferred_candidate_ids),
                Person.display_name != "",
            )
            .order_by(func.lower(Person.display_name), Person.id)
        ).scalars()
    )


def _tool_names_for_person(s: Session, person_id: int) -> tuple[list[str], list[str]]:
    rows = list(
        s.execute(select(ToolPersonRelationship).where(ToolPersonRelationship.person_id == person_id)).scalars()
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


def _account_evidence(account: ToolhubAccountProjection) -> dict[str, str]:
    return {
        "toolhubUserId": account.toolhub_user_id,
        "toolhubUsername": account.username,
        "wikimediaGlobalUserId": account.wikimedia_global_user_id or "",
    }


def _record_stable_identity_conflict(
    s: Session,
    run_id: int,
    account: ToolhubAccountProjection,
    *,
    toolforge_uid_number: str = "",
) -> bool:
    """Queue a cross-system stable-id disagreement and refuse a target."""
    identifiers = {
        people_index.NS_TOOLHUB_USER_ID: account.toolhub_user_id,
        people_index.NS_WIKIMEDIA_GLOBAL_USER_ID: account.wikimedia_global_user_id or "",
        people_index.NS_TOOLFORGE_UID_NUMBER: toolforge_uid_number,
    }
    owners = {
        namespace: owner
        for namespace, value in identifiers.items()
        if value and (owner := _stable_identifier_owner(s, namespace, value)) is not None
    }
    if len(set(owners.values())) <= 1:
        return False
    value = "|".join(
        f"{namespace}:{identifiers[namespace]}" for namespace in sorted(identifiers) if identifiers[namespace]
    )
    conflict = s.execute(
        select(PersonReconciliationConflict).where(
            PersonReconciliationConflict.conflict_type == people_policy.REASON_STABLE_CONFLICT,
            PersonReconciliationConflict.value == value,
            PersonReconciliationConflict.status == "pending",
        )
    ).scalar_one_or_none()
    details = {
        "reason": "Cross-system stable identifiers currently resolve to different people.",
        "identity": _account_evidence(account),
        "toolforgeUidNumber": toolforge_uid_number,
        "stableIdentifierOwners": {namespace: s.get(Person, owner).public_id for namespace, owner in owners.items()},
    }
    if toolhub_owner := owners.get(people_index.NS_TOOLHUB_USER_ID):
        details["toolhubPersonId"] = s.get(Person, toolhub_owner).public_id
    if wikimedia_owner := owners.get(people_index.NS_WIKIMEDIA_GLOBAL_USER_ID):
        details["wikimediaPersonId"] = s.get(Person, wikimedia_owner).public_id
    if toolforge_owner := owners.get(people_index.NS_TOOLFORGE_UID_NUMBER):
        details["toolforgePersonId"] = s.get(Person, toolforge_owner).public_id
    if conflict is None:
        s.add(
            PersonReconciliationConflict(
                run_id=run_id,
                person_id=next(iter(owners.values())),
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


def _exact_account(s: Session, label: str) -> ToolhubAccountProjection | None:
    rows = list(
        s.execute(
            select(ToolhubAccountProjection)
            .where(ToolhubAccountProjection.normalized_username == label.casefold())
            .order_by(ToolhubAccountProjection.toolhub_user_id)
            .limit(2)
        ).scalars()
    )
    return rows[0] if len(rows) == 1 else None


def _mapping_for_source(s: Session, source_person_id: int) -> PersonReconciliationMapping | None:
    return s.execute(
        select(PersonReconciliationMapping)
        .where(PersonReconciliationMapping.source_person_id == source_person_id)
        .order_by(PersonReconciliationMapping.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _candidate_account_groups(
    s: Session,
    sources: list[Person],
) -> list[tuple[ToolhubAccountProjection, list[Person]]]:
    """Group source observations by labels that map to one exact local account."""
    by_label: dict[str, list[Person]] = {}
    for person in sources:
        by_label.setdefault(person.display_name.casefold(), []).append(person)
    matches = []
    for people in by_label.values():
        account = _exact_account(s, people[0].display_name)
        if account is not None:
            matches.append((account, people))
    return matches


def discover_identity_candidates(
    s: Session,
    *,
    run_id: int,
    identity_resolver: PublicIdentityResolver,
    label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
) -> dict[str, int]:
    """Resolve exact public accounts and auto-link only SUL-backed tool evidence."""
    created = 0
    linked = 0
    conflicts = 0
    account_limit = max(1, min(int(label_limit), 100))
    candidates = _candidate_account_groups(s, _candidate_source_people(s))
    for account, people in candidates[:account_limit]:
        resolved = identity_resolver.resolve(account.wikimedia_global_user_id or "")
        toolforge = resolved.toolforge if resolved is not None else None
        if _record_stable_identity_conflict(
            s,
            run_id,
            account,
            toolforge_uid_number=toolforge.uid_number if toolforge else "",
        ):
            conflicts += 1
            continue
        target = people_index.ensure_official_account_person(
            s,
            toolhub_user_id=account.toolhub_user_id,
            username=account.username,
            wikimedia_global_user_id=account.wikimedia_global_user_id or "",
        )
        if target is None:
            conflicts += 1
            continue
        if resolved is not None:
            target = people_index.ensure_person(
                s,
                display_name=account.username,
                toolhub_user_id=account.toolhub_user_id,
                wikimedia_global_user_id=resolved.wikimedia.global_user_id,
                toolforge_uid_number=toolforge.uid_number if toolforge else "",
                toolhub_username=account.username,
                toolforge_username=toolforge.uid if toolforge else "",
                wiki_username=resolved.wikimedia.username,
                source="wikimedia_toolforge_bridge",
            )
        memberships = list(toolforge.tool_names) if toolforge else []
        membership_aliases = _membership_aliases(memberships)
        for source in people:
            tool_names, roles = _tool_names_for_person(s, source.id)
            matched_memberships = sorted(_membership_aliases(tool_names) & membership_aliases)
            decision = people_policy.decide_identity_link(
                exact_toolhub_candidate=True,
                same_tool_toolforge_membership=bool(matched_memberships),
                toolforge_sul_bound=toolforge is not None,
            )
            mapping = _mapping_for_source(s, source.id)
            if mapping is None:
                mapping = PersonReconciliationMapping(source_person_id=source.id)
                s.add(mapping)
                created += 1
            mapping.run_id = run_id
            mapping.target_person_id = target.id
            mapping.source_key = source.canonical_key
            mapping.target_key = target.canonical_key
            mapping.decision = decision.action
            mapping.reason = decision.reason
            mapping.confidence = decision.confidence
            mapping.evidence = {
                "resolutionVersion": 2,
                "identity": _account_evidence(account),
                "wikimediaUsername": resolved.wikimedia.username if resolved else "",
                "toolforgeUsername": toolforge.uid if toolforge else "",
                "toolforgeUidNumber": toolforge.uid_number if toolforge else "",
                "sourcePublicId": source.public_id,
                "toolNames": tool_names,
                "relationshipTypes": roles,
                "toolforgeMemberships": memberships,
                "matchedToolforgeMemberships": matched_memberships,
            }
            mapping.updated_at = utcnow()
            s.flush()
            if mapping.decision == MAPPING_AUTO_LINK:
                linked += int(bool(apply_mapping(s, mapping)))
    s.flush()
    return {"created": created, "linked": linked, "conflicts": conflicts}


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
    identity_resolver: PublicIdentityResolver | None = None,
    candidate_label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
    rebuild_tools: bool = True,
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
            if rebuild_tools:
                for name in before["toolNames"]:
                    _reconcile_tool(s, name)
            candidate_result = (
                discover_identity_candidates(
                    s,
                    run_id=run_row.id,
                    identity_resolver=identity_resolver or PublicIdentityResolver(),
                    label_limit=candidate_label_limit,
                )
                if discover_candidates
                else {"created": 0, "linked": 0, "conflicts": 0}
            )
            if rebuild_tools or candidate_result["linked"]:
                people_index.refresh_activity_summaries(s)
        else:
            candidate_result = {"created": 0, "linked": 0, "conflicts": 0}
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
            "toolsRebuilt": len(after["toolNames"]) if mode == MODE_APPLY and rebuild_tools else 0,
            "identityCandidatesCreated": candidate_result["created"],
            "identityMappingsApplied": candidate_result["linked"],
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
