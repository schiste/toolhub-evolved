# SPDX-License-Identifier: GPL-3.0-or-later
"""Cached, local-only quality statistics for the canonical Toolhub catalog."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import db, people_index
from backend.models import (
    ApiCacheMeta,
    CanonicalToolCache,
    Person,
    ToolinfoSource,
    ToolinfoSourceAttestation,
    ToolPersonRelationship,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    SOURCE_OFFICIAL,
    SYNC_OFFICIAL,
)
from backend.toolinfo_authors import author_assertions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SNAPSHOT_KEY = "catalog_statistics_v1"
SNAPSHOT_MAX_AGE = timedelta(minutes=15)
CORE_FIELDS = ("title", "description", "url", "tool_type", "repository", "user_docs_url")
RECENCY_BUCKETS = (
    ("last30Days", "Last 30 days", 30),
    ("days31To90", "31-90 days", 90),
    ("days91To365", "91 days-1 year", 365),
    ("years1To3", "1-3 years", 1095),
)


def _has_value(value: Any) -> bool:  # noqa: ANN401 - canonical public JSON
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, [], {})


def _parse_date(value: Any) -> datetime | None:  # noqa: ANN401 - canonical public JSON
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _year_histogram(values: list[Any]) -> list[dict[str, Any]]:
    years: Counter[str] = Counter()
    unknown = 0
    for value in values:
        parsed = _parse_date(value)
        if parsed is None:
            unknown += 1
        else:
            years[str(parsed.year)] += 1
    rows = [{"key": year, "label": year, "count": count} for year, count in sorted(years.items())]
    if unknown:
        rows.append({"key": "unknown", "label": "Date unavailable", "count": unknown})
    return rows


def _recency_histogram(values: list[Any], now: datetime) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for value in values:
        parsed = _parse_date(value)
        if parsed is None:
            counts["unknown"] += 1
            continue
        age_days = max(0, (now - parsed).days)
        for key, _label, upper_bound in RECENCY_BUCKETS:
            if age_days <= upper_bound:
                counts[key] += 1
                break
        else:
            counts["olderThan3Years"] += 1
    rows = [{"key": key, "label": label, "count": counts[key]} for key, label, _upper_bound in RECENCY_BUCKETS]
    rows.extend(
        (
            {"key": "older", "label": "More than 3 years", "count": counts["olderThan3Years"]},
            {"key": "unknown", "label": "Date unavailable", "count": counts["unknown"]},
        )
    )
    return rows


def _coverage(count: int, total: int) -> dict[str, int]:
    return {
        "count": count,
        "missingCount": max(0, total - count),
        "percent": round((count / total) * 100) if total else 0,
    }


def _current_relationship(row: ToolPersonRelationship, now: datetime) -> bool:
    return row.expires_at is None or row.expires_at > now.replace(tzinfo=None)


def build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Build one deterministic statistics document from local projections."""
    checked_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    tool_rows = list(
        session.execute(
            select(CanonicalToolCache.tool_name, CanonicalToolCache.record).order_by(CanonicalToolCache.tool_name)
        )
    )
    records = {name: record if isinstance(record, dict) else {} for name, record in tool_rows}
    tool_names = set(records)
    total = len(tool_names)

    listed_author_tools = {name for name, record in records.items() if author_assertions(record)}
    deprecated_tools = {name for name, record in records.items() if record.get("deprecated") is True}
    experimental_tools = {name for name, record in records.items() if record.get("experimental") is True}
    metadata_counts = {
        field: sum(_has_value(record.get(field)) for record in records.values()) for field in CORE_FIELDS
    }
    core_complete = sum(
        all(_has_value(record.get(field)) for field in ("title", "description", "url"))
        and bool(author_assertions(record))
        for record in records.values()
    )

    verified_by_role = {PERSON_REL_AUTHOR: set(), PERSON_REL_MAINTAINER: set()}
    status_counts: dict[str, Counter[str]] = {
        PERSON_REL_AUTHOR: Counter(),
        PERSON_REL_MAINTAINER: Counter(),
    }
    relationships = session.execute(
        select(ToolPersonRelationship).where(
            ToolPersonRelationship.relationship_type.in_((PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER))
        )
    ).scalars()
    for relationship in relationships:
        if relationship.tool_name not in tool_names:
            continue
        status = relationship.verification_status or "unverified"
        if status == AUTHOR_CLAIM_VERIFIED and not _current_relationship(relationship, checked_at):
            status = "stale"
        status_counts[relationship.relationship_type][status] += 1
        if status == AUTHOR_CLAIM_VERIFIED:
            verified_by_role[relationship.relationship_type].add(relationship.tool_name)

    unresolved_rows = list(
        session.execute(
            select(UnresolvedAttributionEvidence).where(
                UnresolvedAttributionEvidence.withdrawn_at.is_(None),
                UnresolvedAttributionEvidence.relationship_type.in_((PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER)),
            )
        ).scalars()
    )
    unresolved_author_tools = {
        row.tool_name
        for row in unresolved_rows
        if row.tool_name in tool_names
        and row.relationship_type == PERSON_REL_AUTHOR
        and (row.expires_at is None or row.expires_at > checked_at.replace(tzinfo=None))
    }
    unresolved_labels = {
        row.normalized_label
        for row in unresolved_rows
        if row.normalized_label and (row.expires_at is None or row.expires_at > checked_at.replace(tzinfo=None))
    }

    publishable_person_ids = people_index.public_identity_ids(session)
    quality_counts = Counter(
        quality
        for _person_id, quality in session.execute(
            select(Person.id, Person.identity_quality).where(Person.id.in_(publishable_person_ids or {-1}))
        )
    )

    sources = list(session.execute(select(ToolinfoSource)).scalars())
    attestations = {row.source_id: row for row in session.execute(select(ToolinfoSourceAttestation)).scalars()}
    source_statuses = Counter(
        (attestations.get(source.id).status if attestations.get(source.id) else "notChecked") for source in sources
    )
    source_classifications = Counter(
        (attestations.get(source.id).classification if attestations.get(source.id) else "notChecked")
        for source in sources
    )

    tool_types = Counter(
        str(record.get("tool_type") or "Unspecified").strip() or "Unspecified" for record in records.values()
    )
    type_rows = [
        {"key": label.casefold().replace(" ", "-"), "label": label, "count": count}
        for label, count in sorted(tool_types.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]

    verified_authors = len(verified_by_role[PERSON_REL_AUTHOR])
    verified_maintainers = len(verified_by_role[PERSON_REL_MAINTAINER])
    return {
        "generatedAt": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": SOURCE_OFFICIAL,
        "syncStatus": SYNC_OFFICIAL,
        "catalog": {
            "totalTools": total,
            "activeTools": total - len(deprecated_tools),
            "deprecatedTools": len(deprecated_tools),
            "experimentalTools": len(experimental_tools),
            "listedAuthors": _coverage(len(listed_author_tools), total),
            "verifiedAuthors": _coverage(verified_authors, total),
            "verifiedMaintainers": _coverage(verified_maintainers, total),
            "unresolvedAuthorTools": len(unresolved_author_tools),
            "coreMetadataComplete": _coverage(core_complete, total),
        },
        "metadata": [
            {"key": field, "label": field.replace("_", " ").title(), **_coverage(count, total)}
            for field, count in metadata_counts.items()
        ],
        "relationships": {
            "authors": dict(sorted(status_counts[PERSON_REL_AUTHOR].items())),
            "maintainers": dict(sorted(status_counts[PERSON_REL_MAINTAINER].items())),
        },
        "identities": {
            "publishablePeople": len(publishable_person_ids),
            "stablePeople": quality_counts["stable"],
            "handlePeople": quality_counts["handle"],
            "unresolvedLabels": len(unresolved_labels),
            "unresolvedTools": len({row.tool_name for row in unresolved_rows if row.tool_name in tool_names}),
        },
        "sources": {
            "total": len(sources),
            "validFeeds": sum(source.valid for source in sources),
            "items": sum(source.item_count for source in sources),
            "statuses": dict(sorted(source_statuses.items())),
            "classifications": dict(sorted(source_classifications.items())),
        },
        "distributions": {
            "createdByYear": _year_histogram(
                [record.get("created_date") or record.get("created") for record in records.values()]
            ),
            "modifiedByYear": _year_histogram(
                [record.get("modified_date") or record.get("modified") for record in records.values()]
            ),
            "modifiedRecency": _recency_histogram(
                [record.get("modified_date") or record.get("modified") for record in records.values()], checked_at
            ),
            "toolTypes": type_rows,
        },
        "definitions": {
            "verifiedAuthor": "A current author relationship backed by stable identity evidence.",
            "listedAuthor": "The canonical Toolhub record contains at least one author attribution.",
            "verifiedMaintainer": "A current maintainer relationship backed by confirmed access evidence.",
            "coreMetadata": "Title, description, tool URL, and at least one listed author are present.",
            "dateBasis": "Dates are canonical Toolhub catalog record dates; unavailable values remain visible.",
        },
    }


def snapshot(*, force: bool = False) -> dict[str, Any]:
    """Return a shared cached snapshot, rebuilding it at most every 15 minutes."""
    now = utcnow()
    # The shared lock prevents two freshly restarted web workers from inserting
    # the same cache key simultaneously. A worker that cannot acquire it may
    # still serve the last snapshot, keeping this diagnostic endpoint read-only
    # under load rather than turning cache contention into a 500.
    with (
        db.advisory_lock("catalog-statistics-refresh", timeout_seconds=2) as acquired,
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
        if cached_payload is not None and (not force and (cached.updated_at >= now - SNAPSHOT_MAX_AGE or not acquired)):
            return cached_payload
        payload = build_snapshot(session, now=now.replace(tzinfo=UTC))
        if not acquired:
            return payload
        if cached is None:
            cached = ApiCacheMeta(key=SNAPSHOT_KEY, value="")
            session.add(cached)
        cached.value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        cached.updated_at = now
        return payload
