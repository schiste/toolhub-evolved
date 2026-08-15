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

from sqlalchemy import distinct, func, select

from backend import db
from backend.models import ApiCacheMeta, CanonicalToolCache, CatalogFacetValue, ToolCatalogSyncState, utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from sqlalchemy.sql import Select

STATE_KEY = "official_catalog"
CACHE_KEY = "catalog:facets:v1"
DIRTY_KEY = "catalog:facets:dirty:v1"
CACHE_VERSION = 1
FACET_BUCKET_LIMIT = 50
FACET_FIELDS = {
    "tool_type": "tool_type",
    "keywords": "keywords",
    "audiences": "audiences",
    "tasks": "tasks",
    "ui_language": "ui_language",
    "license": "license",
    "wiki": "wiki",
    "technology": "technology",
}


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
    """Record that a background projection pass must republish aggregates."""
    row = session.get(ApiCacheMeta, DIRTY_KEY)
    value = utcnow().isoformat(timespec="seconds") + "Z"
    if row is None:
        session.add(ApiCacheMeta(key=DIRTY_KEY, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()


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
            facets = dynamic_payload(session, select(CanonicalToolCache))
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
