# SPDX-License-Identifier: GPL-3.0-or-later
"""Request-safe reads from the local Toolhub catalog replica.

No function in this module performs network I/O.  Toolhub is consumed by the
scheduled synchronizers; web requests only query the last published local
generation or collection payloads already persisted by those jobs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from sqlalchemy import func, select

from backend import activity_privacy, api_cache, catalog_facets, db, list_revisions
from backend.canonical_tools import escape_like
from backend.models import CanonicalToolCache, CatalogFacetValue, ToolCatalogSyncState, utcnow

if TYPE_CHECKING:
    from sqlalchemy.sql import Select

STATE_KEY = "official_catalog"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
FACET_FIELDS = catalog_facets.FACET_FIELDS


def _int(value: Any, default: int, *, minimum: int = 1, maximum: int = MAX_PAGE_SIZE) -> int:  # noqa: ANN401
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _values(params: Any, key: str) -> list[str]:  # noqa: ANN401 - Flask MultiDict or ordinary mapping
    raw = params.getlist(key) if hasattr(params, "getlist") else params.get(key, [])
    values = raw if isinstance(raw, list | tuple) else [raw]
    return list(dict.fromkeys(str(value).strip().casefold() for value in values if str(value).strip()))


def replica_status(*, record_count: int | None = None) -> dict[str, Any]:
    """Return public freshness and atomic-generation metadata."""
    with db.session_scope() as session:
        state = session.get(ToolCatalogSyncState, STATE_KEY)
        count = (
            int(record_count)
            if record_count is not None
            else int(session.scalar(select(func.count()).select_from(CanonicalToolCache)) or 0)
        )
    last_success = state.last_success_at if state is not None else None
    age = max(0, int((utcnow() - last_success).total_seconds())) if last_success else None
    return {
        "source": "local_replica",
        "upstreamOnRequest": False,
        "status": state.status if state is not None else "unavailable",
        "recordCount": count,
        "generation": int(state.snapshot_generation or 0) if state is not None else 0,
        "lastSuccessAt": last_success.isoformat(timespec="seconds") + "Z" if last_success else "",
        "lastCompletedAt": state.last_completed_at.isoformat(timespec="seconds") + "Z"
        if state is not None and state.last_completed_at
        else "",
        "ageSeconds": age,
        "stale": age is None or age > 60 * 60,
        "lastError": state.last_error or "" if state is not None else "replica has not been synchronized",
    }


def _filtered_statement(params: Any) -> Select[tuple[CanonicalToolCache]]:  # noqa: ANN401
    statement = select(CanonicalToolCache)
    query = str(params.get("q") or "").strip().casefold()
    if query:
        statement = statement.where(CanonicalToolCache.search_text.like(f"%{escape_like(query)}%", escape="\\"))
    for public_field, stored_field in FACET_FIELDS.items():
        selected = _values(params, f"{public_field}__term")
        if not selected:
            continue
        matching = select(CatalogFacetValue.tool_name).where(
            CatalogFacetValue.field == stored_field,
            CatalogFacetValue.value.in_(selected),
        )
        statement = statement.where(CanonicalToolCache.tool_name.in_(matching))
    return statement


def _facet_payload(session: Any, filtered: Any) -> dict[str, Any]:  # noqa: ANN401 - SQLAlchemy objects
    return catalog_facets.dynamic_payload(session, filtered)


def _has_catalog_filters(params: Any) -> bool:  # noqa: ANN401 - Flask MultiDict or mapping
    if str(params.get("q") or "").strip():
        return True
    return any(_values(params, f"{field}__term") for field in FACET_FIELDS)


def _include_facets(params: Any) -> bool:  # noqa: ANN401 - Flask MultiDict or mapping
    return str(params.get("include_facets", "true")).strip().casefold() not in {"0", "false", "no"}


def _facets_for(session: Any, filtered: Any, params: Any) -> dict[str, Any]:  # noqa: ANN401
    if not _has_catalog_filters(params):
        cached = catalog_facets.cached_global_payload(session)
        if cached is not None:
            return cached
    return _facet_payload(session, filtered)


def search_payload(params: Any) -> dict[str, Any]:  # noqa: ANN401 - Flask MultiDict or mapping
    """Return a Toolhub-compatible, filtered and paginated local search page."""
    page = _int(params.get("page"), 1, maximum=100_000)
    page_size = _int(params.get("page_size"), DEFAULT_PAGE_SIZE)
    filtered = _filtered_statement(params)
    ordering = str(params.get("ordering") or "")
    if ordering == "name":
        ordered = filtered.order_by(CanonicalToolCache.tool_name.asc())
    elif ordering == "-modified_date":
        ordered = filtered.order_by(CanonicalToolCache.modified_at_sort.desc(), CanonicalToolCache.tool_name.asc())
    elif ordering == "modified_date":
        ordered = filtered.order_by(CanonicalToolCache.modified_at_sort.asc(), CanonicalToolCache.tool_name.asc())
    else:
        ordered = filtered.order_by(CanonicalToolCache.tool_name.asc())
    compact = str(params.get("view") or "").strip().casefold() == "card"
    with db.session_scope() as session:
        total_statement = filtered.with_only_columns(func.count(CanonicalToolCache.tool_name)).order_by(None)
        total = int(session.scalar(total_statement) or 0)
        result_column = CanonicalToolCache.card_record if compact else CanonicalToolCache.record
        rows = list(
            session.execute(
                ordered.with_only_columns(result_column).offset((page - 1) * page_size).limit(page_size)
            ).scalars()
        )
        facets = _facets_for(session, filtered, params) if _include_facets(params) else {}
    query = {key: value for key, value in params.items() if key not in {"page", "include_facets", "view"}}
    next_url = None
    previous_url = None
    if page * page_size < total:
        next_url = f"/v1/catalog/search/tools/?{urlencode({**query, 'page': page + 1})}"
    if page > 1:
        previous_url = f"/v1/catalog/search/tools/?{urlencode({**query, 'page': page - 1})}"
    return {
        "count": total,
        "next": next_url,
        "previous": previous_url,
        "results": rows,
        "facets": facets,
        "canonical": True,
        "replica": replica_status(record_count=total) if not _has_catalog_filters(params) else replica_status(),
    }


def facet_search_payload(params: Any) -> dict[str, Any]:  # noqa: ANN401 - Flask MultiDict or mapping
    """Return exact facets independently so card first paint never waits for aggregation."""
    filtered = _filtered_statement(params)
    with db.session_scope() as session:
        facets = _facets_for(session, filtered, params)
    return {"facets": facets, "canonical": True}


def tool_payload(name: str) -> dict[str, Any] | None:
    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, str(name or "").strip())
        return dict(row.record) if row is not None and isinstance(row.record, dict) else None


def home_payload() -> dict[str, Any]:
    status = replica_status()
    return {
        "total_tools": status["recordCount"],
        "last_crawl_time": status["lastSuccessAt"],
        "last_crawl_changed": 0,
        "replica": status,
    }


def _cached_rows(path: str) -> list[dict[str, Any]]:
    """Merge locally persisted collection pages, newest copy winning."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for response in api_cache.responses_for_path(path):
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        candidates = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            identity = str(candidate.get("id") or candidate.get("name") or candidate.get("content_id") or "")
            if not identity:
                identity = json.dumps(candidate, sort_keys=True, default=str)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(candidate)
    return rows


def collection_payload(path: str, params: Any, *, include_replica: bool = True) -> dict[str, Any]:  # noqa: ANN401
    rows = _cached_rows(path)
    if path == "/api/lists/" and str(params.get("featured") or "").casefold() == "true":
        rows = [row for row in rows if row.get("featured") is True]
    list_activity_available: bool | None = None
    if path == "/api/recent/":
        # Filtered before paging so `count` and `next` describe the rows a
        # reader may actually see. The replica mirrors upstream verbatim, and
        # upstream reports revisions for unpublished lists and for every user's
        # favorites list.
        published = published_list_ids()
        rows = activity_privacy.public_activity_rows(rows, published)
        # An empty allowlist means the replica has not synchronized any list
        # yet, so *every* upstream list revision failed closed. Readers are told
        # that much and no more: naming the withheld rows would itself disclose
        # that an unpublished list changed.
        list_activity_available = bool(published)
        # Collapsed before paging, for the same reason as the filter above: a
        # page of thirty must hold thirty rows a reader can tell apart, not
        # thirty revisions of one list that read as the same line repeated.
        rows = list_revisions.group_list_activity(rows)
    page = _int(params.get("page"), 1, maximum=100_000)
    page_size = _int(params.get("page_size"), DEFAULT_PAGE_SIZE)
    offset = (page - 1) * page_size
    selected = rows[offset : offset + page_size]
    if path == "/api/recent/":
        # After slicing, so the lookup covers one page of rows rather than the
        # whole replica.
        selected = list_revisions.attach_tool_changes(selected)
    payload = {
        "count": len(rows),
        "next": f"/v1/catalog/{path.removeprefix('/api/')}?page={page + 1}&page_size={page_size}"
        if offset + page_size < len(rows)
        else None,
        "previous": f"/v1/catalog/{path.removeprefix('/api/')}?page={page - 1}&page_size={page_size}"
        if page > 1
        else None,
        "results": selected,
    }
    if list_activity_available is not None:
        payload["listActivityAvailable"] = list_activity_available
    if include_replica:
        payload["replica"] = replica_status()
    return payload


def replica_rows(path: str) -> list[dict[str, Any]]:
    """Return every locally persisted row for one collection.

    The scheduled jobs read the replica through this rather than through
    `collection_payload`, which pages and enriches for a reader.
    """
    return _cached_rows(path)


def list_payload(list_id: str) -> dict[str, Any] | None:
    clean = str(list_id or "").strip()
    return next((row for row in _cached_rows("/api/lists/") if str(row.get("id")) == clean), None)


def cached_payload(url: str) -> tuple[bytes, str, int] | None:
    cached = api_cache.get_local(url)
    return (cached.body, cached.content_type, cached.status) if cached is not None else None


def published_list_ids() -> frozenset[str]:
    """Return the replica ids of lists Toolhub serves to anonymous readers.

    Only the published collection is synchronized, so a private list is simply
    absent here.  Activity feeds treat that absence as "not public" rather than
    "unknown", which is what keeps an unpublished list's title and owner out of
    the shared feeds.  Per-user favorites lists are excluded explicitly too:
    Toolhub keeps them unpublished, and one leaking into the replica must not
    turn into a public record of what somebody favorited.
    """
    ids = {
        str(row.get("id") or "").strip()
        for row in _cached_rows("/api/lists/")
        if row.get("published") is not False and row.get("favorites") is not True
    }
    return frozenset(ids - {""})
