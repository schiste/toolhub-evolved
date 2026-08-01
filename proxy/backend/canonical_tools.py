# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured local cache of canonical official Toolhub tool records."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend import db
from backend.api_cache import DETAIL_FRESH_SECONDS, SEARCH_FRESH_SECONDS, STALE_IF_ERROR_SECONDS
from backend.models import CanonicalToolCache, utcnow
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL

MAX_INGEST_TOOLS = 100
MAX_QUERY_NAMES = 50
MAX_SEARCH_RESULTS = 50
MAX_SOURCE_URL = 2000
TOOL_DETAIL_PARTS = 3
MAX_RECORD_RESULTS = 5000


def _clean_name(value: Any) -> str:  # noqa: ANN401 - untrusted official API JSON
    return str(value or "").strip()[:255]


def _path(url: str) -> str:
    return urlparse(url).path.rstrip("/") + "/"


def _path_parts(url: str) -> list[str]:
    return [unquote(part) for part in _path(url).strip("/").split("/") if part]


def _is_tool_record(value: Any) -> bool:  # noqa: ANN401 - untrusted official API JSON
    if not isinstance(value, dict):
        return False
    if not _clean_name(value.get("name")):
        return False
    return any(key in value for key in ("title", "description", "url", "tool_type", "author", "modified_date"))


def _iter_tool_records(value: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - untrusted official API JSON
    out: list[dict[str, Any]] = []
    stack = [value]
    while stack and len(out) < MAX_INGEST_TOOLS:
        current = stack.pop()
        if _is_tool_record(current):
            out.append(current)
            continue
        if isinstance(current, dict):
            for key in ("results", "tools", "featured", "recent", "most_listed"):
                nested = current.get(key)
                if isinstance(nested, list | dict):
                    stack.append(nested)
        elif isinstance(current, list):
            stack.extend(reversed(current))
    return out


def ingest_payload(url: str, body: bytes) -> int:
    """Extract official tool records from one cached Toolhub API payload."""
    path = _path(url)
    if not (path.startswith(("/api/tools/", "/api/lists/")) or path in {"/api/search/tools/", "/api/ui/home/"}):
        return 0
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    records = _iter_tool_records(payload)
    if not records:
        return 0
    return upsert_records(records, source_url=url, detail=is_tool_detail_url(url))


def is_tool_detail_url(url: str) -> bool:
    parts = _path_parts(url)
    return len(parts) == TOOL_DETAIL_PARTS and parts[0] == "api" and parts[1] == "tools" and bool(parts[2])


def _has_value(value: Any) -> bool:  # noqa: ANN401 - official API JSON
    return value not in (None, "", [], {})


def _merge_listing_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Apply listing fields without erasing richer detail-only metadata."""
    merged = dict(existing)
    for key, value in incoming.items():
        if _has_value(value) or key not in merged:
            merged[key] = value
    return merged


def upsert_records(records: list[dict[str, Any]], *, source_url: str, detail: bool = False) -> int:
    """Persist canonical official tool records into the structured cache."""
    now = utcnow()
    fresh = DETAIL_FRESH_SECONDS if detail else SEARCH_FRESH_SECONDS
    expires_at = now + timedelta(seconds=fresh)
    stale_until = now + timedelta(seconds=fresh + STALE_IF_ERROR_SECONDS)
    seen: set[str] = set()
    clean_records: list[tuple[str, dict[str, Any]]] = []
    for record in records:
        name = _clean_name(record.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        clean_records.append((name, record))
    if not clean_records:
        return 0
    try:
        with db.session_scope() as s:
            for name, record in clean_records:
                row = s.get(CanonicalToolCache, name)
                existing_is_detail = bool(row and is_tool_detail_url(row.source_url))
                if row is None:
                    row = CanonicalToolCache(tool_name=name)
                    s.add(row)
                row.record = record if detail else _merge_listing_record(row.record or {}, record)
                if detail or not existing_is_detail:
                    row.source_url = source_url[:MAX_SOURCE_URL]
                    row.expires_at = expires_at
                    row.stale_until = stale_until
                row.source = SOURCE_OFFICIAL
                row.sync_status = SYNC_OFFICIAL
                row.fetched_at = now
                row.last_error = None
    except SQLAlchemyError:
        return 0
    # Queue only after the canonical transaction succeeds. Processing is
    # asynchronous so anonymous API requests do not wait on derived indexes.
    from backend.people_reconcile import enqueue_tool_names  # noqa: PLC0415 - avoid backend startup cycles.

    enqueue_tool_names([name for name, _record in clean_records], reason="canonical_fetch")
    return len(clean_records)


def _payload(row: CanonicalToolCache) -> dict[str, Any]:
    return {
        "toolName": row.tool_name,
        "record": row.record,
        "sourceUrl": row.source_url,
        "source": row.source or SOURCE_OFFICIAL,
        "syncStatus": row.sync_status or SYNC_OFFICIAL,
        "fetchedAt": row.fetched_at.isoformat(timespec="seconds") + "Z" if row.fetched_at else "",
        "expiresAt": row.expires_at.isoformat(timespec="seconds") + "Z" if row.expires_at else "",
        "staleUntil": row.stale_until.isoformat(timespec="seconds") + "Z" if row.stale_until else "",
        "stale": bool(row.expires_at and row.expires_at <= utcnow()),
        "lastError": row.last_error or "",
    }


def tools_by_name(names: list[str]) -> dict[str, dict[str, Any]]:
    """Return cached canonical tool records by exact Toolhub name."""
    clean_names = []
    seen: set[str] = set()
    for name in names:
        clean = _clean_name(name)
        if clean and clean not in seen:
            seen.add(clean)
            clean_names.append(clean)
    clean_names = clean_names[:MAX_QUERY_NAMES]
    if not clean_names:
        return {}
    with db.session_scope() as s:
        rows = list(
            s.execute(select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(clean_names))).scalars()
        )
    return {row.tool_name: _payload(row) for row in rows}


def search(query: str = "", *, limit: int = MAX_SEARCH_RESULTS) -> list[dict[str, Any]]:
    """Search cached canonical records locally with simple deterministic matching."""
    term = str(query or "").strip().casefold()
    capped = max(1, min(MAX_SEARCH_RESULTS, int(limit or MAX_SEARCH_RESULTS)))
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(CanonicalToolCache).order_by(CanonicalToolCache.fetched_at.desc(), CanonicalToolCache.tool_name)
            ).scalars()
        )
    if term:
        rows = [
            row
            for row in rows
            if term
            in "\n".join(
                [
                    str(row.tool_name or ""),
                    str((row.record or {}).get("title") or ""),
                    str((row.record or {}).get("description") or ""),
                ]
            ).casefold()
        ]
    return [_payload(row) for row in rows[:capped]]


def records(*, limit: int = MAX_RECORD_RESULTS) -> list[dict[str, Any]]:
    """Return recent canonical records for deterministic derived indexes."""
    capped = max(1, min(MAX_RECORD_RESULTS, int(limit or MAX_RECORD_RESULTS)))
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(CanonicalToolCache)
                .order_by(CanonicalToolCache.fetched_at.desc(), CanonicalToolCache.tool_name)
                .limit(capped)
            ).scalars()
        )
    return [_payload(row) for row in rows]
