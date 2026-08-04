# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic reconciliation for canonical people and evidence projections."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from backend import db, maintainer_index, people_index
from backend.models import (
    CanonicalToolCache,
    Person,
    PersonReconciliationConflict,
    PersonReconciliationQueue,
    PersonReconciliationRun,
    ToolAuthorClaim,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    User,
    utcnow,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MODE_DRY_RUN = "dry-run"
MODE_APPLY = "apply"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
DEFAULT_QUEUE_LIMIT = 100


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
    people_index.resolve_tool_relationships(s, name)


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
    return [
        {
            "type": "ambiguous_display_name",
            "value": name,
            "details": "Display names are presentation data and are never automatic merge evidence.",
        }
        for name, _count in rows
    ]


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


def run(s: Session, *, mode: str = MODE_DRY_RUN) -> dict[str, Any]:
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
        after = build_plan(s)
        for conflict in after["conflicts"]:
            s.add(
                PersonReconciliationConflict(
                    run_id=run_row.id,
                    conflict_type=conflict["type"],
                    value=conflict["value"],
                    details={"reason": conflict["details"]},
                )
            )
        summary = {
            "mode": mode,
            "peopleScanned": after["peopleScanned"],
            "evidenceScanned": after["evidenceScanned"],
            "relationships": after["relationshipsScanned"],
            "conflicts": len(after["conflicts"]),
            "toolsRebuilt": len(after["toolNames"]) if mode == MODE_APPLY else 0,
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
