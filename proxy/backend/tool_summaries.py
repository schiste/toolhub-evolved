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
# Ceiling on names awaiting a background build. Reads re-queue what is dropped,
# so this caps memory and worker backlog without losing coverage.
MAX_QUEUED_BUILDS = 500
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool-summary-cache")
_REFRESH_LOCK = Lock()
_REFRESHING: set[str] = set()

SummaryBuilder = Callable[[Session, str], dict[str, Any]]

#: The two shapes a stored summary is served in. "full" is the materialized
#: record; "card" is the subset a tool card can render.
VIEW_FULL = "full"
VIEW_CARD = "card"
VIEWS = (VIEW_FULL, VIEW_CARD)
#: Count blocks a card needs from the maintainer record. Two names because the
#: field is mid-rename; carrying both keeps cards correct whichever the
#: frontend in the browser is reading.
MAINTAINER_COUNT_KEYS = ("counts", "healthCounts")
#: Parts of `health` that only the score popover reads. They are most of a
#: summary's remaining weight, and the popover starts collapsed, so cards get
#: them after the page has loaded rather than inside the payload that renders it.
#: `dimensions` doubles as the marker: absent means "not loaded yet", whereas an
#: empty list means the tool genuinely has none.
HEALTH_POPOVER_KEYS = ("dimensions", "calculation", "sourceHealth")


def card_view(summary: dict[str, Any]) -> dict[str, Any]:
    """Project a stored summary down to what a tool card paints immediately.

    A card paints a score chip and a maintainer byline. It also carries the
    calculation breakdown, but inside a collapsed popover that most readers
    never open — so that part is fetched after the route has rendered and
    patched into the panel in place.

    What is left is the score, the grade, and the maintainer counts behind the
    byline. The maintainer record and the popover payload are both dropped; the
    people list alone is the largest block in a summary and no card reads it.
    """
    projected: dict[str, Any] = {key: value for key, value in summary.items() if key != "maintainer"}
    health = summary.get("health")
    if isinstance(health, dict):
        projected["health"] = {key: value for key, value in health.items() if key not in HEALTH_POPOVER_KEYS}
    maintainer = summary.get("maintainer")
    if isinstance(maintainer, dict):
        # hasConfirmedMaintainer() reads only the count block. Carry every count
        # block that exists, under its own name: the field is mid-rename from
        # `counts` to `healthCounts`, and a card that keeps the wrong one silently
        # loses its confirmed-maintainer byline. Both are small; the bulk of a
        # maintainer record is the people list, which no card reads.
        projected["maintainer"] = {
            key: maintainer[key] for key in MAINTAINER_COUNT_KEYS if isinstance(maintainer.get(key), dict)
        }
    return projected


def project(summary: dict[str, Any], view: str) -> dict[str, Any]:
    """Return `summary` in the requested view."""
    return card_view(summary) if view == VIEW_CARD else summary


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


def summaries_for(
    names: list[str],
    build_summary: SummaryBuilder,
    *,
    refresh_stale: bool = True,
    view: str = VIEW_FULL,
) -> SummaryRead:
    """Return already-materialized local summaries, queueing anything missing or stale.

    This read never builds a summary. Building one costs roughly a dozen
    statements per tool — including writes — so materializing a page's worth of
    cold tools inline meant hundreds of round trips inside a single request,
    holding a write transaction while every other reader waited behind it.

    A name with no materialized row is simply absent from `results`; callers
    treat summaries as additive and render without them, and the queued build
    means the next read has it.
    """
    ordered_names = tuple(dict.fromkeys(names))
    if not ordered_names:
        return SummaryRead(results={}, cache_meta={})

    pending_names: list[str] = []
    now = utcnow()
    with db.session_scope() as s:
        rows = _rows_by_name(s, ordered_names)
        results: dict[str, dict[str, Any]] = {}
        cache_meta: dict[str, dict[str, str]] = {}
        for name in ordered_names:
            row = rows.get(name)
            if row is None:
                cache_meta[name] = {"status": "pending"}
                pending_names.append(name)
                continue
            fresh = _fresh_payload(row, now)
            if fresh is not None:
                payload, cache_meta[name] = fresh
                results[name] = project(payload, view)
                continue
            stale = _stale_payload(row, now)
            if stale is not None:
                payload, cache_meta[name] = stale
                results[name] = project(payload, view)
                pending_names.append(name)
                continue
            # Past stale_until: the body is no longer servable, but the row is
            # still the build target, so rebuild it rather than reporting a hit.
            cache_meta[name] = {"status": "pending"}
            pending_names.append(name)

    if refresh_stale and pending_names:
        queue_refresh(pending_names, build_summary)
    return SummaryRead(results=results, cache_meta=cache_meta)


def refresh(names: list[str], build_summary: SummaryBuilder) -> int:
    """Rebuild and store summaries for the supplied tool names.

    One transaction per tool: a build takes write locks, so batching the whole
    queue into a single transaction would hold them for the length of the batch.
    """
    ordered_names = tuple(dict.fromkeys(names))
    for name in ordered_names:
        now = utcnow()
        with db.session_scope() as s:
            row = s.get(ToolSummaryCache, name)
            _build_and_store(s, tool_name=name, row=row, build_summary=build_summary, now=now)
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
    """Queue one background build for each summary not already being built.

    Bounded: a cold catalog would otherwise queue every tool the moment someone
    opens a card grid. Names dropped here are re-queued by the next read, so the
    cache still converges — just at a rate one worker can absorb.
    """
    with _REFRESH_LOCK:
        room = max(0, MAX_QUEUED_BUILDS - len(_REFRESHING))
        queued = tuple(name for name in dict.fromkeys(names) if name not in _REFRESHING)[:room]
        _REFRESHING.update(queued)
    if queued:
        _EXECUTOR.submit(_refresh_worker, queued, build_summary)
