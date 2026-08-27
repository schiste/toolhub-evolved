# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic reconciliation for canonical people and evidence projections."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend import (
    db,
    identity_graph,
    maintainer_index,
    people_index,
    people_policy,
    public_identity,
    source_attestations,
    wikimedia_user_reconciliation,
)
from backend.models import (
    ApiCacheMeta,
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
    ToolSummaryCache,
    UnresolvedAttributionEvidence,
    User,
    utcnow,
)
from backend.public_identity import PublicIdentityResolver
from backend.sync import AUTHOR_CLAIM_VERIFIED

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
MAPPING_APPROVED = people_policy.MAPPING_APPROVED
MAPPING_REJECTED = "rejected"
MAPPING_SPLIT = "split"
MAPPING_DECISIONS = {MAPPING_CANDIDATE, MAPPING_AUTO_LINK, MAPPING_APPROVED, MAPPING_REJECTED, MAPPING_SPLIT}
MAPPING_APPLIED_DECISIONS = people_policy.APPLIED_IDENTITY_MAPPING_DECISIONS
CANDIDATE_RETRY_AFTER = timedelta(days=1)

# How stale an unchanged conflict's `last_seen_at` may get before this job
# refreshes it. Every hourly run re-derives the same conflicts, and rewriting
# `run_id` and `last_seen_at` on rows whose `details` had not moved emitted an
# UPDATE per conflict per hour whose entire content was two timestamps. On
# 2026-08-27 that write deadlocked against `people-reconcile-incremental`, which
# runs every minute and takes the same rows -- MySQL 1213, "Deadlock found when
# trying to get lock", on the two-timestamp UPDATE -- and the job lost 21 hours
# to it. Nothing reads either column -- they exist so
# an operator reading the queue can see a conflict is still live -- so the
# refresh only has to be recent, not current. Six hours is well inside how
# often anyone looks and removes essentially every one of those writes.
CONFLICT_REFRESH_AFTER = timedelta(hours=6)
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
    clean_reason = _clean(reason, 64) or "data_ingestion"
    rows = [{"tool_name": name, "reason": clean_reason, "enqueued_at": now} for name in names]
    dialect = s.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(PersonReconciliationQueue).values(rows)
        s.execute(
            statement.on_duplicate_key_update(
                reason=statement.inserted.reason,
                enqueued_at=statement.inserted.enqueued_at,
                next_attempt_at=None,
                last_error=None,
            )
        )
    elif dialect == "sqlite":
        statement = sqlite_insert(PersonReconciliationQueue).values(rows)
        s.execute(
            statement.on_conflict_do_update(
                index_elements=[PersonReconciliationQueue.tool_name],
                set_={
                    "reason": statement.excluded.reason,
                    "enqueued_at": statement.excluded.enqueued_at,
                    "next_attempt_at": None,
                    "last_error": None,
                },
            )
        )
    else:
        for row_values in rows:
            row = s.get(PersonReconciliationQueue, row_values["tool_name"])
            if row is None:
                s.add(PersonReconciliationQueue(**row_values))
            else:
                row.reason = clean_reason
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
    """Reapply auto-linked or operator-approved mappings after an evidence refresh.

    Only a mapping whose source person already holds evidence on this tool can
    move anything; every other one loads its evidence, finds none, and returns
    an empty set. Selecting them all did that about 2,100 times per tool, which
    was over 90% of the ~4.5s each queued tool cost and the reason a backlog
    took hours rather than minutes to drain.
    """
    evidence_people = {
        row[0]
        for row in s.execute(
            select(ToolRelationshipEvidence.person_id).where(ToolRelationshipEvidence.tool_name == tool_name).distinct()
        ).all()
    }
    if not evidence_people:
        return 0
    mappings = list(
        s.execute(
            select(PersonReconciliationMapping).where(
                PersonReconciliationMapping.decision.in_(MAPPING_APPLIED_DECISIONS),
                PersonReconciliationMapping.source_person_id.in_(evidence_people),
            )
        ).scalars()
    )
    applied = 0
    for mapping in mappings:
        applied += int(bool(_move_mapping_evidence(s, mapping, tool_name=tool_name)))
    return applied


def process_queue(*, limit: int = DEFAULT_QUEUE_LIMIT, reason: str | None = None) -> dict[str, int]:
    capped = max(1, min(DEFAULT_QUEUE_LIMIT, int(limit or DEFAULT_QUEUE_LIMIT)))
    now = utcnow()
    with db.session_scope() as s:
        filters = [
            or_(
                PersonReconciliationQueue.next_attempt_at.is_(None),
                PersonReconciliationQueue.next_attempt_at <= now,
            )
        ]
        if reason:
            filters.append(PersonReconciliationQueue.reason == _clean(reason, 64))
        names = [
            row[0]
            for row in s.execute(
                select(PersonReconciliationQueue.tool_name)
                .where(*filters)
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


def drain_queue(*, reason: str | None = None, max_batches: int = 100) -> dict[str, int]:
    """Drain all currently actionable rows in bounded batches."""
    totals = {"claimed": 0, "processed": 0, "failed": 0, "batches": 0}
    for _batch in range(max(1, min(max_batches, 100))):
        result = process_queue(limit=DEFAULT_QUEUE_LIMIT, reason=reason)
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
    elif _conflict_moved(conflict, details, utcnow()):
        conflict.run_id = run_id
        conflict.details = details
        conflict.last_seen_at = utcnow()
    return True


def _conflict_moved(conflict: PersonReconciliationConflict, details: dict[str, Any], now: datetime) -> bool:
    """Whether an already-recorded conflict is worth writing again.

    True when what the conflict says has changed, and otherwise only once
    `CONFLICT_REFRESH_AFTER` has passed -- so an unchanged conflict costs one
    write every six hours rather than one every hour, and a changed one is
    still written the moment it changes.
    """
    if (conflict.details if isinstance(conflict.details, dict) else {}) != details:
        return True
    last_seen = conflict.last_seen_at
    return last_seen is None or last_seen + CONFLICT_REFRESH_AFTER <= now


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
        elif _conflict_moved(conflict, details, now):
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


DEFAULT_REGISTRY_LABEL_LIMIT = 1000
# Four requests a second, serialized, against an API that publishes no read
# limit and asks chiefly for a descriptive user agent and serial rather than
# parallel requests. The fixed one-second delay this replaces was a guess
# standing in for the real mechanisms; the fetcher now sends maxlag and obeys
# Retry-After, so meta.wikimedia.org can slow us down when it wants to rather
# than us assuming a rate on its behalf. A ~900-label sweep is ~4 minutes.
REGISTRY_MIN_INTERVAL_SECONDS = 0.25
# Provenance for people minted from a registry lookup rather than from an
# account that registered with Toolhub or Toolforge. Deliberately not a
# trusted handle source: the stable id makes them publishable, and nothing
# about the label should lend authority to the handle.
REGISTRY_SOURCE = "wikimedia_centralauth"
REGISTRY_CURSOR_KEY = "registry_label_cursor"


def _registry_corroborated(s: Session, *, target_person_id: int, tool_names: list[str]) -> bool:
    """Return True when the target already holds verified evidence on a shared tool.

    The registry only proved the account exists. This is the independent fact
    that makes the label about *this* tool, and it must come from evidence the
    registry lookup did not create.
    """
    if not tool_names:
        return False
    return (
        s.execute(
            select(ToolRelationshipEvidence.id)
            .where(
                ToolRelationshipEvidence.person_id == target_person_id,
                ToolRelationshipEvidence.tool_name.in_(tool_names),
                ToolRelationshipEvidence.verification_status == AUTHOR_CLAIM_VERIFIED,
                ToolRelationshipEvidence.withdrawn_at.is_(None),
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _upsert_mapping(  # noqa: PLR0913 - the mapping's audit fields stay explicit
    s: Session,
    *,
    run_id: int,
    source: Person,
    target: Person,
    decision: people_policy.IdentityDecision,
    evidence: dict[str, Any],
) -> tuple[PersonReconciliationMapping, bool]:
    """Record one durable mapping from a policy decision, reusing any existing row.

    Both discovery passes reach the same shape once they have a decision, and
    the mapping is the audit trail for it, so the fields must not drift apart
    between them.
    """
    mapping = _mapping_for_source(s, source.id)
    created = mapping is None
    if mapping is None:
        mapping = PersonReconciliationMapping(source_person_id=source.id)
        s.add(mapping)
    mapping.run_id = run_id
    mapping.target_person_id = target.id
    mapping.source_key = source.canonical_key
    mapping.target_key = target.canonical_key
    mapping.decision = decision.action
    mapping.reason = decision.reason
    mapping.confidence = decision.confidence
    mapping.evidence = evidence
    mapping.updated_at = utcnow()
    return mapping, created


def _registry_label_batch(s: Session, *, limit: int) -> tuple[list[str], str]:
    """Return the next handle-shaped labels no local rule can resolve.

    The unresolved population is attribution *labels*, which by design carry no
    person id, so it is not the same set as the display-name people the Toolhub
    candidate pass walks. Aiming at the people set checked nine labels while
    nine hundred sat untouched.

    A persisted cursor walks the population in label order and wraps, which
    keeps each run bounded, gives every label a turn, and rate-limits retries
    of labels the registry does not know to once per full sweep.
    """
    now = utcnow()
    labels = sorted(
        {
            row[0]
            for row in s.execute(
                select(UnresolvedAttributionEvidence.normalized_label).where(
                    UnresolvedAttributionEvidence.withdrawn_at.is_(None),
                    or_(
                        UnresolvedAttributionEvidence.expires_at.is_(None),
                        UnresolvedAttributionEvidence.expires_at > now,
                    ),
                )
            ).all()
            if row[0] and people_policy.is_handle_shaped(row[0])
        }
    )
    if not labels:
        return [], ""
    # Anything already matching a publishable person's handle is resolvable
    # locally and needs no lookup.
    known = {
        normalized
        for person_id, normalized in s.execute(
            select(PersonIdentifier.person_id, PersonIdentifier.normalized_value).where(
                PersonIdentifier.is_current.is_(True),
                PersonIdentifier.namespace.in_((people_index.NS_WIKI_USERNAME, people_index.NS_TOOLFORGE_USERNAME)),
                PersonIdentifier.normalized_value.in_(labels),
            )
        ).all()
        if person_id in people_index.public_identity_ids(s)
    }
    pending = [label for label in labels if label not in known]
    if not pending:
        return [], ""
    cursor_row = s.get(ApiCacheMeta, REGISTRY_CURSOR_KEY)
    cursor = cursor_row.value if cursor_row is not None else ""
    after = [label for label in pending if label > cursor]
    batch = (after or pending)[: max(1, int(limit))]
    return batch, batch[-1]


def _resolve_registry_candidate_batch(
    s: Session,
    *,
    provider: public_identity.WikimediaIdentityProvider,
    label_limit: int,
    sleep: Any,  # noqa: ANN401 - injected for deterministic tests
) -> tuple[list[tuple[str, public_identity.WikimediaIdentity | None]], str]:
    """Finish every registry request before the reconciliation write phase."""
    batch, cursor = _registry_label_batch(s, limit=label_limit)
    resolved = []
    for index, label in enumerate(batch):
        if index:
            sleep(REGISTRY_MIN_INTERVAL_SECONDS)
        resolved.append((label, provider.lookup_username(label)))
    return resolved, cursor


def resolve_remote_batches(
    *,
    identity_resolver: PublicIdentityResolver | None = None,
    registry_provider: public_identity.WikimediaIdentityProvider | None = None,
    candidate_label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
    registry_label_limit: int = 0,
    sleep: Any = time.sleep,  # noqa: ANN401 - injected for deterministic tests
) -> tuple[
    list[tuple[ToolhubAccountProjection, list[Person], public_identity.ResolvedPublicIdentity | None]],
    tuple[list[tuple[str, public_identity.WikimediaIdentity | None]], str],
]:
    """Read candidates briefly, close the DB session, then resolve remotely."""
    with db.session_scope() as s:
        account_limit = max(1, min(int(candidate_label_limit), 100))
        identity_candidates = _candidate_account_groups(s, _candidate_source_people(s))[:account_limit]
        registry_batch, registry_cursor = (
            _registry_label_batch(s, limit=registry_label_limit) if registry_label_limit else ([], "")
        )

    resolver = identity_resolver or PublicIdentityResolver()
    resolved_identities = [
        (account, people, resolver.resolve(account.wikimedia_global_user_id or ""))
        for account, people in identity_candidates
    ]
    provider = registry_provider or public_identity.WikimediaIdentityProvider()
    resolved_registry = []
    for index, label in enumerate(registry_batch):
        if index:
            sleep(REGISTRY_MIN_INTERVAL_SECONDS)
        resolved_registry.append((label, provider.lookup_username(label)))
    return resolved_identities, (resolved_registry, registry_cursor)


def discover_registry_candidates(
    s: Session,
    *,
    provider: public_identity.WikimediaIdentityProvider | None = None,
    label_limit: int = DEFAULT_REGISTRY_LABEL_LIMIT,
    sleep: Any = time.sleep,  # noqa: ANN401 - injected for deterministic tests
    resolved_batch: tuple[list[tuple[str, public_identity.WikimediaIdentity | None]], str] | None = None,
) -> dict[str, int]:
    """Record identities for handle-shaped labels a public registry confirms.

    Every other path starts from an immutable id already held here. This one
    starts from catalog text, so it is bounded at every step: the shape gate
    decides which labels are asked about, a cursor bounds each run, and
    lookups are spaced.

    It records identity only. A confirmed account becomes a person keyed on
    its immutable global user id, which makes the label resolvable by the
    ordinary corroborated-handle rule the moment independent evidence ties
    that person to a tool. Nothing here publishes a relationship, and a person
    with none stays out of the public directory.
    """
    resolver = provider or public_identity.WikimediaIdentityProvider()
    checked = 0
    resolved = 0
    people_created = 0
    candidates, cursor = (
        resolved_batch
        if resolved_batch is not None
        else _resolve_registry_candidate_batch(
            s,
            provider=resolver,
            label_limit=label_limit,
            sleep=sleep,
        )
    )
    for _label, identity in candidates:
        checked += 1
        if identity is None:
            continue
        resolved += 1
        owner_id = _stable_identifier_owner(s, people_index.NS_WIKIMEDIA_GLOBAL_USER_ID, identity.global_user_id)
        if owner_id is not None:
            continue
        # A CentralAuth global id is an immutable stable identifier, the same
        # class the account syncs already mint people from, so this records a
        # real account rather than inventing one.
        person = people_index.ensure_person(
            s,
            display_name=identity.username,
            wikimedia_global_user_id=identity.global_user_id,
            wiki_username=identity.username,
            source=REGISTRY_SOURCE,
        )
        if person is not None:
            people_created += 1
        s.flush()
    if cursor:
        row = s.get(ApiCacheMeta, REGISTRY_CURSOR_KEY)
        if row is None:
            s.add(ApiCacheMeta(key=REGISTRY_CURSOR_KEY, value=cursor))
        else:
            row.value = cursor
            row.updated_at = utcnow()
    return {"checked": checked, "resolved": resolved, "peopleCreated": people_created}


def _resolve_identity_candidate_batch(
    s: Session,
    *,
    identity_resolver: PublicIdentityResolver,
    label_limit: int,
) -> list[tuple[ToolhubAccountProjection, list[Person], public_identity.ResolvedPublicIdentity | None]]:
    """Finish every remote identity bridge before shared identity rows are written."""
    account_limit = max(1, min(int(label_limit), 100))
    candidates = _candidate_account_groups(s, _candidate_source_people(s))
    return [
        (account, people, identity_resolver.resolve(account.wikimedia_global_user_id or ""))
        for account, people in candidates[:account_limit]
    ]


def discover_identity_candidates(
    s: Session,
    *,
    run_id: int,
    identity_resolver: PublicIdentityResolver,
    label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
    resolved_batch: list[tuple[ToolhubAccountProjection, list[Person], public_identity.ResolvedPublicIdentity | None]]
    | None = None,
) -> dict[str, int]:
    """Resolve exact public accounts and auto-link only SUL-backed tool evidence."""
    created = 0
    linked = 0
    conflicts = 0
    candidates = (
        resolved_batch
        if resolved_batch is not None
        else _resolve_identity_candidate_batch(
            s,
            identity_resolver=identity_resolver,
            label_limit=label_limit,
        )
    )
    for account, people, resolved in candidates:
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
                toolforge_username=toolforge.developer_username if toolforge else "",
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
                "toolforgeDeveloperUsername": toolforge.developer_username if toolforge else "",
                "toolforgeShellUsername": toolforge.uid if toolforge else "",
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


# Measured 2026-08-27: 0.009s a label, so 500 was 4 seconds of the hour. Raised
# to what the interval can actually absorb, which is what decides whether the
# 1,171 unresolved bindings converge this week or next quarter.
DEFAULT_RECONVERGE_LIMIT = 5_000
RECONVERGE_CURSOR_KEY = "unresolved_reconverge_cursor"


def _reconverge_cursor(s: Session) -> int:
    row = s.get(ApiCacheMeta, RECONVERGE_CURSOR_KEY)
    try:
        return max(0, int(row.value)) if row is not None else 0
    except (TypeError, ValueError):
        return 0


def _store_reconverge_cursor(s: Session, cursor: int) -> None:
    row = s.get(ApiCacheMeta, RECONVERGE_CURSOR_KEY)
    if row is None:
        s.add(ApiCacheMeta(key=RECONVERGE_CURSOR_KEY, value=str(cursor)))
        return
    row.value = str(cursor)
    row.updated_at = utcnow()


def reconverge_attributions(s: Session, *, limit: int = DEFAULT_RECONVERGE_LIMIT) -> dict[str, int]:
    """Re-decide stored unresolved observations against present evidence.

    Corroboration is the one attribution rule whose answer depends on evidence
    that arrives outside the observation being judged: a label resolves once
    some other source proves the same person holds the same tool. Without this
    pass an observation is only ever judged at ingest time, so its verdict is
    fixed by whichever feed happened to run first, and the corroborating edge
    that lands an hour later changes nothing until that feed is re-ingested for
    that tool. The backlog then reflects feed order rather than what the catalog
    can prove, and a widened rule reaches the existing rows only as their feeds
    happen to come round again.

    Re-deciding them here is what makes reconciliation converge on evidence.
    The batch is bounded two ways: a correlated ``EXISTS`` that mirrors the
    corroboration query's own candidate predicates exactly, so only rows where
    the rule could possibly now succeed are read at all, and a rolling id cursor
    that resumes where the last pass stopped and wraps at the tail, so a
    permanently unresolvable row cannot starve the ones behind it.
    """
    examined, promoted, tools = _reconverge_batch(s, batch_size=max(1, int(limit)))
    return {"examined": examined, "promoted": promoted, "tools": len(tools)}


def _reconverge_batch(s: Session, *, batch_size: int) -> tuple[int, int, set[str]]:
    """One bounded pass: rows examined, rows promoted, and the tools they touched.

    Split out from the public entry point so a chunked caller can union the tool
    names across chunks rather than sum per-chunk counts, which keeps `tools` a
    count of distinct tools however the backlog happens to distribute across
    chunk boundaries.
    """
    now = utcnow()
    # Mirrors corroborated_handle_person's candidate query. Mirroring it exactly
    # is the correctness condition: a looser filter wastes work, a tighter one
    # would silently skip rows the rule would have promoted.
    corroborating_edge_exists = (
        select(ToolRelationshipEvidence.id)
        .where(
            ToolRelationshipEvidence.tool_name == UnresolvedAttributionEvidence.tool_name,
            ToolRelationshipEvidence.source != UnresolvedAttributionEvidence.source,
            ToolRelationshipEvidence.verification_status == AUTHOR_CLAIM_VERIFIED,
            ToolRelationshipEvidence.withdrawn_at.is_(None),
        )
        .exists()
    )
    cursor = _reconverge_cursor(s)
    rows = list(
        s.execute(
            select(UnresolvedAttributionEvidence)
            .where(
                UnresolvedAttributionEvidence.withdrawn_at.is_(None),
                UnresolvedAttributionEvidence.id > cursor,
                or_(
                    UnresolvedAttributionEvidence.expires_at.is_(None),
                    UnresolvedAttributionEvidence.expires_at > now,
                ),
                corroborating_edge_exists,
            )
            .order_by(UnresolvedAttributionEvidence.id)
            .limit(batch_size)
        ).scalars()
    )
    promoted_tools: set[str] = set()
    promoted = 0
    for row in rows:
        if people_index.promote_unresolved_attribution(s, row) is not None:
            promoted += 1
            promoted_tools.add(row.tool_name)
    s.flush()
    for tool_name in sorted(promoted_tools):
        people_index.resolve_tool_relationships(s, tool_name)
        summary = s.get(ToolSummaryCache, tool_name)
        if summary is not None:
            s.delete(summary)
    # A short batch means the tail is reached, so the next pass starts from the
    # head. Coverage is therefore complete over successive passes without any
    # pass having to read the whole backlog.
    _store_reconverge_cursor(s, 0 if len(rows) < batch_size else rows[-1].id)
    return len(rows), promoted, promoted_tools


DEFAULT_RECONVERGE_CHUNK = 25


def reconverge_in_chunks(
    *, limit: int = DEFAULT_RECONVERGE_LIMIT, chunk: int = DEFAULT_RECONVERGE_CHUNK
) -> dict[str, int]:
    """Reconverge a bounded backlog in committed chunks instead of one transaction.

    Identical work and the same rolling cursor as `reconverge_attributions`; the
    only difference is where the commits fall, and that is the entire point.
    Promoting an observation deletes the tool's `tool_summary_cache` row, and
    under REPEATABLE-READ a DELETE holds a next-key lock over the gap it emptied
    until the transaction commits -- so one transaction over the whole batch
    blocks inserts into that table for as long as the batch runs. The continuous
    repository scan inserts into exactly that table, waits the full
    `innodb_lock_wait_timeout` of 50 seconds, and logs 1205.

    Retrying cannot rescue a waiter whose holder outlives the timeout, which is
    why the retry helper wrapped around several of the victims did not stop
    this. Committing sooner can, and it costs nothing here: each chunk is
    already an independently correct pass over its own cursor range, so a chunk
    boundary is a place this pass could have stopped anyway.

    Only the standalone job takes this path. `run()` reconverges inside the
    weekly rebuild's own transaction, where a separate commit boundary would
    break the atomicity that pass is built on.
    """
    ceiling = max(1, int(limit))
    batch = max(1, min(ceiling, int(chunk)))
    examined = promoted = 0
    tools: set[str] = set()
    while examined < ceiling:
        remaining = min(batch, ceiling - examined)
        with db.session_scope() as s:
            seen, made, names = _reconverge_batch(s, batch_size=remaining)
        examined += seen
        promoted += made
        tools |= names
        # A short chunk is the tail, and `_reconverge_batch` has already reset
        # the cursor to the head. Continuing would re-read the rows this pass
        # just judged rather than make progress.
        if seen < remaining:
            break
    return {"examined": examined, "promoted": promoted, "tools": len(tools)}


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


def run(  # noqa: PLR0913, PLR0915 - explicit providers keep reconciliation deterministic in tests
    s: Session,
    *,
    mode: str = MODE_DRY_RUN,
    discover_candidates: bool = False,
    identity_resolver: PublicIdentityResolver | None = None,
    candidate_label_limit: int = DEFAULT_CANDIDATE_LABEL_LIMIT,
    registry_label_limit: int = 0,
    rebuild_tools: bool = True,
    sync_accounts: bool = True,
    refresh_sources: bool = True,
    reconverge_limit: int = DEFAULT_RECONVERGE_LIMIT,
    source_changes_since: Any | None = None,  # noqa: ANN401 - persisted naive datetime
    resolved_identity_candidates: list[
        tuple[ToolhubAccountProjection, list[Person], public_identity.ResolvedPublicIdentity | None]
    ]
    | None = None,
    resolved_registry_candidates: tuple[list[tuple[str, public_identity.WikimediaIdentity | None]], str] | None = None,
) -> dict[str, Any]:
    """Audit or rebuild Toolhub-backed evidence and local people projections."""
    if mode not in {MODE_DRY_RUN, MODE_APPLY}:
        raise PersonReconciliationError(mode)
    run_row = PersonReconciliationRun(mode=mode, status="running", started_at=utcnow())
    s.add(run_row)
    s.flush()
    identity_changed_since = source_changes_since or utcnow()
    try:
        before = build_plan(s)
        # The hourly identities-only worker starts from materialized evidence,
        # so exhaust its remote providers before the first shared people/user
        # write. A full rebuild must first create fresh candidate evidence and
        # therefore keeps discovery after that local phase. OAuth no longer
        # touches people rows, and user links are kept last below.
        identity_resolver = identity_resolver or PublicIdentityResolver()
        resolved_identity_candidates = (
            resolved_identity_candidates
            if resolved_identity_candidates is not None
            else (
                _resolve_identity_candidate_batch(
                    s,
                    identity_resolver=identity_resolver,
                    label_limit=candidate_label_limit,
                )
                if mode == MODE_APPLY and discover_candidates and not rebuild_tools
                else None
            )
        )
        resolved_registry_candidates = (
            resolved_registry_candidates
            if resolved_registry_candidates is not None
            else (
                _resolve_registry_candidate_batch(
                    s,
                    provider=public_identity.WikimediaIdentityProvider(),
                    label_limit=registry_label_limit,
                    sleep=time.sleep,
                )
                if mode == MODE_APPLY and discover_candidates and registry_label_limit and not rebuild_tools
                else None
            )
        )
        if mode == MODE_APPLY:
            account_bindings = (
                identity_graph.synchronize(s)
                if sync_accounts
                else {
                    "toolhubBindings": 0,
                    "toolhubConflicts": 0,
                    "usersHydrated": 0,
                    "verified": 0,
                    "candidate": 0,
                    "conflict": 0,
                    "unresolved": 0,
                    "membershipRelationships": 0,
                    "canonicalMembershipRelationships": 0,
                    "fallbackMembershipRelationships": 0,
                    "unmappedMemberships": 0,
                    "unboundMemberships": 0,
                    "relationshipCacheHit": 0,
                }
            )
            account_binding_conflicts_queued = _record_account_binding_conflicts(s, run_row.id)
            identity_qualities_refreshed = people_index.refresh_identity_qualities(s)
            non_actionable_conflicts_retired = _retire_non_actionable_display_conflicts(s)
            if rebuild_tools:
                for name in before["toolNames"]:
                    _reconcile_tool(s, name)
            candidate_result = (
                discover_identity_candidates(
                    s,
                    run_id=run_row.id,
                    identity_resolver=identity_resolver,
                    label_limit=candidate_label_limit,
                    resolved_batch=resolved_identity_candidates,
                )
                if discover_candidates
                else {"created": 0, "linked": 0, "conflicts": 0}
            )
            # Bounded and last: it is the only pass that starts from catalog
            # text, so it runs a small number of external lookups per pass and
            # its results publish nothing without corroboration.
            registry_result = (
                discover_registry_candidates(
                    s,
                    label_limit=registry_label_limit,
                    resolved_batch=resolved_registry_candidates,
                )
                if discover_candidates and registry_label_limit
                else {"checked": 0, "resolved": 0, "peopleCreated": 0}
            )
            wikimedia_user_space_result = wikimedia_user_reconciliation.synchronize(s)
            source_attestation_summary = {
                "sources": 0,
                "tools": 0,
                "authorEvidence": 0,
                "maintainerEvidence": 0,
            }
            catalog_anchor_summary = {"tools": 0, "authorEvidence": 0, "ambiguous": 0, "cacheHit": 0}
            with db.advisory_lock(source_attestations.SOURCE_WRITER_LOCK) as source_lock:
                if not source_lock:
                    source_attestation_summary["locked"] = True
                    catalog_anchor_summary["locked"] = True
                else:
                    if refresh_sources:
                        source_attestation_summary = source_attestations.refresh_incremental(
                            s,
                            identity_changed_since=identity_changed_since,
                        )
                    # Reads the verified edges every phase above published, so it runs
                    # after them — and under the same lock, because it publishes
                    # source-derived evidence like the pass it follows.
                    catalog_anchor_summary = source_attestations.refresh_catalog_anchor(s)
            # Last of the evidence phases on purpose: it decides observations
            # against evidence, so it must see everything this pass created.
            reconverge_summary = (
                reconverge_attributions(s, limit=reconverge_limit)
                if reconverge_limit
                else {"examined": 0, "promoted": 0, "tools": 0}
            )
            if (
                rebuild_tools
                or candidate_result["linked"]
                or wikimedia_user_space_result["verifiedTools"]
                or wikimedia_user_space_result["retiredTools"]
                or source_attestation_summary["tools"]
                or catalog_anchor_summary["tools"]
                or reconverge_summary["promoted"]
            ):
                people_index.refresh_activity_summaries(s)
            # User/person links are the only reconciliation writes that can
            # overlap the authentication authority. Keep them last so their
            # row-lock lifetime is bounded by the final local summary queries.
            for user in s.execute(select(User).order_by(User.id)).scalars():
                people_index.link_user(s, user)
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
            registry_result = {"checked": 0, "resolved": 0, "peopleCreated": 0}
            wikimedia_user_space_result = wikimedia_user_reconciliation.empty_stats()
            identity_qualities_refreshed = 0
            non_actionable_conflicts_retired = 0
            reconverge_summary = {"examined": 0, "promoted": 0, "tools": 0}
            source_attestation_summary = {
                "sources": 0,
                "tools": 0,
                "authorEvidence": 0,
                "maintainerEvidence": 0,
            }
            catalog_anchor_summary = {"tools": 0, "authorEvidence": 0, "ambiguous": 0, "cacheHit": 0}
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
            "registryChecked": registry_result["checked"],
            "registryResolved": registry_result["resolved"],
            "registryPeopleCreated": registry_result["peopleCreated"],
            "identityMappingsApplied": candidate_result["linked"],
            "stableIdentityConflicts": candidate_result["conflicts"],
            "accountBindings": account_bindings,
            "wikimediaUserSpaceReconciliation": wikimedia_user_space_result,
            "sourceAttestations": source_attestation_summary,
            "catalogAuthorAnchor": catalog_anchor_summary,
            "attributionReconvergence": reconverge_summary,
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
