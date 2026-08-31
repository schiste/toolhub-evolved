# SPDX-License-Identifier: GPL-3.0-or-later
"""Field-level filling of the local catalog, broken down by where each value came from.

The statistics snapshot answers "how much of the catalog is filled in". This
answers the question underneath it: *who filled it*. Every projected field on
every tool carries the ordered evidence that produced it, so the same pass can
report both the hole and the hand that filled it.

Sources are reported in four buckets rather than eight because the eight are a
precedence vocabulary, not an audience-facing one. The split that matters to a
reader is whether a person asserted the value, a machine-readable feed declared
it, a static analyzer read it off the code, or a language model wrote it -- and
the last two are separated because they behave differently: only
``llm_inference`` is fill-only, so it can never displace a value some other
source stated, while ``repository_analysis`` asserts and can become the
effective value of a field nobody else filled.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import db
from backend.catalog_projection import (
    LIST_FIELDS,
    PROJECTED_FIELDS,
    SCALAR_FIELDS,
    SOURCE_CANONICAL,
    SOURCE_CONFIDENCE,
    SOURCE_CRAWLER,
    SOURCE_CURATION,
    SOURCE_DISCOVERY,
    SOURCE_GADGET,
    SOURCE_INFERENCE,
    SOURCE_REPOSITORY,
    SOURCE_WIKIMEDIA_USER_SCRIPT,
    STATUS_READY,
)
from backend.models import ApiCacheMeta, CatalogToolProjection, utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

SNAPSHOT_KEY = "catalog_coverage_v1"
#: Matches the statistics snapshot: a request serves what the refresh job last
#: stored, and only rebuilds when nothing exists or the copy is older than this.
SNAPSHOT_STALE_LIMIT = timedelta(hours=6)

BUCKET_HUMAN = "human"
BUCKET_TOOLINFO = "toolinfo"
BUCKET_CODE = "code"
BUCKET_AI = "ai"
#: Order is the reading order of the page, strongest assertion first.
BUCKETS = (BUCKET_HUMAN, BUCKET_TOOLINFO, BUCKET_CODE, BUCKET_AI)

#: Which bucket each projection source is reported under. Exhaustive over the
#: projection vocabulary on purpose -- an unmapped source must fail loudly in
#: tests rather than silently vanish from a total the page presents as complete.
BUCKET_BY_SOURCE = {
    SOURCE_CURATION: BUCKET_HUMAN,
    SOURCE_WIKIMEDIA_USER_SCRIPT: BUCKET_HUMAN,
    SOURCE_GADGET: BUCKET_HUMAN,
    SOURCE_CANONICAL: BUCKET_TOOLINFO,
    SOURCE_CRAWLER: BUCKET_TOOLINFO,
    SOURCE_DISCOVERY: BUCKET_TOOLINFO,
    SOURCE_REPOSITORY: BUCKET_CODE,
    SOURCE_INFERENCE: BUCKET_AI,
}


def _bucket(source: str) -> str:
    """Report an unknown source under its own name rather than losing it.

    A source added to the projection and not to `BUCKET_BY_SOURCE` would
    otherwise be counted as filled while belonging to no bucket, so the
    per-bucket numbers would silently stop summing to the filled total.
    """
    return BUCKET_BY_SOURCE.get(source, f"unmapped:{source}")


def _primary(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the one entry a field's value is attributed to.

    A scalar field has exactly one effective entry, so this is that entry. A
    list field can be merged from several sources at once, and attributing it
    to all of them would make the buckets sum past the number of filled fields;
    the highest-confidence contributor is the honest single answer, with the
    rest reported separately as `contributing`.
    """
    effective = [entry for entry in entries if entry.get("effective")]
    if not effective:
        return None
    return max(effective, key=lambda entry: (entry.get("confidence") or 0, entry.get("observedAt") or ""))


class _FieldTally:
    """Counts for one projected field across every tool."""

    def __init__(self, field: str) -> None:
        self.field = field
        self.filled = 0
        self.primary: Counter[str] = Counter()
        self.contributing: Counter[str] = Counter()
        self.shadowed: Counter[str] = Counter()

    def observe(self, entries: list[dict[str, Any]]) -> None:
        """Fold one tool's evidence for this field into the tally."""
        primary = _primary(entries)
        if primary is not None:
            self.filled += 1
            self.primary[_bucket(str(primary.get("source", "")))] += 1
        seen_effective: set[str] = set()
        seen_shadowed: set[str] = set()
        for entry in entries:
            bucket = _bucket(str(entry.get("source", "")))
            if entry.get("effective"):
                seen_effective.add(bucket)
            else:
                seen_shadowed.add(bucket)
        for bucket in seen_effective:
            self.contributing[bucket] += 1
        # A bucket that also won the field is not reported as overridden there.
        for bucket in seen_shadowed - seen_effective:
            self.shadowed[bucket] += 1

    def document(self, total: int) -> dict[str, Any]:
        """Render this tally as the page reads it."""
        return {
            "field": self.field,
            "kind": "list" if self.field in LIST_FIELDS else "scalar",
            "filled": self.filled,
            "missing": max(0, total - self.filled),
            "percent": round(self.filled * 100 / total, 1) if total else 0.0,
            "primary": {bucket: self.primary.get(bucket, 0) for bucket in BUCKETS},
            "contributing": {bucket: self.contributing.get(bucket, 0) for bucket in BUCKETS},
            "shadowed": {bucket: self.shadowed.get(bucket, 0) for bucket in BUCKETS},
            "unmapped": {
                bucket: count for bucket, count in sorted(self.primary.items()) if bucket.startswith("unmapped:")
            },
        }


def build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Build one deterministic field-coverage document from local projections.

    Streams the projection table naming only the two columns it reads. The
    provenance blob is the expensive part of each row, so selecting the mapped
    entity here would carry every other column of a table that grows with the
    catalog.
    """
    checked_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    tallies = {field: _FieldTally(field) for field in PROJECTED_FIELDS}
    total = 0
    pending = 0

    statement = select(CatalogToolProjection.provenance, CatalogToolProjection.status).execution_options(yield_per=500)
    for provenance, status in session.execute(statement):
        if status != STATUS_READY:
            pending += 1
            continue
        total += 1
        blob = provenance if isinstance(provenance, dict) else {}
        for field, tally in tallies.items():
            entries = blob.get(field)
            tally.observe(entries if isinstance(entries, list) else [])

    fields = [tallies[field].document(total) for field in PROJECTED_FIELDS]
    totals_by_bucket: Counter[str] = Counter()
    for entry in fields:
        for bucket, count in entry["primary"].items():
            totals_by_bucket[bucket] += count
    filled_total = sum(entry["filled"] for entry in fields)
    slots = total * len(PROJECTED_FIELDS)

    return {
        "generatedAt": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tools": total,
        "pendingTools": pending,
        "fieldCount": len(PROJECTED_FIELDS),
        "scalarFields": list(SCALAR_FIELDS),
        "listFields": list(LIST_FIELDS),
        "buckets": list(BUCKETS),
        "sourcesByBucket": {
            bucket: sorted(source for source, mapped in BUCKET_BY_SOURCE.items() if mapped == bucket)
            for bucket in BUCKETS
        },
        "sourceConfidence": dict(sorted(SOURCE_CONFIDENCE.items())),
        "overall": {
            "slots": slots,
            "filled": filled_total,
            "missing": max(0, slots - filled_total),
            "percent": round(filled_total * 100 / slots, 1) if slots else 0.0,
            "primary": {bucket: totals_by_bucket.get(bucket, 0) for bucket in BUCKETS},
        },
        "fields": fields,
    }


def snapshot(*, force: bool = False) -> dict[str, Any]:
    """Return the shared cached coverage snapshot, preferring stale to a rebuild.

    Same contract as the statistics snapshot: the refresh job pays for the
    whole-catalog pass, and a request serves what it last stored -- rebuilding
    only when nothing exists or the stored copy is old enough that a dead job
    would otherwise freeze the page indefinitely.
    """
    now = utcnow()
    with (
        db.advisory_lock("catalog-coverage-refresh", timeout_seconds=2) as acquired,
        db.session_scope() as session,
    ):
        cached = session.get(ApiCacheMeta, SNAPSHOT_KEY)
        cached_payload: dict[str, Any] | None = None
        if cached is not None:
            try:
                decoded = json.loads(cached.value)
            except json.JSONDecodeError:
                decoded = None
            cached_payload = decoded if isinstance(decoded, dict) else None
        # Serve the stored copy unless it is old enough that a dead refresh job
        # would freeze the page -- and even then, only rebuild if this request
        # holds the lock, so a crowd never stampedes the whole-catalog pass.
        if (
            cached_payload is not None
            and not force
            and (cached.updated_at >= now - SNAPSHOT_STALE_LIMIT or not acquired)
        ):
            return cached_payload
        payload = build_snapshot(session, now=now.replace(tzinfo=UTC))
        if acquired:
            _store(session, payload, now)
        return payload


def _store(session: Session, payload: dict[str, Any], now: datetime) -> None:
    """Write one rebuilt snapshot into the shared cache row."""
    cached = session.get(ApiCacheMeta, SNAPSHOT_KEY)
    if cached is None:
        cached = ApiCacheMeta(key=SNAPSHOT_KEY, value="")
        session.add(cached)
    cached.value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    cached.updated_at = now


def refresh() -> dict[str, Any]:
    """Rebuild and store the snapshot on behalf of the refresh job."""
    now = utcnow()
    with (
        db.advisory_lock("catalog-coverage-refresh", timeout_seconds=2) as acquired,
        db.session_scope() as session,
    ):
        if not acquired:
            return {"stored": False, "reason": "another refresh holds the lock"}
        payload = build_snapshot(session, now=now.replace(tzinfo=UTC))
        _store(session, payload, now)
        return {"stored": True, "generatedAt": payload["generatedAt"], "tools": payload["tools"]}
