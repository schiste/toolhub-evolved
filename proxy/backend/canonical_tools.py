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
    return upsert_records(records, source_url=url, detail=_is_tool_detail_url(url))


def _is_tool_detail_url(url: str) -> bool:
    parts = _path_parts(url)
    return len(parts) == TOOL_DETAIL_PARTS and parts[0] == "api" and parts[1] == "tools" and bool(parts[2])


def upsert_records(records: list[dict[str, Any]], *, source_url: str, detail: bool = False) -> int:
    """Persist canonical official tool records into the structured cache."""
    now = utcnow()
    fresh = DETAIL_FRESH_SECONDS if detail else SEARCH_FRESH_SECONDS
    expires_at = now + timedelta(seconds=fresh)
    stale_until = now + timedelta(seconds=fresh + STALE_IF_ERROR_SECONDS)
    seen: set[str] = set()
    rows: list[CanonicalToolCache] = []
    for record in records:
        name = _clean_name(record.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(
            CanonicalToolCache(
                tool_name=name,
                record=record,
                source_url=source_url[:MAX_SOURCE_URL],
                source=SOURCE_OFFICIAL,
                sync_status=SYNC_OFFICIAL,
                fetched_at=now,
                expires_at=expires_at,
                stale_until=stale_until,
                last_error=None,
            )
        )
    if not rows:
        return 0
    try:
        with db.session_scope() as s:
            for row in rows:
                s.merge(row)
        return len(rows)
    except SQLAlchemyError:
        return 0


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
