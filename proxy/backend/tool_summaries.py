# SPDX-License-Identifier: GPL-3.0-or-later
"""Materialized public summaries for tool cards and detail pages."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import db
from backend.models import ToolSummaryCache, utcnow
from backend.sync import SOURCE_LOCAL, SYNC_EVOLVED_REAL, clean_error

SUMMARY_FRESH_SECONDS = 30 * 60
SUMMARY_STALE_SECONDS = 24 * 60 * 60
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool-summary-cache")
_REFRESH_LOCK = Lock()
_REFRESHING: set[str] = set()

SummaryBuilder = Callable[[Session, str], dict[str, Any]]


@dataclass(frozen=True)
class SummaryRead:
    """Results plus per-tool cache metadata for one summary read."""

    results: dict[str, dict[str, Any]]
    cache_meta: dict[str, dict[str, str]]


def _iso(value: datetime | None) -> str:
    """Serialize optional datetimes as API ISO strings."""
    return value.isoformat(timespec="seconds") + "Z" if value is not None else ""


def _cache_meta(row: ToolSummaryCache, status: str) -> dict[str, str]:
    """Return frontend-safe freshness metadata for one cached summary."""
    return {
        "status": status,
        "computedAt": _iso(row.computed_at),
        "expiresAt": _iso(row.expires_at),
        "staleUntil": _iso(row.stale_until),
        "lastError": row.last_error or "",
    }


def _fresh_payload(row: ToolSummaryCache, now: datetime) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Return a fresh cached payload when the row has not expired."""
    if now >= row.expires_at:
        return None
    return dict(row.summary), _cache_meta(row, "hit")


def _stale_payload(row: ToolSummaryCache, now: datetime) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Return a stale-but-servable cached payload when it is inside the stale window."""
    if now >= row.stale_until:
        return None
    return dict(row.summary), _cache_meta(row, "stale")


def _store(
    s: Session,
    row: ToolSummaryCache | None,
    *,
    tool_name: str,
    summary: dict[str, Any],
    now: datetime,
) -> ToolSummaryCache:
    """Upsert one materialized summary row."""
    stored = row or ToolSummaryCache(tool_name=tool_name)
    stored.summary = summary
    stored.source = SOURCE_LOCAL
    stored.sync_status = SYNC_EVOLVED_REAL
    stored.computed_at = now
    stored.expires_at = now + timedelta(seconds=SUMMARY_FRESH_SECONDS)
    stored.stale_until = now + timedelta(seconds=SUMMARY_STALE_SECONDS)
    stored.last_error = None
    s.add(stored)
    return stored


def _build_and_store(
    s: Session,
    *,
    tool_name: str,
    row: ToolSummaryCache | None,
    build_summary: SummaryBuilder,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build one summary and persist it before returning the payload."""
    summary = build_summary(s, tool_name)
    stored = _store(s, row, tool_name=tool_name, summary=summary, now=now)
    return dict(summary), _cache_meta(stored, "miss")


def _rows_by_name(s: Session, names: tuple[str, ...]) -> dict[str, ToolSummaryCache]:
    """Load cache rows for the requested names."""
    rows = s.execute(select(ToolSummaryCache).where(ToolSummaryCache.tool_name.in_(names))).scalars()
    return {row.tool_name: row for row in rows}


def summaries_for(names: list[str], build_summary: SummaryBuilder, *, refresh_stale: bool = True) -> SummaryRead:
    """Return local summaries, materializing missing rows and queueing stale refreshes."""
    ordered_names = tuple(dict.fromkeys(names))
    if not ordered_names:
        return SummaryRead(results={}, cache_meta={})

    stale_names: list[str] = []
    now = utcnow()
    with db.session_scope() as s:
        rows = _rows_by_name(s, ordered_names)
        results: dict[str, dict[str, Any]] = {}
        cache_meta: dict[str, dict[str, str]] = {}
        for name in ordered_names:
            row = rows.get(name)
            if row is not None:
                fresh = _fresh_payload(row, now)
                if fresh is not None:
                    results[name], cache_meta[name] = fresh
                    continue
                stale = _stale_payload(row, now)
                if stale is not None:
                    results[name], cache_meta[name] = stale
                    stale_names.append(name)
                    continue
            results[name], cache_meta[name] = _build_and_store(
                s,
                tool_name=name,
                row=row,
                build_summary=build_summary,
                now=now,
            )

    if refresh_stale and stale_names:
        queue_refresh(stale_names, build_summary)
    return SummaryRead(results=results, cache_meta=cache_meta)


def refresh(names: list[str], build_summary: SummaryBuilder) -> int:
    """Rebuild and store summaries for the supplied tool names."""
    ordered_names = tuple(dict.fromkeys(names))
    if not ordered_names:
        return 0
    now = utcnow()
    with db.session_scope() as s:
        rows = _rows_by_name(s, ordered_names)
        for name in ordered_names:
            _build_and_store(s, tool_name=name, row=rows.get(name), build_summary=build_summary, now=now)
    return len(ordered_names)


def _refresh_worker(names: tuple[str, ...], build_summary: SummaryBuilder) -> None:
    """Background worker that refreshes stale summaries without blocking readers."""
    try:
        refresh(list(names), build_summary)
    except Exception as exc:  # noqa: BLE001 - stale refresh must never affect the request that queued it.
        with db.session_scope() as s:
            for name in names:
                row = s.get(ToolSummaryCache, name)
                if row is not None:
                    row.last_error = clean_error(str(exc))
    finally:
        with _REFRESH_LOCK:
            _REFRESHING.difference_update(names)


def queue_refresh(names: list[str], build_summary: SummaryBuilder) -> None:
    """Queue one background refresh for each stale summary not already running."""
    with _REFRESH_LOCK:
        queued = tuple(name for name in dict.fromkeys(names) if name not in _REFRESHING)
        _REFRESHING.update(queued)
    if queued:
        _EXECUTOR.submit(_refresh_worker, queued, build_summary)
