# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic historical reconciliation for people and tool relationships."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, or_, select

from backend import db, maintainer_index, people_index
from backend.models import (
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    PersonReconciliationConflict,
    PersonReconciliationMapping,
    PersonReconciliationQueue,
    PersonReconciliationRun,
    ToolAuthorClaim,
    ToolMaintainerEdge,
    ToolPersonRelationship,
    utcnow,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MODE_DRY_RUN = "dry-run"
MODE_APPLY = "apply"
DEFAULT_QUEUE_LIMIT = 100
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
STABLE_NAMESPACES = ("toolhub", "wiki")
NAMESPACE_PRIORITY = {namespace: index for index, namespace in enumerate(STABLE_NAMESPACES)}


class PersonReconciliationError(ValueError):
    """Invalid reconciliation mode or unsafe reconciliation input."""


def enqueue_tool_names(tool_names: list[str] | set[str], *, reason: str = "data_ingestion") -> int:
    """Queue changed tools after their write transaction has committed.

    The separate transaction is deliberate: canonical cache writes also happen
    on anonymous API requests, and queue bookkeeping must not participate in
    their upstream/cache transaction.
    """
    names = sorted({_clean(name) for name in tool_names if _clean(name)})
    if not names:
        return 0
    now = utcnow()
    with db.session_scope() as s:
        for name in names:
            row = s.get(PersonReconciliationQueue, name)
            if row is None:
                s.add(PersonReconciliationQueue(tool_name=name, reason=_clean(reason, 64), enqueued_at=now))
                continue
            row.reason = _clean(reason, 64) or row.reason
            row.enqueued_at = now
            row.next_attempt_at = None
            row.last_error = None
    return len(names)


def process_queue(*, limit: int = DEFAULT_QUEUE_LIMIT) -> dict[str, int]:
    """Reconcile a bounded batch of changed tools without a global scan."""
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
                cache = s.get(CanonicalToolCache, name)
                if cache is not None and isinstance(cache.record, dict):
                    maintainer_index.replace_toolhub_metadata_edges(s, name, cache.record)
                maintainer_index.sync_author_claim_edges(s, tool_names=[name])
                row.last_processed_at = utcnow()
                row.attempts = 0
                row.next_attempt_at = None
                row.last_error = None
            processed += 1
        except Exception as exc:  # noqa: BLE001 - persist retry state before continuing the batch
            failed += 1
            with db.session_scope() as s:
                row = s.get(PersonReconciliationQueue, name)
                if row is not None:
                    row.attempts += 1
                    row.next_attempt_at = utcnow() + timedelta(minutes=min(60, 2 ** min(row.attempts, 6)))
                    row.last_error = _clean(str(exc), 2000)
    return {"claimed": len(names), "processed": processed, "failed": failed}


class _UnionFind:
    """Small deterministic disjoint-set implementation for identity aliases."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, value: str) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: str) -> str:
        self.add(value)
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            parent = self.parent[value]
            self.parent[value] = root
            value = parent
        return root

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        # Lexical root selection makes the component shape independent of row order.
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


def _clean(value: Any, limit: int = 255) -> str:  # noqa: ANN401 - untrusted stored JSON
    return str(value or "").strip()[:limit]


def _normalized(value: Any) -> str:  # noqa: ANN401 - untrusted stored JSON
    return _clean(value).casefold()


def _identifier_node(namespace: str, value: str) -> str:
    return f"i:{namespace}:{_normalized(value)}"


def _person_node(person_id: int) -> str:
    return f"p:{person_id}"


def _stable_pairs_from_edge(edge: ToolMaintainerEdge) -> list[tuple[str, str]]:
    pairs = []
    if _clean(edge.toolhub_username):
        pairs.append(("toolhub", _clean(edge.toolhub_username)))
    if _clean(edge.wiki_username):
        pairs.append(("wiki", _clean(edge.wiki_username)))
    return pairs


def _stable_pairs_from_record(record: dict[str, Any]) -> list[list[tuple[str, str]]]:
    """Return stable identifiers that co-occur in each canonical author object."""
    raw_authors = record.get("author")
    authors = raw_authors if isinstance(raw_authors, list) else [raw_authors]
    groups: list[list[tuple[str, str]]] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        pairs = []
        if _clean(author.get("developer_username")):
            pairs.append(("toolhub", _clean(author["developer_username"])))
        if _clean(author.get("wiki_username")):
            pairs.append(("wiki", _clean(author["wiki_username"])))
        if pairs:
            groups.append(pairs)
    return groups


def _canonical_stable_pair(key: str) -> tuple[str, str] | None:
    namespace, separator, value = _clean(key).partition(":")
    if not separator or namespace not in STABLE_NAMESPACES or not value:
        return None
    return namespace, value


def _preferred_identifier(pairs: set[tuple[str, str]]) -> tuple[str, str] | None:
    return min(
        pairs,
        key=lambda pair: (NAMESPACE_PRIORITY.get(pair[0], 99), _normalized(pair[1]), pair[1]),
        default=None,
    )


def _seed_people(s: Session, union: _UnionFind) -> dict[int, set[tuple[str, str]]]:
    person_pairs: dict[int, set[tuple[str, str]]] = {}
    people = list(s.execute(select(Person).order_by(Person.id)).scalars())
    for person in people:
        union.add(_person_node(person.id))
        pair = _canonical_stable_pair(person.canonical_key)
        if pair:
            person_pairs.setdefault(person.id, set()).add(pair)
            union.union(_person_node(person.id), _identifier_node(*pair))
    return person_pairs


def _link_identifiers(s: Session, union: _UnionFind, person_pairs: dict[int, set[tuple[str, str]]]) -> None:
    for identifier in s.execute(select(PersonIdentifier).order_by(PersonIdentifier.id)).scalars():
        pair = (identifier.namespace, identifier.value)
        person_pairs.setdefault(identifier.person_id, set()).add(pair)
        union.union(_person_node(identifier.person_id), _identifier_node(*pair))


def _link_edges(s: Session, union: _UnionFind) -> None:
    for edge in s.execute(select(ToolMaintainerEdge).order_by(ToolMaintainerEdge.id)).scalars():
        pairs = _stable_pairs_from_edge(edge)
        for namespace, value in pairs:
            union.add(_identifier_node(namespace, value))
        for pair in pairs[1:]:
            union.union(_identifier_node(*pairs[0]), _identifier_node(*pair))
        current = s.execute(select(Person).where(Person.canonical_key == edge.maintainer_key)).scalar_one_or_none()
        if current is not None and pairs:
            union.union(_person_node(current.id), _identifier_node(*pairs[0]))


def _link_canonical_cache(s: Session, union: _UnionFind) -> None:
    for cache in s.execute(select(CanonicalToolCache).order_by(CanonicalToolCache.tool_name)).scalars():
        if isinstance(cache.record, dict):
            for pairs in _stable_pairs_from_record(cache.record):
                for namespace, value in pairs:
                    union.add(_identifier_node(namespace, value))
                for pair in pairs[1:]:
                    union.union(_identifier_node(*pairs[0]), _identifier_node(*pair))


def _build_union(s: Session) -> tuple[dict[str, set[int]], dict[int, set[tuple[str, str]]]]:
    union = _UnionFind()
    person_pairs = _seed_people(s, union)
    _link_identifiers(s, union, person_pairs)
    _link_edges(s, union)
    _link_canonical_cache(s, union)
    component_people: dict[str, set[int]] = {}
    for person_id in person_pairs:
        root = union.find(_person_node(person_id))
        component_people.setdefault(root, set()).add(person_id)
    return component_people, person_pairs


def _display_conflicts(s: Session, component_people: dict[str, set[int]]) -> list[dict[str, Any]]:
    people = {person.id: person for person in s.execute(select(Person)).scalars()}
    by_name: dict[str, list[int]] = {}
    for person in people.values():
        name = _normalized(person.display_name)
        if name:
            by_name.setdefault(name, []).append(person.id)
    conflicts = []
    for name, ids in sorted(by_name.items()):
        roots = {root for root, people_ids in component_people.items() if set(ids) & people_ids}
        display_only = [person_id for person_id in ids if people[person_id].identity_quality == "display_name"]
        if len(roots) > 1 or len(display_only) > 1:
            conflicts.append(
                {
                    "type": "ambiguous_display_name",
                    "value": name,
                    "personIds": sorted(ids),
                    "details": "Display names are not used as merge evidence.",
                }
            )
    return conflicts


def build_plan(s: Session) -> dict[str, Any]:
    """Build a deterministic reconciliation plan without changing database rows."""
    component_people, person_pairs = _build_union(s)
    people = {person.id: person for person in s.execute(select(Person)).scalars()}
    groups = []
    for root, person_ids in sorted(component_people.items()):
        pairs = set()
        for person_id in person_ids:
            pairs.update(person_pairs.get(person_id, set()))
        if len(person_ids) == 1 and not pairs:
            continue
        preferred = _preferred_identifier(pairs)
        target_id = min(
            person_ids,
            key=lambda person_id: (
                0
                if preferred and people[person_id].canonical_key == f"{preferred[0]}:{_normalized(preferred[1])}"
                else 1,
                people[person_id].id,
            ),
        )
        target_key = f"{preferred[0]}:{_normalized(preferred[1])}" if preferred else people[target_id].canonical_key
        groups.append(
            {
                "root": root,
                "personIds": sorted(person_ids),
                "targetId": target_id,
                "targetKey": target_key,
                "stableIdentifiers": sorted(f"{namespace}:{_normalized(value)}" for namespace, value in pairs),
                "reason": (
                    "co_occurring_stable_identifiers"
                    if len(person_ids) > 1
                    else "canonicalize_stable_identifier"
                ),
            }
        )
    cached_tools = [
        row[0]
        for row in s.execute(select(CanonicalToolCache.tool_name).order_by(CanonicalToolCache.tool_name)).all()
    ]
    edge_tools = [
        row[0]
        for row in s.execute(
            select(ToolMaintainerEdge.tool_name).distinct().order_by(ToolMaintainerEdge.tool_name)
        ).all()
    ]
    conflicts = _display_conflicts(s, component_people)
    return {
        "groups": groups,
        "conflicts": conflicts,
        "peopleScanned": len(people),
        "stableIdentifiersScanned": sum(len(values) for values in person_pairs.values()),
        "canonicalCacheTools": len(cached_tools),
        "edgeTools": len(edge_tools),
        "relationshipsScanned": s.scalar(select(func.count()).select_from(ToolPersonRelationship)) or 0,
        "toolNames": sorted(set(cached_tools) | set(edge_tools)),
    }


def _materialize_historical_edges(s: Session) -> list[str]:
    """Rebuild legacy evidence edges from the local canonical cache and claims."""
    names = set()
    for cache in s.execute(select(CanonicalToolCache).order_by(CanonicalToolCache.tool_name)).scalars():
        if isinstance(cache.record, dict):
            names.add(cache.tool_name)
            maintainer_index.replace_toolhub_metadata_edges(s, cache.tool_name, cache.record)
    names.update(row[0] for row in s.execute(select(ToolMaintainerEdge.tool_name).distinct()).all())
    names.update(row[0] for row in s.execute(select(ToolAuthorClaim.tool_name).distinct()).all())
    maintainer_index.sync_author_claim_edges(s, tool_names=sorted(names))
    for name in sorted(names):
        people_index.sync_tool_people(s, name)
    return sorted(names)


def _apply_groups(s: Session, plan: dict[str, Any]) -> int:
    mappings = 0
    s.execute(delete(ToolPersonRelationship))
    s.flush()
    for group in plan["groups"]:
        people = {
            person.id: person
            for person in s.execute(select(Person).where(Person.id.in_(group["personIds"]))).scalars()
        }
        target = people.get(group["targetId"])
        if target is None:
            continue
        target_ids = set(people) - {target.id}
        identifiers = list(s.execute(select(PersonIdentifier).where(PersonIdentifier.person_id.in_(people))).scalars())
        for identifier in identifiers:
            if identifier.person_id == target.id:
                continue
            existing = s.execute(
                select(PersonIdentifier).where(
                    PersonIdentifier.namespace == identifier.namespace,
                    PersonIdentifier.normalized_value == identifier.normalized_value,
                    PersonIdentifier.person_id == target.id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                s.delete(identifier)
            else:
                identifier.person_id = target.id
        for person_id in sorted(target_ids):
            s.delete(people[person_id])
            mappings += 1
        s.flush()
        target.canonical_key = group["targetKey"]
        target.identity_quality = "stable" if group["stableIdentifiers"] else "display_name"
        target.updated_at = utcnow()
    s.flush()
    for name in plan["toolNames"]:
        people_index.sync_tool_people(s, name)
    return mappings


def _record_plan(s: Session, run: PersonReconciliationRun, plan: dict[str, Any]) -> None:
    for group in plan["groups"]:
        for person_id in group["personIds"]:
            person = s.get(Person, person_id)
            if person is None:
                continue
            is_target = person_id == group["targetId"]
            s.add(
                PersonReconciliationMapping(
                    run_id=run.id,
                    source_person_id=person_id,
                    target_person_id=group["targetId"],
                    source_key=person.canonical_key,
                    target_key=group["targetKey"],
                    decision="retain" if is_target else "merge",
                    reason=group["reason"],
                    confidence=100 if group["stableIdentifiers"] else 40,
                )
            )
    for conflict in plan["conflicts"]:
        s.add(
            PersonReconciliationConflict(
                run_id=run.id,
                conflict_type=conflict["type"],
                value=conflict["value"],
                details={"personIds": conflict["personIds"], "reason": conflict["details"]},
            )
        )


def run(s: Session, *, mode: str = MODE_DRY_RUN) -> dict[str, Any]:
    """Run one audited dry-run or apply reconciliation transaction."""
    if mode not in {MODE_DRY_RUN, MODE_APPLY}:
        raise PersonReconciliationError
    started = utcnow()
    run_row = PersonReconciliationRun(mode=mode, status="running", started_at=started)
    s.add(run_row)
    s.flush()
    try:
        if mode == MODE_APPLY:
            _materialize_historical_edges(s)
        plan = build_plan(s)
        _record_plan(s, run_row, plan)
        applied = _apply_groups(s, plan) if mode == MODE_APPLY else 0
        summary = {
            "mode": mode,
            "peopleScanned": plan["peopleScanned"],
            "groups": len(plan["groups"]),
            "mergeCandidates": sum(max(0, len(group["personIds"]) - 1) for group in plan["groups"]),
            "mergedPeople": applied,
            "conflicts": len(plan["conflicts"]),
            "stableIdentifiersScanned": plan["stableIdentifiersScanned"],
            "canonicalCacheTools": plan["canonicalCacheTools"],
            "edgeTools": plan["edgeTools"],
            "relationshipsRebuilt": len(plan["toolNames"]) if mode == MODE_APPLY else 0,
        }
    except Exception as exc:
        run_row.status = RUN_FAILED
        run_row.completed_at = utcnow()
        run_row.error = _clean(str(exc), 2000)
        raise
    else:
        run_row.status = RUN_COMPLETED
        run_row.completed_at = utcnow()
        run_row.summary = summary
        return summary
