# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic reconciliation for canonical people and evidence projections."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import db, identity_graph, maintainer_index, people_index, people_policy
from backend.models import (
    CanonicalToolCache,
    Person,
    PersonAccountBinding,
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
IDENTITY_RESOLUTION_VERSION = 4


class PersonReconciliationError(ValueError):
    """Invalid reconciliation mode."""


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - untrusted stored data
    return str(value or "").strip()[:limit]


def enqueue_tool_names_in_session(s: Session, tool_names: list[str], *, reason: str = "data_ingestion") -> int:
    """Upsert reconciliation work within the caller's transaction."""
    names = sorted({_clean(name) for name in tool_names if _clean(name)})
    if not names:
        return 0
    now = utcnow()
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


def enqueue_tool_names(tool_names: list[str], *, reason: str = "data_ingestion") -> int:
    with db.session_scope() as s:
        return enqueue_tool_names_in_session(s, tool_names, reason=reason)


def _reconcile_tool(s: Session, name: str, *, retired: bool = False) -> None:
    if retired:
        people_index.retire_tool_relationships(s, name)
        return
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
                _reconcile_tool(s, name, retired=row.reason == "canonical_retired")
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


def drain_queue(*, max_batches: int = 100) -> dict[str, int]:
    """Drain all currently actionable rows in bounded batches."""
    totals = {"claimed": 0, "processed": 0, "failed": 0, "batches": 0}
    for _batch in range(max(1, min(max_batches, 100))):
        result = process_queue(limit=DEFAULT_QUEUE_LIMIT)
        if result["claimed"] == 0:
            break
        totals["batches"] += 1
        for key in ("claimed", "processed", "failed"):
            totals[key] += result[key]
    return totals


def _ambiguous_display_name_count(s: Session) -> int:
    """Count repeated labels for observability without creating review work."""
    rows = s.execute(
        select(func.lower(Person.display_name), func.count(Person.id))
        .where(Person.display_name != "")
        .group_by(func.lower(Person.display_name))
        .having(func.count(Person.id) > 1)
    ).all()
    return len(rows)


def _retire_non_actionable_display_conflicts(s: Session) -> int:
    """Dismiss legacy label-only conflicts that cannot support a safe decision."""
    now = utcnow()
    rows = list(
        s.execute(
            select(PersonReconciliationConflict).where(
                PersonReconciliationConflict.conflict_type == "ambiguous_display_name",
                PersonReconciliationConflict.status == "pending",
            )
        ).scalars()
    )
    for row in rows:
        row.status = "dismissed"
        row.reviewed_at = now
        row.review_notes = (
            "Automatically retired: repeated display labels are evidence clusters, not identity conflicts."
        )
    return len(rows)


def _pending_actionable_conflict_count(s: Session) -> int:
    return (
        s.scalar(
            select(func.count())
            .select_from(PersonReconciliationConflict)
            .where(
                PersonReconciliationConflict.status == "pending",
                PersonReconciliationConflict.conflict_type != "ambiguous_display_name",
            )
        )
        or 0
    )


def _candidate_source_people(s: Session) -> list[Person]:
    """Return non-stable evidence owners due for deterministic resolution."""
    related_ids = select(ToolPersonRelationship.person_id)
    stable_ids = select(PersonIdentifier.person_id).where(
        PersonIdentifier.identifier_kind == people_index.IDENTIFIER_STABLE,
        PersonIdentifier.is_current.is_(True),
    )
    finalized_ids = select(PersonReconciliationMapping.source_person_id).where(
        PersonReconciliationMapping.source_person_id.is_not(None),
        PersonReconciliationMapping.decision.in_({MAPPING_REJECTED, MAPPING_SPLIT}),
    )
    people = list(
        s.execute(
            select(Person)
            .where(
                Person.id.in_(related_ids),
                Person.id.not_in(stable_ids),
                Person.id.not_in(finalized_ids),
                Person.display_name != "",
            )
            .order_by(func.lower(Person.display_name), Person.id)
        ).scalars()
    )
    if not people:
        return []
    person_ids = {person.id for person in people}
    latest_mappings: dict[int, PersonReconciliationMapping] = {}
    mappings = s.execute(
        select(PersonReconciliationMapping)
        .where(
            PersonReconciliationMapping.source_person_id.in_(person_ids),
            PersonReconciliationMapping.decision.in_({MAPPING_CANDIDATE, MAPPING_AUTO_LINK, MAPPING_APPROVED}),
        )
        .order_by(PersonReconciliationMapping.id.desc())
    ).scalars()
    for mapping in mappings:
        latest_mappings.setdefault(mapping.source_person_id, mapping)
    structured_evidence_people = {
        person_id
        for (person_id,) in s.execute(
            select(PersonIdentifier.person_id).where(
                PersonIdentifier.person_id.in_(person_ids),
                PersonIdentifier.namespace == people_index.NS_WIKI_USERNAME,
                PersonIdentifier.is_current.is_(True),
            )
        ).all()
    }
    structured_evidence_people.update(
        person_id
        for (person_id,) in s.execute(
            select(ToolRelationshipEvidence.person_id).where(
                ToolRelationshipEvidence.person_id.in_(person_ids),
                ToolRelationshipEvidence.source == maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
        ).all()
    )
    retry_after = utcnow() - CANDIDATE_RETRY_AFTER
    due = []
    for person in people:
        mapping = latest_mappings.get(person.id)
        if mapping is not None and mapping.decision in MAPPING_APPLIED_DECISIONS:
            # Applied evidence should no longer resolve to the source person.
            # If an upstream refresh recreated it, immediately reapply the
            # durable decision instead of treating the old mapping as final.
            due.append(person)
            continue
        if mapping is None or mapping.updated_at <= retry_after:
            due.append(person)
            continue
        evidence = mapping.evidence if isinstance(mapping.evidence, dict) else {}
        version = int(evidence.get("resolutionVersion") or 0)
        if person.id in structured_evidence_people and version < IDENTITY_RESOLUTION_VERSION:
            due.append(person)
    return due


def _source_evidence_for_person(s: Session, person_id: int) -> tuple[list[str], list[str], list[str]]:
    relationships = list(
        s.execute(select(ToolPersonRelationship).where(ToolPersonRelationship.person_id == person_id)).scalars()
    )
    toolforge_names = set()
    evidence_rows = s.execute(
        select(ToolRelationshipEvidence).where(
            ToolRelationshipEvidence.person_id == person_id,
            ToolRelationshipEvidence.source == maintainer_index.SOURCE_TOOLFORGE_TOOLSADMIN,
            ToolRelationshipEvidence.withdrawn_at.is_(None),
        )
    ).scalars()
    for row in evidence_rows:
        payload = row.evidence_payload if isinstance(row.evidence_payload, dict) else {}
        if toolforge_name := _clean(payload.get("toolforgeToolName")):
            toolforge_names.add(toolforge_name)
    return (
        sorted({row.tool_name for row in relationships}),
        sorted(toolforge_names),
        sorted({row.relationship_type for row in relationships}),
    )


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


def _normalized_wikimedia_username(value: str) -> str:
    """Normalize Toolhub's common wiki-username forms for exact comparison."""
    normalized = " ".join(_clean(value).replace("_", " ").split())
    prefix, separator, remainder = normalized.partition(":")
    if separator and prefix.casefold() == "user":
        normalized = remainder.strip()
    return normalized.casefold()


def _verified_wikimedia_handle(s: Session, person_id: int, canonical_username: str) -> str:
    """Return a stored wiki handle only when CentralAuth confirms the same name."""
    expected = _normalized_wikimedia_username(canonical_username)
    if not expected:
        return ""
    rows = s.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.person_id == person_id,
            PersonIdentifier.namespace == people_index.NS_WIKI_USERNAME,
            PersonIdentifier.is_current.is_(True),
        )
    ).scalars()
    return next((row.value for row in rows if _normalized_wikimedia_username(row.value) == expected), "")


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


def _record_account_binding_conflicts(s: Session, run_id: int) -> int:
    """Project durable provider-binding conflicts into the operator queue."""
    rows = list(
        s.execute(
            select(PersonAccountBinding).where(
                PersonAccountBinding.status == identity_graph.STATUS_CONFLICT,
                PersonAccountBinding.revoked_at.is_(None),
            )
        ).scalars()
    )
    now = utcnow()
    for row in rows:
        value = f"{row.provider}:{row.external_id}"
        conflict = s.execute(
            select(PersonReconciliationConflict).where(
                PersonReconciliationConflict.conflict_type == "account_binding_conflict",
                PersonReconciliationConflict.value == value,
                PersonReconciliationConflict.status == "pending",
            )
        ).scalar_one_or_none()
        details = {
            "reason": "Immutable provider identifiers currently resolve to different people.",
            "provider": row.provider,
            "externalId": row.external_id,
            "proofMethod": row.proof_method,
            "evidence": row.evidence if isinstance(row.evidence, dict) else {},
        }
        if conflict is None:
            s.add(
                PersonReconciliationConflict(
                    run_id=run_id,
                    person_id=row.person_id,
                    conflict_type="account_binding_conflict",
                    value=value,
                    details=details,
                )
            )
        else:
            conflict.run_id = run_id
            conflict.details = details
            conflict.last_seen_at = now
    return len(rows)


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
    return sorted(
        matches,
        key=lambda match: (
            -len(match[1]),
            match[0].normalized_username,
            match[0].toolhub_user_id,
        ),
    )


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
        verified_wikimedia_handles = {
            source.id: _verified_wikimedia_handle(s, source.id, resolved.wikimedia.username)
            for source in people
            if resolved is not None
        }
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
            tool_names, toolforge_names, roles = _source_evidence_for_person(s, source.id)
            matched_memberships = sorted(
                (_membership_aliases(toolforge_names) | _membership_aliases(tool_names)) & membership_aliases
            )
            verified_wikimedia_handle = verified_wikimedia_handles.get(source.id, "")
            decision = people_policy.decide_identity_link(
                structured_handle=bool(verified_wikimedia_handle),
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
                "resolutionVersion": IDENTITY_RESOLUTION_VERSION,
                "identity": _account_evidence(account),
                "wikimediaUsername": resolved.wikimedia.username if resolved else "",
                "verifiedWikimediaHandle": verified_wikimedia_handle,
                "toolforgeUsername": toolforge.uid if toolforge else "",
                "toolforgeUidNumber": toolforge.uid_number if toolforge else "",
                "sourcePublicId": source.public_id,
                "toolNames": tool_names,
                "toolforgeToolNames": toolforge_names,
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
        "ambiguousDisplayNameClusters": _ambiguous_display_name_count(s),
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
            account_bindings = identity_graph.synchronize(s)
            account_binding_conflicts_queued = _record_account_binding_conflicts(s, run_row.id)
            identity_qualities_refreshed = people_index.refresh_identity_qualities(s)
            non_actionable_conflicts_retired = _retire_non_actionable_display_conflicts(s)
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
            account_bindings = {
                "toolhubBindings": 0,
                "toolhubConflicts": 0,
                "usersHydrated": 0,
                "verified": 0,
                "candidate": 0,
                "conflict": 0,
                "unresolved": 0,
            }
            account_binding_conflicts_queued = 0
            candidate_result = {"created": 0, "linked": 0, "conflicts": 0}
            identity_qualities_refreshed = 0
            non_actionable_conflicts_retired = 0
        after = build_plan(s)
        summary = {
            "mode": mode,
            "peopleScanned": after["peopleScanned"],
            "evidenceScanned": after["evidenceScanned"],
            "relationships": after["relationshipsScanned"],
            "conflicts": _pending_actionable_conflict_count(s),
            "ambiguousDisplayNameClusters": after["ambiguousDisplayNameClusters"],
            "identityQualitiesRefreshed": identity_qualities_refreshed,
            "nonActionableConflictsRetired": non_actionable_conflicts_retired,
            "toolsRebuilt": len(after["toolNames"]) if mode == MODE_APPLY and rebuild_tools else 0,
            "identityCandidatesCreated": candidate_result["created"],
            "identityMappingsApplied": candidate_result["linked"],
            "stableIdentityConflicts": candidate_result["conflicts"],
            "accountBindings": account_bindings,
            "accountBindingConflictsQueued": account_binding_conflicts_queued,
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
