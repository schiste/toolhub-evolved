# SPDX-License-Identifier: GPL-3.0-or-later
"""Cached, local-only quality statistics for the canonical Toolhub catalog."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend import db, people_index, people_policy
from backend.models import (
    ApiCacheMeta,
    CanonicalToolCache,
    Person,
    PersonIdentifier,
    ToolhubAccountProjection,
    ToolinfoAuthorBinding,
    ToolinfoSource,
    ToolinfoSourceAttestation,
    ToolPersonRelationship,
    ToolRelationshipEvidence,
    UnresolvedAttributionEvidence,
    utcnow,
)
from backend.sync import (
    AUTHOR_CLAIM_VERIFIED,
    PERSON_REL_AUTHOR,
    PERSON_REL_MAINTAINER,
    SOURCE_OFFICIAL,
    SOURCE_WIKI_GADGET,
    SOURCE_WIKI_USERSCRIPT,
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


#: The lanes this codebase catalogues itself, off the wikis, as opposed to
#: everything registered with Toolhub. The created-by-year chart can be read
#: either way and defaults to both, because the two answer different questions:
#: how old the registered catalogue is, and how long the wikis have been
#: writing tools nobody registered.
WIKI_SOURCES = (SOURCE_WIKI_GADGET, SOURCE_WIKI_USERSCRIPT)


def _created_values(records: dict[str, dict[str, Any]], names: set[str] | None = None) -> list[Any]:
    """Every creation date the given records carry, in whatever field holds it."""
    return [
        record.get("created_date") or record.get("created")
        for name, record in records.items()
        if names is None or name in names
    ]


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


def _attribution_funnel(
    session: Session,
    labels: set[str],
    publishable_person_ids: set[int],
) -> dict[str, Any]:
    """Classify unresolved labels by the rule that could still resolve them.

    Outcome counts say how many labels are unresolved. They cannot say
    whether the reconciler is merely behind or has reached the limit of its
    rules, which are different problems with different fixes. This partitions
    every label by the strongest local match available, so a large
    ``noLocalMatch`` reads as a rule ceiling rather than a backlog.

    Matching mirrors the reconciler's own precedence and normalization: an
    exact Toolhub username is what ``discover_identity_candidates`` tries
    first, and a current handle on a publishable person is what source
    attestation binds through. No external lookups happen here.
    """
    account_counts: Counter[str] = Counter(
        session.execute(select(ToolhubAccountProjection.normalized_username)).scalars()
    )
    handle_people: dict[str, set[int]] = {}
    for person_id, normalized in session.execute(
        select(PersonIdentifier.person_id, PersonIdentifier.normalized_value).where(
            PersonIdentifier.is_current.is_(True),
            PersonIdentifier.namespace.in_((people_index.NS_WIKI_USERNAME, people_index.NS_TOOLFORGE_USERNAME)),
        )
    ):
        if person_id in publishable_person_ids and normalized:
            handle_people.setdefault(normalized, set()).add(person_id)
    counts = Counter()
    for label in labels:
        accounts = account_counts.get(label, 0)
        if accounts == 1:
            counts["exactToolhubAccount"] += 1
        elif accounts > 1:
            counts["ambiguousToolhubAccount"] += 1
        elif len(handle_people.get(label, ())) == 1:
            counts["verifiedHandleOnly"] += 1
        else:
            counts["noLocalMatch"] += 1
            # Split the ceiling by whether a label could ever be resolved
            # against a public registry, so the size of that option is a
            # measured number rather than an estimate.
            if people_policy.is_handle_shaped(label):
                counts["noLocalMatchHandleShaped"] += 1
            else:
                counts["noLocalMatchNameShaped"] += 1
    bindings = list(
        session.execute(select(ToolinfoAuthorBinding).where(ToolinfoAuthorBinding.withdrawn_at.is_(None))).scalars()
    )
    return {
        "distinctLabels": len(labels),
        "exactToolhubAccount": counts["exactToolhubAccount"],
        "ambiguousToolhubAccount": counts["ambiguousToolhubAccount"],
        "verifiedHandleOnly": counts["verifiedHandleOnly"],
        "noLocalMatch": counts["noLocalMatch"],
        "noLocalMatchHandleShaped": counts["noLocalMatchHandleShaped"],
        "noLocalMatchNameShaped": counts["noLocalMatchNameShaped"],
        "sourceBindings": dict(sorted(Counter(row.status for row in bindings).items())),
        "sourceBindingMethods": dict(sorted(Counter(row.method for row in bindings if row.method).items())),
    }


def _coverage(count: int, total: int) -> dict[str, int]:
    return {
        "count": count,
        "missingCount": max(0, total - count),
        "percent": round((count / total) * 100) if total else 0,
    }


def _current_relationship(row: ToolPersonRelationship, now: datetime) -> bool:
    return row.expires_at is None or row.expires_at > now.replace(tzinfo=None)


def _relationship_statistics(
    session: Session,
    tool_names: set[str],
    checked_at: datetime,
    publishable_person_ids: set[int],
) -> tuple[dict[str, set[str]], dict[str, Counter[str]], dict[str, Any]]:
    """Count tool, person, row, transition, and freshness units separately."""
    roles = (PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER)
    verified_by_role: dict[str, set[str]] = {role: set() for role in roles}
    verified_people_by_role: dict[str, set[int]] = {role: set() for role in roles}
    status_counts: dict[str, Counter[str]] = {role: Counter() for role in roles}
    linked_people: set[int] = set()
    newly_verified = {
        "last24Hours": {role: set() for role in roles},
        "last7Days": {role: set() for role in roles},
    }
    naive_now = checked_at.replace(tzinfo=None)
    relationships = session.execute(
        select(ToolPersonRelationship).where(ToolPersonRelationship.relationship_type.in_(roles))
    ).scalars()
    for relationship in relationships:
        if relationship.tool_name not in tool_names:
            continue
        status = relationship.verification_status or "unverified"
        is_current = _current_relationship(relationship, checked_at)
        if status == AUTHOR_CLAIM_VERIFIED and not is_current:
            status = "stale"
        status_counts[relationship.relationship_type][status] += 1
        if is_current:
            linked_people.add(relationship.person_id)
        if status != AUTHOR_CLAIM_VERIFIED:
            continue
        verified_by_role[relationship.relationship_type].add(relationship.tool_name)
        verified_people_by_role[relationship.relationship_type].add(relationship.person_id)
        if relationship.verified_at is not None and relationship.verified_at >= naive_now - timedelta(days=7):
            newly_verified["last7Days"][relationship.relationship_type].add(relationship.tool_name)
            if relationship.verified_at >= naive_now - timedelta(hours=24):
                newly_verified["last24Hours"][relationship.relationship_type].add(relationship.tool_name)

    evidence_rows = list(
        session.execute(
            select(ToolRelationshipEvidence).where(
                ToolRelationshipEvidence.tool_name.in_(tool_names or {"<none>"}),
                ToolRelationshipEvidence.relationship_type.in_(roles),
            )
        ).scalars()
    )
    active_evidence = [row for row in evidence_rows if row.withdrawn_at is None]
    expired_evidence = [row for row in active_evidence if row.expires_at is not None and row.expires_at <= naive_now]
    expiring_evidence = [
        row
        for row in active_evidence
        if row.expires_at is not None and naive_now < row.expires_at <= naive_now + timedelta(hours=72)
    ]

    def window_metrics(window: str) -> dict[str, int]:
        authors = newly_verified[window][PERSON_REL_AUTHOR]
        maintainers = newly_verified[window][PERSON_REL_MAINTAINER]
        return {"all": len(authors | maintainers), "authors": len(authors), "maintainers": len(maintainers)}

    verified_people = verified_people_by_role[PERSON_REL_AUTHOR] | verified_people_by_role[PERSON_REL_MAINTAINER]
    metrics = {
        "tools": {
            "verifiedAuthors": len(verified_by_role[PERSON_REL_AUTHOR]),
            "verifiedMaintainers": len(verified_by_role[PERSON_REL_MAINTAINER]),
        },
        "people": {
            "withAnyCurrentRelationship": len(publishable_person_ids & linked_people),
            "withAnyVerifiedRelationship": len(publishable_person_ids & verified_people),
            "verifiedAuthors": len(publishable_person_ids & verified_people_by_role[PERSON_REL_AUTHOR]),
            "verifiedMaintainers": len(publishable_person_ids & verified_people_by_role[PERSON_REL_MAINTAINER]),
            "identityOnly": len(publishable_person_ids - linked_people),
        },
        "rows": {
            "total": sum(sum(counts.values()) for counts in status_counts.values()),
            "verified": sum(counts[AUTHOR_CLAIM_VERIFIED] for counts in status_counts.values()),
            "stale": sum(counts["stale"] for counts in status_counts.values()),
        },
        "newlyVerifiedTools": {
            "last24Hours": window_metrics("last24Hours"),
            "last7Days": window_metrics("last7Days"),
        },
        "evidenceFreshness": {
            "active": len(active_evidence) - len(expired_evidence),
            "expired": len(expired_evidence),
            "expiringWithin72Hours": len(expiring_evidence),
            "withdrawn": len(evidence_rows) - len(active_evidence),
        },
    }
    return verified_by_role, status_counts, metrics


def build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Build one deterministic statistics document from local projections."""
    checked_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    tool_rows = list(
        session.execute(
            select(
                CanonicalToolCache.tool_name,
                CanonicalToolCache.record,
                CanonicalToolCache.source,
            ).order_by(CanonicalToolCache.tool_name)
        )
    )
    records = {name: record if isinstance(record, dict) else {} for name, record, _ in tool_rows}
    wiki_tools = {name for name, _, source in tool_rows if source in WIKI_SOURCES}
    catalog_tools = set(records) - wiki_tools
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

    publishable_person_ids = people_index.public_identity_ids(session)
    verified_by_role, status_counts, relationship_metrics = _relationship_statistics(
        session, tool_names, checked_at, publishable_person_ids
    )

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
        "relationshipMetrics": relationship_metrics,
        "identities": {
            "publishablePeople": len(publishable_person_ids),
            "stablePeople": quality_counts["stable"],
            "handlePeople": quality_counts["handle"],
            "unresolvedLabels": len(unresolved_labels),
            "unresolvedTools": len({row.tool_name for row in unresolved_rows if row.tool_name in tool_names}),
        },
        "attribution": _attribution_funnel(session, unresolved_labels, publishable_person_ids),
        "sources": {
            "total": len(sources),
            "validFeeds": sum(source.valid for source in sources),
            "items": sum(source.item_count for source in sources),
            "statuses": dict(sorted(source_statuses.items())),
            "classifications": dict(sorted(source_classifications.items())),
        },
        "distributions": {
            "createdByYear": _year_histogram(_created_values(records)),
            # The same chart split by where the record came from, so a reader
            # can ask about the registered catalogue and the wiki lanes
            # separately. Both series are always emitted; which is shown is the
            # page's business, and showing both is the default because the
            # combined shape is the honest one.
            "createdByYearBySource": {
                "catalog": _year_histogram(_created_values(records, catalog_tools)),
                "wiki": _year_histogram(_created_values(records, wiki_tools)),
            },
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
            "identityOnly": "A publishable person identity with no current author or maintainer relationship.",
            "newlyVerifiedTool": "A canonical tool whose current relationship first became verified in the window.",
            "coreMetadata": "Title, description, tool URL, and at least one listed author are present.",
            "dateBasis": "Dates are canonical Toolhub catalog record dates; unavailable values remain visible.",
            "noLocalMatch": "Unresolved labels no current rule can reach, so the remaining limit is the rules.",
            "exactToolhubAccount": "Unresolved labels matching exactly one official Toolhub username.",
            "handleShaped": "Unreachable labels shaped like a chosen handle, which a public registry could resolve.",
            "nameShaped": "Unreachable labels indistinguishable from a person name, never resolved from text alone.",
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
