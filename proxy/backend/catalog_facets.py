# SPDX-License-Identifier: GPL-3.0-or-later
"""Generation-safe facet projections for fast local catalog reads.

The raw inverted index remains authoritative for filtered searches.  The
unfiltered catalog sidebar is read far more often, so its bounded aggregate is
materialized once by background jobs and published atomically through one
ApiCacheMeta row.  Public requests never rebuild it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, distinct, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from backend import db, facet_names
from backend.models import ApiCacheMeta, CanonicalToolCache, CatalogFacetValue, ToolCatalogSyncState, utcnow
from backend.sync import LIFECYCLE_ARCHIVED

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session
    from sqlalchemy.sql import Select

STATE_KEY = "official_catalog"
CACHE_KEY = "catalog:facets:v2"
DIRTY_KEY = "catalog:facets:dirty:v2"
CACHE_VERSION = 2
FACET_BUCKET_LIMIT = 50
FACET_FIELDS = facet_names.CATALOG_PUBLIC_TO_STORAGE

STATUS_DEPRECATED = "deprecated"
STATUS_EXPERIMENTAL = "experimental"
STATUS_ACTIVE = "active"
# `archived` is deliberately not here. It is carried by `include_archived`,
# which predates this parameter and is also read by the offline fallback in
# `canonical_tools.search`; accepting it in both places would be two answers to
# one question, and they would eventually disagree.
STATUS_VALUES = frozenset({STATUS_DEPRECATED, STATUS_EXPERIMENTAL, STATUS_ACTIVE})


def default_population() -> Select:
    """Rows the catalog shows to a reader who has not asked for more.

    Archived tools are catalogued but not offered: the user-script census files
    a script nobody but its author loads as `archived` rather than dropping it,
    so the row exists precisely so that it can be found on purpose. Excluding it
    here rather than at each call site keeps one definition of "the default
    view", which is what makes the cached global aggregate below comparable with
    the result page it labels.

    `lifecycle` is `NOT NULL DEFAULT ''` (`backend.db._schema_additions`), so
    rows predating the column read as unknown and stay visible; only an explicit
    `archived` is withheld. A tool the census has never judged is not a tool it
    has judged badly.
    """
    return select(CanonicalToolCache).where(CanonicalToolCache.lifecycle != LIFECYCLE_ARCHIVED)


def selected_statuses(params: Any) -> frozenset[str]:  # noqa: ANN401 - Flask MultiDict or mapping
    """Return the status kinds this request accepts, as a set of ticked boxes.

    An absent parameter is every kind, not none: a caller that has never heard
    of this filter must keep seeing the whole population, and the search page
    only puts `status` in the URL once the reader has changed something. An
    empty string is a real answer -- every box cleared -- and stays distinct
    from absent, which is why this tests for None rather than for a falsy value.
    Unknown words are dropped rather than rejected, so a stale bookmark
    degrades to a wider result set instead of an error page.
    """
    raw = params.get("status")
    if raw is None:
        return frozenset(STATUS_VALUES)
    return frozenset(part.strip() for part in str(raw).split(",")) & STATUS_VALUES


def status_predicate(statuses: frozenset[str]) -> Any | None:  # noqa: ANN401 - SQLAlchemy clause
    """Match the rows the ticked Status boxes ask for, or None when they ask for all.

    Inclusion rather than exclusion: a tool is shown when it belongs to at
    least one ticked kind. The distinction is only visible on a tool carrying
    both flags, and there inclusion is the reading that matches the label --
    clearing Experimental while leaving Deprecated ticked still means "show me
    the deprecated ones", and a deprecated-and-experimental tool is one of
    them. Chaining an exclusion per cleared box would drop it from both.

    `active` is the complement of the other three rather than a flag of its
    own: nothing in toolinfo says "this tool is fine", only what is wrong with
    it. Archived is named in that complement, and again as a term of its own,
    because `include_archived` is the same tick as the Archived box: a row that
    reaches this predicate archived was asked for, so it stays, while an
    `active` blind to lifecycle would re-admit archived rows nobody ticked.
    """
    if statuses == STATUS_VALUES:
        return None
    terms = [CanonicalToolCache.lifecycle == LIFECYCLE_ARCHIVED]
    if STATUS_DEPRECATED in statuses:
        terms.append(CanonicalToolCache.deprecated.is_(True))
    if STATUS_EXPERIMENTAL in statuses:
        terms.append(CanonicalToolCache.experimental.is_(True))
    if STATUS_ACTIVE in statuses:
        terms.append(
            and_(
                CanonicalToolCache.deprecated.is_not(True),
                CanonicalToolCache.experimental.is_not(True),
                CanonicalToolCache.lifecycle != LIFECYCLE_ARCHIVED,
            )
        )
    return or_(*terms)


def _aggregate_rows(session: Session, filtered: Select) -> list[Any]:
    names = filtered.with_only_columns(CanonicalToolCache.tool_name).order_by(None).subquery()
    return list(
        session.execute(
            select(
                CatalogFacetValue.field,
                CatalogFacetValue.value,
                func.max(CatalogFacetValue.label),
                func.count(distinct(CatalogFacetValue.tool_name)),
            )
            .join(names, names.c.tool_name == CatalogFacetValue.tool_name)
            .where(CatalogFacetValue.field.in_(FACET_FIELDS.values()))
            .group_by(CatalogFacetValue.field, CatalogFacetValue.value)
            .order_by(
                CatalogFacetValue.field,
                func.count(distinct(CatalogFacetValue.tool_name)).desc(),
                CatalogFacetValue.value.asc(),
            )
        ).all()
    )


def payload_from_rows(rows: list[Any]) -> dict[str, Any]:
    """Build the Toolhub-compatible facet envelope from aggregate rows."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for field, value, label, count in rows:
        if len(buckets[field]) < FACET_BUCKET_LIMIT:
            buckets[field].append({"key": label or value, "doc_count": int(count)})
    return {
        f"_filter_{public_field}": {
            public_field: {
                "meta": {"param": f"{public_field}__term"},
                "buckets": buckets.get(stored_field, []),
            }
        }
        for public_field, stored_field in FACET_FIELDS.items()
    }


def dynamic_payload(session: Session, filtered: Select) -> dict[str, Any]:
    """Compute exact facets for one filtered result set."""
    return payload_from_rows(_aggregate_rows(session, filtered))


def cached_global_payload(session: Session) -> dict[str, Any] | None:
    """Return the last atomically published global aggregate, if usable."""
    row = session.get(ApiCacheMeta, CACHE_KEY)
    if row is None:
        return None
    try:
        wrapper = json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(wrapper, dict) or wrapper.get("version") != CACHE_VERSION:
        return None
    payload = wrapper.get("facets")
    return payload if isinstance(payload, dict) else None


def mark_dirty(session: Session) -> None:
    """Record that a background projection pass must republish aggregates.

    A locking write, never a read-then-insert. `session.get` answers from the
    transaction's REPEATABLE READ snapshot, which InnoDB fixes at the
    transaction's first read -- minutes earlier for a 20,000-tool projection
    batch, which calls this once at the end. A concurrent job that inserted the
    marker in that window stayed invisible to the snapshot, so the INSERT hit
    the primary key and rolled the whole batch back into STATUS_ERROR: one
    bookkeeping row discarded 20,000 computed projections, twice, during a
    single deploy. UPDATE reads the latest committed row rather than the
    snapshot, so its rowcount reports whether the marker really exists.

    The INSERT that follows a miss still races anything that commits between
    the two statements, so it runs inside a SAVEPOINT and falls back to the
    same UPDATE. The explicit flush first is what keeps that safe: it lands the
    caller's pending rows in the enclosing transaction, so rolling the SAVEPOINT
    back can only ever undo this marker, never the batch that asked for it.
    """
    now = utcnow()
    value = now.isoformat(timespec="seconds") + "Z"
    if _touch_dirty(session, value, now):
        return
    session.flush()
    try:
        with session.begin_nested():
            session.add(ApiCacheMeta(key=DIRTY_KEY, value=value))
            session.flush()
    except IntegrityError:
        _touch_dirty(session, value, now)


def _touch_dirty(session: Session, value: str, now: datetime) -> bool:
    """Stamp the existing dirty marker, reporting whether one was there."""
    result = session.execute(
        update(ApiCacheMeta).where(ApiCacheMeta.key == DIRTY_KEY).values(value=value, updated_at=now)
    )
    return bool(result.rowcount)


def rebuild_global_payload(*, force: bool = False) -> int:
    """Atomically replace the global facet aggregate outside request paths."""
    with db.advisory_lock("catalog-facets-v1", timeout_seconds=30 if force else 0) as acquired:
        if not acquired:
            return 0
        with db.session_scope() as session:
            dirty = session.get(ApiCacheMeta, DIRTY_KEY)
            existing = session.get(ApiCacheMeta, CACHE_KEY)
            if not force and dirty is None and existing is not None:
                return 0
            facets = dynamic_payload(session, default_population())
            state = session.get(ToolCatalogSyncState, STATE_KEY)
            wrapper = {
                "version": CACHE_VERSION,
                "generation": int(state.snapshot_generation or 0) if state is not None else 0,
                "builtAt": utcnow().isoformat(timespec="seconds") + "Z",
                "facets": facets,
            }
            value = json.dumps(wrapper, sort_keys=True, separators=(",", ":"))
            if existing is None:
                session.add(ApiCacheMeta(key=CACHE_KEY, value=value))
            else:
                existing.value = value
                existing.updated_at = utcnow()
            if dirty is not None:
                session.delete(dirty)
            return sum(
                len(group[public_field]["buckets"])
                for key, group in facets.items()
                if (public_field := key.removeprefix("_filter_")) in group
            )
