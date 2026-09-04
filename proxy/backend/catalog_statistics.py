# SPDX-License-Identifier: GPL-3.0-or-later
"""Cached, local-only quality statistics for the canonical Toolhub catalog."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy import select

from backend import db, people_index, people_policy
from backend.models import (
    ApiCacheMeta,
    CanonicalToolCache,
    CatalogToolProjection,
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
# How long a stored snapshot is advertised as fresh. The statistics-refresh
# job has to run more often than this or the page reports an age it never
# reaches; tests/proxy/test_catalog_statistics.py pins the two together.
SNAPSHOT_MAX_AGE = timedelta(minutes=15)
# The point at which serving stale stops being better than making one
# visitor wait: past this, the refresh job is not running and somebody has
# to rebuild for the page to mean anything.
SNAPSHOT_STALE_LIMIT = timedelta(hours=6)
# Rows are consumed in batches so a 17,000-tool catalog never lands in
# memory at once; the size is a throughput/allocation trade-off, not a
# correctness one.
STREAM_BATCH_SIZE = 500
CORE_FIELDS = ("title", "description", "url", "tool_type", "repository", "user_docs_url")
#: What each measurement on the page means. Static text, identical under every
#: lens: narrowing the catalog changes the numbers, never what they are called.
DEFINITIONS = {
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
}
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


class _YearHistogram:
    """Count dates by year while the row that carried them is discarded.

    Written as an accumulator rather than a function over a list because the
    caller streams the catalog: holding the values long enough to pass them
    here is what used to make this module the largest allocation in the
    process.
    """

    def __init__(self) -> None:
        self._years: Counter[str] = Counter()
        self._unknown = 0

    def add(self, value: Any) -> None:  # noqa: ANN401 - canonical public JSON
        parsed = _parse_date(value)
        if parsed is None:
            self._unknown += 1
        else:
            self._years[str(parsed.year)] += 1

    def rows(self) -> list[dict[str, Any]]:
        rows = [{"key": year, "label": year, "count": count} for year, count in sorted(self._years.items())]
        if self._unknown:
            rows.append({"key": "unknown", "label": "Date unavailable", "count": self._unknown})
        return rows


#: The lanes this codebase catalogs itself, off the wikis, as opposed to
#: everything registered with Toolhub. The created-by-year chart can be read
#: either way and defaults to both, because the two answer different questions:
#: how old the registered catalog is, and how long the wikis have been
#: writing tools nobody registered.
WIKI_SOURCES = (SOURCE_WIKI_GADGET, SOURCE_WIKI_USERSCRIPT)


class _RecencyHistogram:
    """Bucket dates by age against one fixed instant, one value at a time."""

    def __init__(self, now: datetime) -> None:
        self._now = now
        self._counts: Counter[str] = Counter()

    def add(self, value: Any) -> None:  # noqa: ANN401 - canonical public JSON
        parsed = _parse_date(value)
        if parsed is None:
            self._counts["unknown"] += 1
            return
        age_days = max(0, (self._now - parsed).days)
        for key, _label, upper_bound in RECENCY_BUCKETS:
            if age_days <= upper_bound:
                self._counts[key] += 1
                return
        self._counts["olderThan3Years"] += 1

    def rows(self) -> list[dict[str, Any]]:
        rows = [{"key": key, "label": label, "count": self._counts[key]} for key, label, _bound in RECENCY_BUCKETS]
        rows.extend(
            (
                {"key": "older", "label": "More than 3 years", "count": self._counts["olderThan3Years"]},
                {"key": "unknown", "label": "Date unavailable", "count": self._counts["unknown"]},
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

    ``sourceBindings`` and ``sourceBindingMethods`` are the exception to the
    lens: a binding is scoped to a toolinfo feed record and carries no tool
    name, so it cannot be narrowed to a set of tools. They describe the
    ingest pipeline, and read the same under every lens.
    """
    account_counts: Counter[str] = Counter(
        _stream(session, select(ToolhubAccountProjection.normalized_username)).scalars()
    )
    handle_people: dict[str, set[int]] = {}
    for person_id, normalized in _stream(
        session,
        select(PersonIdentifier.person_id, PersonIdentifier.normalized_value).where(
            PersonIdentifier.is_current.is_(True),
            PersonIdentifier.namespace.in_((people_index.NS_WIKI_USERNAME, people_index.NS_TOOLFORGE_USERNAME)),
        ),
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
    binding_statuses: Counter[str] = Counter()
    binding_methods: Counter[str] = Counter()
    for status, method in _stream(
        session,
        select(ToolinfoAuthorBinding.status, ToolinfoAuthorBinding.method).where(
            ToolinfoAuthorBinding.withdrawn_at.is_(None)
        ),
    ):
        binding_statuses[status] += 1
        if method:
            binding_methods[method] += 1
    return {
        "distinctLabels": len(labels),
        "exactToolhubAccount": counts["exactToolhubAccount"],
        "ambiguousToolhubAccount": counts["ambiguousToolhubAccount"],
        "verifiedHandleOnly": counts["verifiedHandleOnly"],
        "noLocalMatch": counts["noLocalMatch"],
        "noLocalMatchHandleShaped": counts["noLocalMatchHandleShaped"],
        "noLocalMatchNameShaped": counts["noLocalMatchNameShaped"],
        "sourceBindings": dict(sorted(binding_statuses.items())),
        "sourceBindingMethods": dict(sorted(binding_methods.items())),
    }


def _coverage(count: int, total: int) -> dict[str, int]:
    return {
        "count": count,
        "missingCount": max(0, total - count),
        "percent": round((count / total) * 100) if total else 0,
    }


def _stream(session: Session, statement: Any) -> Any:  # noqa: ANN401 - SQLAlchemy select/result
    """Iterate a query in batches instead of buffering the whole result set.

    Every caller here reduces rows to counters and small name sets, so the
    rows themselves never need to exist all at once. Selecting columns rather
    than entities also keeps them out of the session identity map.
    """
    return session.execute(statement.execution_options(yield_per=STREAM_BATCH_SIZE))


def _evidence_freshness(
    session: Session,
    tool_names: set[str],
    naive_now: datetime,
    roles: tuple[str, ...],
) -> Counter[str]:
    """Count relationship evidence by freshness without collecting the rows.

    Restricting the query by `tool_name IN (...)` used to send one bind
    parameter per catalog tool -- roughly 17,000 of them. The catalog set is
    already in memory, so the same restriction costs nothing here, and only
    four counters survive the loop either way.
    """
    counts: Counter[str] = Counter()
    expiring_before = naive_now + timedelta(hours=72)
    for tool_name, withdrawn_at, expires_at in _stream(
        session,
        select(
            ToolRelationshipEvidence.tool_name,
            ToolRelationshipEvidence.withdrawn_at,
            ToolRelationshipEvidence.expires_at,
        ).where(ToolRelationshipEvidence.relationship_type.in_(roles)),
    ):
        if tool_name not in tool_names:
            continue
        if withdrawn_at is not None:
            counts["withdrawn"] += 1
        elif expires_at is not None and expires_at <= naive_now:
            counts["expired"] += 1
        else:
            counts["active"] += 1
            if expires_at is not None and expires_at <= expiring_before:
                counts["expiringWithin72Hours"] += 1
    return counts


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
    relationships = _stream(
        session,
        select(
            ToolPersonRelationship.tool_name,
            ToolPersonRelationship.person_id,
            ToolPersonRelationship.relationship_type,
            ToolPersonRelationship.verification_status,
            ToolPersonRelationship.verified_at,
            ToolPersonRelationship.expires_at,
        ).where(ToolPersonRelationship.relationship_type.in_(roles)),
    )
    verified_since_7d = naive_now - timedelta(days=7)
    verified_since_24h = naive_now - timedelta(hours=24)
    for tool_name, person_id, role, verification_status, verified_at, expires_at in relationships:
        if tool_name not in tool_names:
            continue
        status = verification_status or "unverified"
        is_current = expires_at is None or expires_at > naive_now
        if status == AUTHOR_CLAIM_VERIFIED and not is_current:
            status = "stale"
        status_counts[role][status] += 1
        if is_current:
            linked_people.add(person_id)
        if status != AUTHOR_CLAIM_VERIFIED:
            continue
        verified_by_role[role].add(tool_name)
        verified_people_by_role[role].add(person_id)
        if verified_at is not None and verified_at >= verified_since_7d:
            newly_verified["last7Days"][role].add(tool_name)
            if verified_at >= verified_since_24h:
                newly_verified["last24Hours"][role].add(tool_name)

    evidence_counts = _evidence_freshness(session, tool_names, naive_now, roles)

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
            "active": evidence_counts["active"],
            "expired": evidence_counts["expired"],
            "expiringWithin72Hours": evidence_counts["expiringWithin72Hours"],
            "withdrawn": evidence_counts["withdrawn"],
        },
    }
    return verified_by_role, status_counts, metrics


class _CatalogTotals(NamedTuple):
    """Everything one streamed pass over the canonical catalog can answer."""

    tool_names: set[str]
    listed_authors: int
    deprecated: int
    experimental: int
    core_complete: int
    metadata_counts: Counter[str]
    tool_types: Counter[str]
    created_by_year: _YearHistogram
    modified_by_year: _YearHistogram
    modified_recency: _RecencyHistogram


#: The lenses the page can be read under. ``all`` is every canonical record;
#: the other two are the halves ``WIKI_SOURCES`` splits the catalog into.
LENS_ALL = "all"
LENS_CATALOG = "catalog"
LENS_WIKI = "wiki"
LENSES = (LENS_ALL, LENS_CATALOG, LENS_WIKI)


class _LensAccumulator:
    """Counters for one lens, fed one record at a time.

    Every quantity the catalog pass produces is a count, a histogram bucket,
    or a tool name, so a lens costs its counters and its name set -- not a
    second copy of the records. That is what makes three lenses affordable:
    the expensive part is decoding each record, and this way it happens once.
    """

    def __init__(self, checked_at: datetime) -> None:
        self.tool_names: set[str] = set()
        self.listed_authors = 0
        self.deprecated = 0
        self.experimental = 0
        self.core_complete = 0
        self.metadata_counts: Counter[str] = Counter()
        self.tool_types: Counter[str] = Counter()
        self.created_by_year = _YearHistogram()
        self.modified_by_year = _YearHistogram()
        self.modified_recency = _RecencyHistogram(checked_at)

    def add(self, tool_name: str, record: dict[str, Any], *, has_author: bool) -> None:
        """Fold one already-decoded record into this lens."""
        self.tool_names.add(tool_name)
        self.listed_authors += has_author
        self.deprecated += record.get("deprecated") is True
        self.experimental += record.get("experimental") is True
        for field in CORE_FIELDS:
            if _has_value(record.get(field)):
                self.metadata_counts[field] += 1
        if has_author and all(_has_value(record.get(field)) for field in ("title", "description", "url")):
            self.core_complete += 1
        self.tool_types[str(record.get("tool_type") or "Unspecified").strip() or "Unspecified"] += 1
        created = record.get("created_date") or record.get("created")
        self.created_by_year.add(created)
        modified = record.get("modified_date") or record.get("modified")
        self.modified_by_year.add(modified)
        self.modified_recency.add(modified)

    def totals(self) -> _CatalogTotals:
        return _CatalogTotals(
            tool_names=self.tool_names,
            listed_authors=self.listed_authors,
            deprecated=self.deprecated,
            experimental=self.experimental,
            core_complete=self.core_complete,
            metadata_counts=self.metadata_counts,
            tool_types=self.tool_types,
            created_by_year=self.created_by_year,
            modified_by_year=self.modified_by_year,
            modified_recency=self.modified_recency,
        )


def _catalog_totals(session: Session, checked_at: datetime) -> dict[str, _CatalogTotals]:
    """Reduce every canonical record to counters, once per lens, in one pass.

    This used to build a dict of all ~17,000 decoded records first. Every
    quantity derived from it is a count, a histogram bucket, or a tool name,
    so the records themselves only had to exist one at a time -- and holding
    them all was the largest allocation in the web service, which is what got
    it OOM-killed while answering /statistics.

    A record belongs to ``all`` and to exactly one of ``catalog``/``wiki``,
    which is a column on the row rather than anything the record has to be
    re-read to decide. Accumulating the lenses together therefore costs one
    extra counter update per row, where filtering per lens would cost a
    second and third pass over the catalog.

    The record measured is the *effective* one, not the canonical one. The
    canonical row is what a source said; the projection is what the site
    shows, and the two differ by every locally added field -- a reviewed
    correction, a toolinfo record, an inferred description. Measuring the
    canonical layer reported `description` at exactly the number of tools that
    arrived from Toolhub with one, and no amount of local enrichment could ever
    move it: 2,583 descriptions written by the inference sweep were live on the
    site and absent from this number. The lens still comes from
    `CanonicalToolCache.source`, because which lane a tool arrived through is a
    fact about its origin and not about what has since been added to it, and
    the outer join is on the canonical side so a tool with no projection yet is
    still counted -- as its canonical record, which is all there is of it.

    The projection is layered *over* the canonical record rather than used in
    its place, because it is a partial record: it carries only the fields the
    projection lane computes. In production it held `title` for 54,937 tools
    and `description` for 9,554 -- and `modified_date`, `created_date` and
    `author` for exactly none of 57,290 rows. Substituting it therefore blanked
    every date and every author the catalog had: `modifiedByYear` reported
    53,189 of 53,190 tools as "Date unavailable" and `listedAuthors` counted 1,
    the single tool with no projection row to lose them to. Merging keeps the
    enrichment the substitution was introduced for and keeps the canonical
    fields the projection is simply silent about.
    """
    lenses = {name: _LensAccumulator(checked_at) for name in LENSES}
    for tool_name, canonical_record, effective_record, source in _stream(
        session,
        select(
            CanonicalToolCache.tool_name,
            CanonicalToolCache.record,
            CatalogToolProjection.effective_record,
            CanonicalToolCache.source,
        )
        .outerjoin(CatalogToolProjection, CatalogToolProjection.tool_name == CanonicalToolCache.tool_name)
        .order_by(CanonicalToolCache.tool_name),
    ):
        canonical = canonical_record if isinstance(canonical_record, dict) else {}
        overlay = effective_record if isinstance(effective_record, dict) else {}
        record = {**canonical, **overlay} if overlay else canonical
        has_author = bool(author_assertions(record))
        lane = LENS_WIKI if source in WIKI_SOURCES else LENS_CATALOG
        lenses[LENS_ALL].add(tool_name, record, has_author=has_author)
        lenses[lane].add(tool_name, record, has_author=has_author)
    return {name: accumulator.totals() for name, accumulator in lenses.items()}


class _UnresolvedAttribution(NamedTuple):
    """Catalog tools and labels that attribution has not resolved yet."""

    author_tools: set[str]
    labels: set[str]
    tools: set[str]


def _unresolved_attribution(session: Session, tool_names: set[str], naive_now: datetime) -> _UnresolvedAttribution:
    """Collect the three unresolved-attribution sets in one streamed pass.

    All three narrow to ``tool_names``, labels included: an author token that
    only ever appeared on a registered tool is not part of the wiki lane's
    unresolved vocabulary, and counting it there would make the funnel read
    the same under every lens.
    """
    author_tools: set[str] = set()
    labels: set[str] = set()
    tools: set[str] = set()
    for tool_name, normalized_label, relationship_type, expires_at in _stream(
        session,
        select(
            UnresolvedAttributionEvidence.tool_name,
            UnresolvedAttributionEvidence.normalized_label,
            UnresolvedAttributionEvidence.relationship_type,
            UnresolvedAttributionEvidence.expires_at,
        ).where(
            UnresolvedAttributionEvidence.withdrawn_at.is_(None),
            UnresolvedAttributionEvidence.relationship_type.in_((PERSON_REL_AUTHOR, PERSON_REL_MAINTAINER)),
        ),
    ):
        if tool_name not in tool_names:
            continue
        tools.add(tool_name)
        unexpired = expires_at is None or expires_at > naive_now
        if not unexpired:
            continue
        if relationship_type == PERSON_REL_AUTHOR:
            author_tools.add(tool_name)
        if normalized_label:
            labels.add(normalized_label)
    return _UnresolvedAttribution(author_tools=author_tools, labels=labels, tools=tools)


def _source_statistics(session: Session) -> dict[str, Any]:
    """Summarize toolinfo feeds and whatever attestation each one carries."""
    attestations = {
        source_id: (status, classification)
        for source_id, status, classification in _stream(
            session,
            select(
                ToolinfoSourceAttestation.source_id,
                ToolinfoSourceAttestation.status,
                ToolinfoSourceAttestation.classification,
            ),
        )
    }
    total = 0
    valid_feeds = 0
    items = 0
    statuses: Counter[str] = Counter()
    classifications: Counter[str] = Counter()
    for source_id, valid, item_count in _stream(
        session, select(ToolinfoSource.id, ToolinfoSource.valid, ToolinfoSource.item_count)
    ):
        total += 1
        valid_feeds += bool(valid)
        items += item_count
        status, classification = attestations.get(source_id, ("notChecked", "notChecked"))
        statuses[status] += 1
        classifications[classification] += 1
    return {
        "total": total,
        "validFeeds": valid_feeds,
        "items": items,
        "statuses": dict(sorted(statuses.items())),
        "classifications": dict(sorted(classifications.items())),
    }


class _Shared(NamedTuple):
    """The parts of the page that do not narrow with the lens.

    Feeds, people, and vocabulary are not tools, so restricting the catalog
    does not restrict them. Computing them once also keeps the three lenses
    from disagreeing about how many publishable people exist.
    """

    publishable_person_ids: set[int]
    quality_counts: Counter[str]
    sources: dict[str, Any]


def _lens_document(
    session: Session,
    catalog: _CatalogTotals,
    checked_at: datetime,
    shared: _Shared,
) -> dict[str, Any]:
    """Assemble every block of the page for one lens's set of tools.

    Each helper here already narrows on ``tool_names``, so a lens is not a
    filter applied to a finished document -- it is the same document computed
    against a smaller catalog. ``sources``, the person quality counts, and the
    definitions are the exceptions: they describe feeds, people, and
    vocabulary rather than tools, so they are computed once and shared.
    """
    tool_names = catalog.tool_names
    total = len(tool_names)
    verified_by_role, status_counts, relationship_metrics = _relationship_statistics(
        session, tool_names, checked_at, shared.publishable_person_ids
    )
    unresolved = _unresolved_attribution(session, tool_names, checked_at.replace(tzinfo=None))
    type_rows = [
        {"key": label.casefold().replace(" ", "-"), "label": label, "count": count}
        for label, count in sorted(catalog.tool_types.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]
    verified_authors = len(verified_by_role[PERSON_REL_AUTHOR])
    verified_maintainers = len(verified_by_role[PERSON_REL_MAINTAINER])
    return {
        "catalog": {
            "totalTools": total,
            "activeTools": total - catalog.deprecated,
            "deprecatedTools": catalog.deprecated,
            "experimentalTools": catalog.experimental,
            "listedAuthors": _coverage(catalog.listed_authors, total),
            "verifiedAuthors": _coverage(verified_authors, total),
            "verifiedMaintainers": _coverage(verified_maintainers, total),
            "unresolvedAuthorTools": len(unresolved.author_tools),
            "coreMetadataComplete": _coverage(catalog.core_complete, total),
        },
        "metadata": [
            {"key": field, "label": field.replace("_", " ").title(), **_coverage(catalog.metadata_counts[field], total)}
            for field in CORE_FIELDS
        ],
        "relationships": {
            "authors": dict(sorted(status_counts[PERSON_REL_AUTHOR].items())),
            "maintainers": dict(sorted(status_counts[PERSON_REL_MAINTAINER].items())),
        },
        "relationshipMetrics": relationship_metrics,
        "identities": {
            "publishablePeople": len(shared.publishable_person_ids),
            "stablePeople": shared.quality_counts["stable"],
            "handlePeople": shared.quality_counts["handle"],
            "unresolvedLabels": len(unresolved.labels),
            "unresolvedTools": len(unresolved.tools),
        },
        "attribution": _attribution_funnel(session, unresolved.labels, shared.publishable_person_ids),
        "sources": shared.sources,
        "distributions": {
            "createdByYear": catalog.created_by_year.rows(),
            "modifiedByYear": catalog.modified_by_year.rows(),
            "modifiedRecency": catalog.modified_recency.rows(),
            "toolTypes": type_rows,
        },
        "definitions": DEFINITIONS,
    }


def build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Build one deterministic statistics document from local projections.

    The document is the ``all`` lens, with the other two beside it under
    ``lenses``. Three whole documents rather than one filtered client-side
    because most blocks here are not sums the page could re-add: a coverage
    percentage, a verified-relationship count, and an unresolved-label funnel
    all have to be recomputed against the narrower set of tools to mean
    anything. The payload is a few kilobytes, so carrying all three costs far
    less than a request per switch would.
    """
    checked_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    totals = _catalog_totals(session, checked_at)

    # Computed once and shared: these describe feeds and people rather than
    # tools, so they do not narrow with the lens.
    publishable_person_ids = people_index.public_identity_ids(session)
    # Filtering in Python rather than `Person.id IN (...)`: the publishable set
    # is already in memory, and the IN form sent one bind parameter per person.
    quality_counts: Counter[str] = Counter()
    for person_id, quality in _stream(session, select(Person.id, Person.identity_quality)):
        if person_id in publishable_person_ids:
            quality_counts[quality] += 1
    shared = _Shared(
        publishable_person_ids=publishable_person_ids,
        quality_counts=quality_counts,
        sources=_source_statistics(session),
    )

    documents = {name: _lens_document(session, totals[name], checked_at, shared) for name in LENSES}
    return {
        "generatedAt": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": SOURCE_OFFICIAL,
        "syncStatus": SYNC_OFFICIAL,
        **documents[LENS_ALL],
        # The narrower readings sit beside the full one rather than replacing
        # it, so a client that knows nothing about lenses still reads the
        # document it always did.
        "lenses": {LENS_CATALOG: documents[LENS_CATALOG], LENS_WIKI: documents[LENS_WIKI]},
    }


def _stored_snapshot(session: Session) -> tuple[Any, dict[str, Any] | None]:
    """Return the cache row and its decoded payload, or None when unusable."""
    cached = session.get(ApiCacheMeta, SNAPSHOT_KEY)
    if cached is None:
        return None, None
    try:
        decoded = json.loads(cached.value)
    except json.JSONDecodeError:
        return cached, None
    return cached, decoded if isinstance(decoded, dict) else None


def snapshot(*, force: bool = False) -> dict[str, Any]:
    """Return the shared cached snapshot, preferring a stale one to a rebuild.

    The rebuild reads the whole catalog, so whoever pays for it waits seconds
    on a pod capped at half a CPU. That used to be whichever visitor arrived
    first after the 15-minute window closed, which -- with the precompute job
    running every six hours -- was almost every visitor. The refresh is now
    the statistics-refresh job's work (see `proxy/statistics_refresh.py`), and
    a request serves what that job last stored even when it is past
    SNAPSHOT_MAX_AGE. The payload carries `generatedAt`, and /statistics shows
    it, so serving stale is visible rather than silent.

    A request still rebuilds in two cases: nothing has ever been stored, and
    the stored copy is older than SNAPSHOT_STALE_LIMIT, which bounds how long
    a dead refresh job can freeze the page. The shared lock keeps that to one
    worker at a time; the others go on serving the stale payload rather than
    turning cache contention into a 500.
    """
    now = utcnow()
    # One connection on the path almost every request takes. Holding the
    # rebuild lock here too cost two, which is a webservice worker's whole pool,
    # so a single request starved its own worker and the next one waited out
    # pool_timeout. The lock decides who may rebuild; reading the stored copy
    # is not rebuilding.
    with db.session_scope() as session:
        cached, cached_payload = _stored_snapshot(session)
        if cached_payload is not None and not force and cached.updated_at >= now - SNAPSHOT_STALE_LIMIT:
            return cached_payload

    # Missing, or stale past the bound on how long a dead refresh job may
    # freeze the page. Only here is the lock worth its connection.
    with (
        db.advisory_lock("catalog-statistics-refresh", timeout_seconds=2) as acquired,
        db.session_scope() as session,
    ):
        # Re-read first: whoever held the lock while this request queued for it
        # has probably just stored a fresh copy.
        cached, cached_payload = _stored_snapshot(session)
        if cached_payload is not None and not force:
            serve_stale = cached.updated_at >= now - SNAPSHOT_STALE_LIMIT or not acquired
            if serve_stale:
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
    """Rebuild and store the snapshot on behalf of the statistics-refresh job.

    Separate from ``snapshot(force=True)`` because a job that loses the lock
    should stop rather than spend the whole rebuild on a payload it is not
    allowed to store, and because the caller needs to report whether the
    stored copy actually moved.
    """
    now = utcnow()
    with (
        db.advisory_lock("catalog-statistics-refresh", timeout_seconds=2) as acquired,
        db.session_scope() as session,
    ):
        if not acquired:
            return {"stored": False, "reason": "another refresh holds the lock"}
        payload = build_snapshot(session, now=now.replace(tzinfo=UTC))
        _store(session, payload, now)
        return {
            "stored": True,
            "generatedAt": payload["generatedAt"],
            "totalTools": payload["catalog"]["totalTools"],
        }
