# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent cache for anonymous Toolhub reads and bounded derived public payloads."""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend import db
from backend.models import ApiCache, ApiCacheMeta, utcnow

# Freshness is a backstop, not the primary correctness mechanism: the
# api-cache-invalidator job polls Toolhub's recent-change feed every
# RECENT_POLL_SECONDS and deletes the rows a change actually affects. Toolhub
# sees a handful of edits a day, so short TTLs bought no freshness the poll did
# not already provide and cost an upstream revalidation on nearly every visit.
#
# These windows must stay in step with the mirrored client policy in
# public_html/lib/core/api.js; tests/proxy/test_app.py fails if they drift.
RECENT_FRESH_SECONDS = 5 * 60
SEARCH_FRESH_SECONDS = 30 * 60
DETAIL_FRESH_SECONDS = 6 * 60 * 60
CRAWLER_FRESH_SECONDS = 6 * 60 * 60
CONFIG_FRESH_SECONDS = 24 * 60 * 60
DEFAULT_FRESH_SECONDS = 15 * 60
STALE_IF_ERROR_SECONDS = 24 * 60 * 60
# Deliberately independent of RECENT_FRESH_SECONDS. The poll is what makes the
# longer windows above safe, so how often we look for changes must not move
# just because we changed how long a cached recent feed is served.
RECENT_POLL_SECONDS = 30

# Compatibility aliases for tests/callers that only need the default policy.
FRESH_SECONDS = DEFAULT_FRESH_SECONDS
STALE_SECONDS = STALE_IF_ERROR_SECONDS

_STALE_RESPONSE_FRESH_SECONDS = 30
_DETAIL_PATH_PARTS = 3
_DETAIL_COLLECTIONS = {"tools", "lists"}
_CONFIG_PATHS = {
    "/api/",
    "/api/schema/",
    "/api/audiences/",
    "/api/content-types/",
    "/api/licenses/",
    "/api/origins/",
    "/api/tasks/",
    "/api/tool-types/",
    "/api/technology-used/",
    "/api/wikis/",
}
_RECENT_LAST_POLLED_KEY = "recent_last_polled_at"
_RECENT_LATEST_MARKER_KEY = "recent_latest_marker"
_TOOL_AGGREGATE_PATHS = {"/api/search/tools/", "/api/ui/home/"}
_LIST_COLLECTION_PATH = "/api/lists/"
_RECENT_COLLECTION_PATH = "/api/recent/"
_CRAWLER_RUNS_PATH = "/api/crawler/runs/"
_GRAPH_PATH = "/v1/graph/"
_LIST_AND_RECENT_PATHS = {_LIST_COLLECTION_PATH, _RECENT_COLLECTION_PATH}


@dataclass(frozen=True)
class CachePolicy:
    """Fresh and stale-if-error windows for one anonymous Toolhub endpoint."""

    fresh_seconds: int
    stale_if_error_seconds: int = STALE_IF_ERROR_SECONDS

    @property
    def stale_until_seconds(self) -> int:
        """Total row lifetime: fresh window plus stale-if-error window."""
        return self.fresh_seconds + self.stale_if_error_seconds


@dataclass(frozen=True)
class CachedResponse:
    """A detached cached HTTP response body."""

    url: str
    status: int
    content_type: str
    body: bytes
    stale: bool
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class CacheableResponse:
    """A successful upstream response ready to persist."""

    status: int
    content_type: str
    body: bytes
    etag: str | None = None
    last_modified: str | None = None


def _key(url: str) -> str:
    """Return a compact, index-safe cache key for an upstream URL."""
    return sha256(url.encode("utf-8")).hexdigest()


def _path(url: str) -> str:
    """Extract a normalized upstream API path from a full or relative URL."""
    return urlparse(url).path.rstrip("/") + "/"


def _path_parts(url: str) -> list[str]:
    """Return decoded path parts for upstream cache URL matching."""
    return [unquote(part) for part in _path(url).strip("/").split("/") if part]


def _index_keys(url: str) -> tuple[str, str, str]:
    """Return the (path, collection, detail_key) invalidation columns for a URL.

    Derived once at write time; `invalidate_*` then matches on indexed columns
    rather than re-parsing every stored URL.
    """
    parts = _path_parts(url)
    if not parts or parts[0] != "api":
        return _path(url), "", ""
    collection = parts[1] if len(parts) > 1 else ""
    detail_key = parts[2] if len(parts) > _DETAIL_PATH_PARTS - 1 else ""
    return _path(url), collection, detail_key


def _is_detail_path(path: str) -> bool:
    """Return true for /api/tools/:name/ and /api/lists/:id/ detail reads."""
    parts = path.strip("/").split("/")
    return len(parts) == _DETAIL_PATH_PARTS and parts[0] == "api" and parts[1] in _DETAIL_COLLECTIONS and bool(parts[2])


def policy_for_url(url: str) -> CachePolicy:
    """Return cache policy for an anonymous Toolhub API URL."""
    path = _path(url)
    if path == "/api/recent/":
        return CachePolicy(RECENT_FRESH_SECONDS)
    if path == "/api/search/tools/":
        return CachePolicy(SEARCH_FRESH_SECONDS)
    if path == _CRAWLER_RUNS_PATH:
        return CachePolicy(CRAWLER_FRESH_SECONDS)
    if _is_detail_path(path):
        return CachePolicy(DETAIL_FRESH_SECONDS)
    if path in _CONFIG_PATHS:
        return CachePolicy(CONFIG_FRESH_SECONDS)
    return CachePolicy(DEFAULT_FRESH_SECONDS)


def cache_control(url: str, *, stale: bool = False) -> str:
    """Return browser/intermediate cache headers aligned with the API policy."""
    policy = policy_for_url(url)
    max_age = _STALE_RESPONSE_FRESH_SECONDS if stale else policy.fresh_seconds
    return f"public, max-age={max_age}, stale-if-error={policy.stale_if_error_seconds}"


def get(url: str, *, allow_stale: bool = False) -> CachedResponse | None:
    """Return a fresh cache hit, or a stale hit when explicitly allowed."""
    now = utcnow()
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is None:
                return None
            if row.expires_at > now:
                stale = False
            elif allow_stale and row.stale_until > now:
                stale = True
            else:
                return None
            return CachedResponse(
                url=row.url,
                status=row.status,
                content_type=row.content_type,
                body=bytes(row.body),
                stale=stale,
                etag=row.etag,
                last_modified=row.last_modified,
            )
    except SQLAlchemyError:
        return None


def put_success(
    url: str,
    upstream: CacheableResponse,
    *,
    fresh_seconds: int | None = None,
    stale_if_error_seconds: int | None = None,
) -> None:
    """Store a successful anonymous Toolhub API response."""
    now = utcnow()
    policy = policy_for_url(url)
    fresh = policy.fresh_seconds if fresh_seconds is None else fresh_seconds
    stale_if_error = policy.stale_if_error_seconds if stale_if_error_seconds is None else stale_if_error_seconds
    path, collection, detail_key = _index_keys(url)
    row = ApiCache(
        url_hash=_key(url),
        url=url,
        path=path,
        collection=collection,
        detail_key=detail_key,
        status=upstream.status,
        content_type=upstream.content_type,
        body=upstream.body,
        fetched_at=now,
        expires_at=now + timedelta(seconds=fresh),
        stale_until=now + timedelta(seconds=fresh + stale_if_error),
        etag=upstream.etag,
        last_modified=upstream.last_modified,
        last_error=None,
    )
    try:
        with db.session_scope() as s:
            s.merge(row)
    except SQLAlchemyError:
        # Cache persistence must never break live reads.
        return


def refresh(url: str, *, fresh_seconds: int | None = None, stale_if_error_seconds: int | None = None) -> None:
    """Refresh cache timestamps after upstream confirms the cached body is current."""
    now = utcnow()
    policy = policy_for_url(url)
    fresh = policy.fresh_seconds if fresh_seconds is None else fresh_seconds
    stale_if_error = policy.stale_if_error_seconds if stale_if_error_seconds is None else stale_if_error_seconds
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is None:
                return
            row.fetched_at = now
            row.expires_at = now + timedelta(seconds=fresh)
            row.stale_until = now + timedelta(seconds=fresh + stale_if_error)
            row.last_error = None
    except SQLAlchemyError:
        return


def mark_failure(url: str, error: str) -> None:
    """Record the latest revalidation failure without caching an error body."""
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is not None:
                row.last_error = error[:2000]
    except SQLAlchemyError:
        return


def needs_refresh(url: str, *, refresh_ahead_seconds: int = 0) -> bool:
    """Return true when a cache row is missing or close enough to expiry to refresh."""
    now = utcnow()
    try:
        with db.session_scope() as s:
            row = s.get(ApiCache, _key(url))
            if row is None:
                return True
            return row.expires_at <= now + timedelta(seconds=max(0, refresh_ahead_seconds))
    except SQLAlchemyError:
        return True


def _metadata_value(s: Session, key: str) -> str | None:
    """Return one cache metadata value."""
    row = s.get(ApiCacheMeta, key)
    return row.value if row is not None else None


def _set_metadata(s: Session, key: str, value: str, now: datetime) -> None:
    """Upsert one cache metadata value."""
    s.merge(ApiCacheMeta(key=key, value=value, updated_at=now))


def _parse_metadata_datetime(value: str | None) -> datetime | None:
    """Parse a naive UTC datetime written by this cache module."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _poll_is_due(last_polled_at: str | None, now: datetime) -> bool:
    """Return true when the recent-change invalidation poll should run."""
    last_polled = _parse_metadata_datetime(last_polled_at)
    return last_polled is None or now - last_polled >= timedelta(seconds=RECENT_POLL_SECONDS)


def _recent_marker(row: dict[str, Any]) -> str | None:
    """Return the stable timestamp/id marker for one Toolhub recent row."""
    timestamp = row.get("timestamp")
    ident = row.get("id")
    if timestamp is None and ident is None:
        return None
    return json.dumps(
        {
            "id": "" if ident is None else str(ident),
            "timestamp": "" if timestamp is None else str(timestamp),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _latest_marker(rows: Iterable[dict[str, Any]]) -> str | None:
    """Return the first usable marker from a newest-first recent feed page."""
    for row in rows:
        marker = _recent_marker(row)
        if marker is not None:
            return marker
    return None


def _new_recent_rows(rows: list[dict[str, Any]], last_marker: str | None) -> list[dict[str, Any]]:
    """Return rows newer than the previously recorded recent marker."""
    if last_marker is None:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if _recent_marker(row) == last_marker:
            break
        out.append(row)
    return out


def _recent_content_id(row: dict[str, Any]) -> str | None:
    """Return the official object id used by Toolhub recent rows."""
    content_id = row.get("content_id")
    if content_id is None:
        return None
    value = str(content_id).strip()
    return value or None


def _tool_clause(tool_names: set[str]) -> ColumnElement[bool] | None:
    """Build the SQL predicate for cached reads affected by changed tool names."""
    if not tool_names:
        return None
    return or_(
        ApiCache.path.in_([_RECENT_COLLECTION_PATH, *_TOOL_AGGREGATE_PATHS]),
        and_(ApiCache.collection == "tools", ApiCache.detail_key.in_(sorted(tool_names))),
    )


def _list_clause(list_ids: set[str]) -> ColumnElement[bool] | None:
    """Build the SQL predicate for cached reads affected by changed list ids."""
    if not list_ids:
        return None
    return or_(
        ApiCache.path.in_(sorted(_LIST_AND_RECENT_PATHS)),
        and_(ApiCache.collection == "lists", ApiCache.detail_key.in_(sorted(list_ids))),
    )


def _delete_where(clause: ColumnElement[bool] | None) -> int:
    """Delete cached rows matching an indexed SQL predicate.

    Matching happens in the database. The previous Python-side scan had to load
    every row — `body` blobs included, tens of MB against ToolsDB — to read one
    URL per row, on a path that runs every minute and on every official write.
    """
    if clause is None:
        return 0
    try:
        with db.session_scope() as s:
            return int(s.execute(delete(ApiCache).where(clause)).rowcount or 0)
    except SQLAlchemyError:
        return 0


def invalidate_tool(tool_name: str) -> int:
    """Invalidate cached official reads affected by one changed Toolhub tool."""
    name = str(tool_name).strip()
    if not name:
        return 0
    return _delete_where(_tool_clause({name}))


def invalidate_list(list_id: int | str) -> int:
    """Invalidate cached official reads affected by one changed Toolhub list."""
    ident = str(list_id).strip()
    if not ident:
        return 0
    return _delete_where(_list_clause({ident}))


def invalidate_list_collection() -> int:
    """Invalidate cached official list collection and recent feed reads."""
    return _delete_where(ApiCache.path.in_([_LIST_COLLECTION_PATH, _RECENT_COLLECTION_PATH]))


def invalidate_graph() -> int:
    """Invalidate all versioned derived graph payloads after facet changes."""
    return _delete_where(ApiCache.path == _GRAPH_PATH)


def invalidate_url(url: str) -> int:
    """Invalidate one exact cached entry, derived payloads included."""
    return _delete_where(ApiCache.url_hash == _key(url))


def invalidate_recent_rows(rows: Iterable[dict[str, Any]]) -> int:
    """Invalidate cached official reads affected by Toolhub recent rows."""
    tool_names: set[str] = set()
    list_ids: set[str] = set()
    for row in rows:
        content_type = str(row.get("content_type") or "").lower()
        content_id = _recent_content_id(row)
        if content_type == "tool" and content_id is not None:
            tool_names.add(content_id)
        elif content_type == "list" and content_id is not None:
            list_ids.add(content_id)
    clauses = [clause for clause in (_tool_clause(tool_names), _list_clause(list_ids)) if clause is not None]
    if not clauses:
        return 0
    return _delete_where(or_(*clauses) if len(clauses) > 1 else clauses[0])


def maybe_poll_recent_changes(fetch_recent: Callable[[], list[dict[str, Any]]]) -> int:
    """Poll Toolhub recent changes and invalidate shared cache rows if newer rows appear."""
    now = utcnow()
    try:
        with db.session_scope() as s:
            last_polled_at = _metadata_value(s, _RECENT_LAST_POLLED_KEY)
            if not _poll_is_due(last_polled_at, now):
                return 0
            last_marker = _metadata_value(s, _RECENT_LATEST_MARKER_KEY)
            _set_metadata(s, _RECENT_LAST_POLLED_KEY, now.isoformat(), now)
    except SQLAlchemyError:
        return 0

    try:
        rows = [row for row in fetch_recent() if isinstance(row, dict)]
    except Exception:  # noqa: BLE001 - recent polling must never break anonymous API reads.
        return 0

    latest_marker = _latest_marker(rows)
    if latest_marker is None:
        return 0
    new_rows = _new_recent_rows(rows, last_marker)
    removed = invalidate_recent_rows(new_rows)
    try:
        with db.session_scope() as s:
            _set_metadata(s, _RECENT_LATEST_MARKER_KEY, latest_marker, utcnow())
    except SQLAlchemyError:
        return removed
    return removed


def backfill_index_columns(*, batch_size: int = 500) -> int:
    """Populate path/collection/detail_key for rows cached before those columns.

    A row with no path cannot be matched by any invalidate_*, so a changed tool
    would never evict it and it would serve stale for its whole stale-if-error
    window. Deriving the keys from the stored URL keeps the cache intact;
    dropping the rows instead would empty the shared cache at exactly the
    moment a deploy restarts every worker, and send the resulting cold traffic
    straight upstream.

    Batched, and safe to run repeatedly: only rows still missing a path are touched.
    """
    filled = 0
    while True:
        try:
            with db.session_scope() as s:
                rows = list(s.execute(select(ApiCache).where(ApiCache.path == "").limit(batch_size)).scalars())
                if not rows:
                    return filled
                for row in rows:
                    row.path, row.collection, row.detail_key = _index_keys(row.url)
                    filled += 1
        except SQLAlchemyError:
            return filled


def clear() -> None:
    """Clear the API cache, used by tests and operator cleanup scripts."""
    with db.session_scope() as s:
        s.execute(delete(ApiCache))
        s.execute(delete(ApiCacheMeta))
