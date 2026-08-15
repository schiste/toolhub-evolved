# SPDX-License-Identifier: GPL-3.0-or-later
"""Paced, resumable synchronization of the official Toolhub catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

import requests

from backend import canonical_tools, catalog_facets, db, digests, graph_enrichment, job_runner, toolhub
from backend.models import ToolCatalogSyncState, utcnow
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL, clean_error

if TYPE_CHECKING:
    from collections.abc import Callable

STATE_KEY = "official_catalog"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 100
DEFAULT_PAGES_PER_RUN = 5
MAX_PAGES_PER_RUN = 20
DEFAULT_MIN_INTERVAL_SECONDS = 3.0
MAX_MIN_INTERVAL_SECONDS = 60.0
RECENT_PATH = "/api/recent/"
RECENT_PAGE_SIZE = 50
MAX_RECENT_PAGES_PER_RUN = 20
MAX_RECENT_DETAILS_PER_RUN = 20
MAX_GRAPH_DETAILS_PER_RUN = 20
MAX_COMPLETE_PAGES = 100
DEFAULT_SNAPSHOT_CONSISTENCY_RETRIES = 3
RECONCILE_INTERVAL = timedelta(hours=12)
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"
CATALOG_PATH = "/api/tools/"


class CatalogSyncError(RuntimeError):
    """Raised when an official catalog page cannot be consumed safely."""


class SnapshotConsistencyError(CatalogSyncError):
    """A full snapshot changed shape and must restart from page one."""


class RecentCursorLostError(CatalogSyncError):
    """The saved recent-event marker fell outside Toolhub's retained window."""

    def __init__(self, message: str, *, rows: list[dict[str, Any]], latest_marker: str | None) -> None:
        """Retain the observable event tail and its newest safe recovery anchor."""
        super().__init__(message)
        self.rows = rows
        self.latest_marker = latest_marker


@dataclass(frozen=True)
class RecentScan:
    """One safe, resumable slice between two immutable recent-event markers."""

    rows: list[dict[str, Any]]
    latest_marker: str | None
    boundary_marker: str | None
    page: int
    pages_fetched: int
    complete: bool


def _catalog_error(message: str) -> CatalogSyncError:
    return CatalogSyncError(message)


def _invalid_catalog_shape_error() -> CatalogSyncError:
    return _catalog_error("Toolhub catalog response was not an object or list")


def _missing_results_error() -> CatalogSyncError:
    return _catalog_error("Toolhub catalog response did not contain a results list")


def _empty_page_error(page: int) -> CatalogSyncError:
    return _catalog_error(f"Toolhub returned an empty page {page} with a next page")


def _invalid_detail_error(name: str) -> CatalogSyncError:
    return _catalog_error(f"Toolhub returned an invalid detail for {name}")


def _invalid_count_error() -> CatalogSyncError:
    return _catalog_error("Toolhub catalog response did not contain a valid count")


def _changed_count_error(before: int, after: int) -> CatalogSyncError:
    return SnapshotConsistencyError(f"Toolhub catalog count changed during snapshot: {before} to {after}")


def _page_limit_error() -> CatalogSyncError:
    return SnapshotConsistencyError(f"Toolhub catalog exceeded the {MAX_COMPLETE_PAGES}-page safety limit")


def _state(s: Any) -> ToolCatalogSyncState:  # noqa: ANN401 - SQLAlchemy session
    row = s.get(ToolCatalogSyncState, STATE_KEY)
    if row is None:
        row = ToolCatalogSyncState(key=STATE_KEY)
        s.add(row)
    return row


def listing_page(page: int, page_size: int) -> tuple[list[dict[str, Any]], bool, int]:
    """Fetch and validate one fresh paginated official catalog response.

    Catalog pages are reconciliation input, not ordinary browsing responses.
    Reading independently cached pages can combine different catalog moments
    and makes a complete deletion-safe snapshot impossible to validate.
    """
    payload = toolhub.public_api_get(
        CATALOG_PATH,
        params={"page": page, "page_size": page_size},
        read_cache=False,
    )
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        return rows, False, len(rows)
    if not isinstance(payload, dict):
        raise _invalid_catalog_shape_error()
    raw_rows = payload.get("results")
    if not isinstance(raw_rows, list):
        raise _missing_results_error()
    rows = [row for row in raw_rows if isinstance(row, dict)]
    try:
        total_count = int(payload.get("count"))
    except (TypeError, ValueError):
        raise _invalid_count_error() from None
    if total_count <= 0:
        raise _invalid_count_error()
    return rows, bool(payload.get("next")), total_count


def recent_page(page: int = 1) -> tuple[list[dict[str, Any]], bool]:
    """Fetch one validated page of official incremental catalog updates."""
    payload = toolhub.public_api_get(
        RECENT_PATH,
        params={"page": page, "page_size": RECENT_PAGE_SIZE},
        read_cache=False,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise _missing_results_error()
    return [row for row in payload["results"] if isinstance(row, dict)], bool(payload.get("next"))


def listing_url(page: int, page_size: int) -> str:
    """Return the stable source URL recorded for one catalog page."""
    return f"{toolhub.base_url()}{CATALOG_PATH}?{urlencode({'page': page, 'page_size': page_size})}"


def detail_url(tool_name: str) -> str:
    """Return the stable source URL recorded for one changed tool detail."""
    return f"{toolhub.base_url()}/api/tools/{quote(tool_name, safe='')}/"


def _bounded_pages(value: int) -> int:
    return max(1, min(MAX_PAGES_PER_RUN, value))


def _bounded_page_size(value: int) -> int:
    return max(1, min(MAX_PAGE_SIZE, value))


def _bounded_interval(value: float) -> float:
    return max(DEFAULT_MIN_INTERVAL_SECONDS, min(MAX_MIN_INTERVAL_SECONDS, value))


def _marker(row: dict[str, Any]) -> str | None:
    timestamp = row.get("timestamp")
    ident = row.get("id")
    if timestamp is None and ident is None:
        return None
    return json.dumps(
        {"id": "" if ident is None else str(ident), "timestamp": "" if timestamp is None else str(timestamp)},
        separators=(",", ":"),
        sort_keys=True,
    )


def _latest_marker(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        marker = _marker(row)
        if marker is not None:
            return marker
    return None


def _recent_rows_since(
    last_marker: str | None,
    *,
    resume_page: int = 1,
    scan_latest_marker: str | None = None,
    boundary_marker: str | None = None,
) -> RecentScan:
    """Read one checkpointed slice without advancing across an unproven gap."""
    collected: list[dict[str, Any]] = []
    latest = scan_latest_marker
    boundary = boundary_marker
    seeking = boundary_marker
    first_page = max(1, resume_page - int(bool(boundary_marker)))
    last_page = first_page
    for offset in range(MAX_RECENT_PAGES_PER_RUN):
        page = first_page + offset
        last_page = page
        rows, has_next = recent_page(page)
        if latest is None and page == 1:
            latest = _latest_marker(rows)
            if last_marker is None or latest is None:
                return RecentScan(
                    rows=[],
                    latest_marker=latest,
                    boundary_marker=None,
                    page=page,
                    pages_fetched=offset + 1,
                    complete=True,
                )
        start = 0
        if seeking is not None:
            matched = next((index for index, row in enumerate(rows) if _marker(row) == seeking), None)
            if matched is None:
                if not has_next:
                    message = "Toolhub recent scan boundary disappeared before it could be resumed"
                    raise RecentCursorLostError(message, rows=collected, latest_marker=latest)
                continue
            start = matched + 1
            seeking = None
        for row in rows[start:]:
            if _marker(row) == last_marker:
                return RecentScan(
                    rows=collected,
                    latest_marker=latest,
                    boundary_marker=boundary,
                    page=page,
                    pages_fetched=offset + 1,
                    complete=True,
                )
            collected.append(row)
            boundary = _marker(row) or boundary
        if not has_next:
            message = "Toolhub recent cursor disappeared before it could be reconciled"
            raise RecentCursorLostError(message, rows=collected, latest_marker=latest)
    return RecentScan(
        rows=collected,
        latest_marker=latest,
        boundary_marker=boundary,
        page=last_page,
        pages_fetched=MAX_RECENT_PAGES_PER_RUN,
        complete=False,
    )


def _tool_names(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("content_type") or "").lower() != "tool":
            continue
        name = str(row.get("content_id") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _dedupe_names(names: list[str]) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))


def _reset_snapshot_cursor(state: ToolCatalogSyncState) -> int:
    """Reset staged snapshot progress and return its generation for cleanup."""
    generation = int(state.snapshot_generation or 0)
    state.snapshot_next_page = 1
    state.snapshot_expected_count = 0
    state.snapshot_started_at = None
    return generation


def _cancel_obsolete_cursor_recovery(state: ToolCatalogSyncState) -> int:
    """Reset a superseded snapshot and return its staging generation."""
    if not state.recent_cursor_recovery_required:
        return 0
    generation = _reset_snapshot_cursor(state)
    state.recent_cursor_recovery_required = False
    return generation


def _store_recent_progress(scan: RecentScan, remaining: list[str]) -> int:
    """Persist recent-scan progress and retire any superseded recovery."""
    with db.session_scope() as s:
        state = _state(s)
        abandoned_snapshot_generation = _cancel_obsolete_cursor_recovery(state)
        if scan.complete:
            state.recent_latest_marker = scan.latest_marker
            state.recent_scan_page = 1
            state.recent_scan_latest_marker = None
            state.recent_scan_boundary_marker = None
        else:
            state.recent_scan_page = scan.page
            state.recent_scan_latest_marker = scan.latest_marker
            state.recent_scan_boundary_marker = scan.boundary_marker
        state.recent_pending_tools = _dedupe_names(remaining)
        state.recent_last_at = utcnow()
        state.last_success_at = utcnow()
        state.status = STATUS_IDLE
        state.source = SOURCE_OFFICIAL
        state.sync_status = SYNC_OFFICIAL
        return abandoned_snapshot_generation


def _mark_started() -> None:
    with db.session_scope() as s:
        row = _state(s)
        row.status = STATUS_RUNNING
        row.last_started_at = utcnow()
        row.last_error = None
        row.source = SOURCE_OFFICIAL
        row.sync_status = SYNC_OFFICIAL


def _mark_error(error: BaseException) -> None:
    with db.session_scope() as s:
        row = _state(s)
        row.status = STATUS_ERROR
        row.last_error = clean_error(str(error))
        row.source = SOURCE_OFFICIAL
        row.sync_status = SYNC_OFFICIAL


def _prepare_recent_cursor_recovery(error: RecentCursorLostError) -> None:
    """Persist a pre-snapshot anchor without discarding still-visible events."""
    digests.capture_recent_rows(error.rows)
    abandoned_snapshot_generation = 0
    with db.session_scope() as s:
        state = _state(s)
        if not state.recent_cursor_recovery_required and state.snapshot_started_at is not None:
            abandoned_snapshot_generation = _reset_snapshot_cursor(state)
        state.recent_pending_tools = _dedupe_names([*(state.recent_pending_tools or []), *_tool_names(error.rows)])
        state.recent_scan_page = 1
        state.recent_scan_latest_marker = error.latest_marker
        state.recent_scan_boundary_marker = None
        state.recent_cursor_recovery_required = True
        state.status = STATUS_ERROR
        state.last_error = clean_error(str(error))
    if abandoned_snapshot_generation:
        canonical_tools.discard_snapshot_stage(abandoned_snapshot_generation)


def _store_page(page: int, page_size: int, rows: list[dict[str, Any]], *, has_next: bool, reconcile: bool) -> int:
    """Upsert one page and advance either the initial or reconciliation cursor."""
    inserted = canonical_tools.upsert_records(rows, source_url=listing_url(page, page_size), detail=False)
    next_page = page + 1 if has_next else 1
    with db.session_scope() as s:
        state = _state(s)
        state.pages_fetched += 1
        state.records_seen += inserted
        state.last_success_at = utcnow()
        state.last_error = None
        if reconcile:
            state.reconcile_next_page = next_page
            state.reconcile_last_at = utcnow()
            if not has_next:
                state.reconcile_cycles_completed += 1
        else:
            state.next_page = next_page
            if not has_next:
                state.cycles_completed += 1
                state.last_completed_at = utcnow()
        state.status = STATUS_IDLE
        state.source = SOURCE_OFFICIAL
        state.sync_status = SYNC_OFFICIAL
    graph_enrichment.refresh_tool_names([str(row.get("name") or "") for row in rows])
    return inserted


def _initial_backfill(
    *, pages_limit: int, page_size: int, interval: float, sleep_fn: Callable[[float], None]
) -> dict[str, int | bool]:
    with db.session_scope() as s:
        state = s.get(ToolCatalogSyncState, STATE_KEY)
        current_page = max(1, state.next_page if state else 1)
    pages = records = 0
    completed = False
    for offset in range(pages_limit):
        if offset:
            sleep_fn(interval)
        rows, has_next, _total_count = listing_page(current_page, page_size)
        if not rows and has_next:
            raise _empty_page_error(current_page)
        records += _store_page(current_page, page_size, rows, has_next=has_next, reconcile=False)
        pages += 1
        completed = not has_next
        if completed:
            break
        current_page += 1
    return {"pages": pages, "records": records, "next_page": 1 if completed else current_page, "completed": completed}


def _recent_updates(interval: float, sleep_fn: Callable[[float], None]) -> dict[str, int]:
    with db.session_scope() as s:
        state = _state(s)
        previous = state.recent_latest_marker
        pending = list(state.recent_pending_tools or [])
        scan_page = state.recent_scan_page
        scan_latest = state.recent_scan_latest_marker
        scan_boundary = state.recent_scan_boundary_marker
    scan = _recent_rows_since(
        previous,
        resume_page=scan_page,
        scan_latest_marker=scan_latest,
        boundary_marker=scan_boundary,
    )
    if scan.latest_marker is None:
        return {
            "recent_tools": 0,
            "recent_errors": 0,
            "recent_scan_pages": scan.pages_fetched,
            "recent_scan_complete": 1,
        }
    if previous is None:
        with db.session_scope() as s:
            state = _state(s)
            state.recent_latest_marker = scan.latest_marker
            state.recent_last_at = utcnow()
            state.status = STATUS_IDLE
        return {
            "recent_tools": 0,
            "recent_errors": 0,
            "recent_scan_pages": scan.pages_fetched,
            "recent_scan_complete": 1,
        }
    digests.capture_recent_rows(scan.rows)
    names = _dedupe_names(pending + _tool_names(scan.rows))
    successful = errors = 0
    refreshed_names: list[str] = []
    remaining: list[str] = []
    for index, name in enumerate(names[:MAX_RECENT_DETAILS_PER_RUN]):
        if index:
            sleep_fn(interval)
        try:
            payload = toolhub.public_api_get(f"/api/tools/{quote(name, safe='')}/")
            if not isinstance(payload, dict):
                raise _invalid_detail_error(name)
            successful += canonical_tools.upsert_records([payload], source_url=detail_url(name), detail=True)
            refreshed_names.append(name)
        except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError):
            errors += 1
            remaining.append(name)
    remaining.extend(names[MAX_RECENT_DETAILS_PER_RUN:])
    abandoned_snapshot_generation = _store_recent_progress(scan, remaining)
    if abandoned_snapshot_generation:
        canonical_tools.discard_snapshot_stage(abandoned_snapshot_generation)
    graph_enrichment.refresh_tool_names(refreshed_names)
    return {
        "recent_tools": successful,
        "recent_errors": errors,
        "recent_scan_pages": scan.pages_fetched,
        "recent_scan_complete": int(scan.complete),
    }


def _graph_detail_candidates(cursor: str | None, pending: list[str]) -> list[str]:
    rows = canonical_tools.records()
    ranked = sorted(
        (
            -sum(
                not row["record"].get(field)
                for field in (
                    "for_wikis",
                    "technology_used",
                    "tasks",
                    "audiences",
                    "available_ui_languages",
                    "tool_type",
                )
            ),
            str(row.get("toolName") or ""),
        )
        for row in rows
        if isinstance(row.get("record"), dict)
        and (row["record"].get("keywords") or row["record"].get("tasks"))
        and not canonical_tools.is_tool_detail_url(str(row.get("sourceUrl") or ""))
    )
    names = [name for _missing, name in ranked if name]
    if not names:
        return _dedupe_names(pending)[:MAX_GRAPH_DETAILS_PER_RUN]
    start = names.index(cursor) + 1 if cursor in names else 0
    rotated = names[start:] + names[:start]
    return _dedupe_names([*pending, *rotated])[:MAX_GRAPH_DETAILS_PER_RUN]


def _hydrate_graph_details(interval: float, sleep_fn: Callable[[float], None]) -> dict[str, int]:
    with db.session_scope() as s:
        state = _state(s)
        cursor = state.detail_hydration_cursor
        pending = list(state.detail_hydration_pending_tools or [])
    names = _graph_detail_candidates(cursor, pending)
    successful = errors = 0
    refreshed_names: list[str] = []
    remaining = [name for name in pending if name not in names]
    for index, name in enumerate(names):
        if index:
            sleep_fn(interval)
        try:
            payload = toolhub.public_api_get(f"/api/tools/{quote(name, safe='')}/")
            if not isinstance(payload, dict):
                raise _invalid_detail_error(name)
            successful += canonical_tools.upsert_records([payload], source_url=detail_url(name), detail=True)
            refreshed_names.append(name)
        except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError):
            errors += 1
            remaining.append(name)
        with db.session_scope() as s:
            state = _state(s)
            state.detail_hydration_cursor = name
            state.detail_hydration_pending_tools = _dedupe_names(remaining)
    graph_enrichment.refresh_tool_names(refreshed_names)
    return {"hydrated_tools": successful, "hydration_errors": errors}


def _reconcile_if_due(page_size: int) -> dict[str, int]:
    now = utcnow()
    with db.session_scope() as s:
        state = _state(s)
        if state.reconcile_last_at is not None and now - state.reconcile_last_at < RECONCILE_INTERVAL:
            return {"reconcile_pages": 0, "reconcile_records": 0}
        page = max(1, state.reconcile_next_page)
    rows, has_next, _total_count = listing_page(page, page_size)
    if not rows and has_next:
        raise _empty_page_error(page)
    inserted = _store_page(page, page_size, rows, has_next=has_next, reconcile=True)
    return {"reconcile_pages": 1, "reconcile_records": inserted}


def _begin_snapshot() -> tuple[int, int, int]:
    """Start or resume one complete catalog generation."""
    with db.session_scope() as s:
        state = _state(s)
        if state.snapshot_started_at is None:
            state.snapshot_generation = int(state.snapshot_generation or 0) + 1
            state.snapshot_next_page = 1
            state.snapshot_expected_count = 0
            state.snapshot_started_at = utcnow()
        state.status = STATUS_RUNNING
        state.last_started_at = utcnow()
        state.last_error = None
        return (
            int(state.snapshot_next_page or 1),
            int(state.snapshot_generation or 1),
            int(state.snapshot_expected_count or 0),
        )


def _restart_snapshot() -> None:
    """Discard only the incomplete cursor; last-known-good rows stay intact."""
    with db.session_scope() as s:
        state = _state(s)
        generation = _reset_snapshot_cursor(state)
    canonical_tools.discard_snapshot_stage(generation)


def _store_snapshot_page(
    rows: list[dict[str, Any]], *, page: int, page_size: int, generation: int, expected_count: int
) -> int:
    """Persist one validated page and its resumable cursor."""
    stored = canonical_tools.stage_snapshot_records(
        rows,
        source_url=listing_url(page, page_size),
        generation=generation,
    )
    with db.session_scope() as s:
        state = _state(s)
        state.snapshot_expected_count = expected_count
        state.snapshot_next_page = page + 1
        state.pages_fetched += 1
        state.records_seen += stored
        state.last_success_at = utcnow()
    return stored


def _publish_snapshot(generation: int, expected_count: int) -> list[str]:
    """Atomically prune a validated generation and publish its retirements."""
    from backend.people_reconcile import enqueue_tool_names_in_session  # noqa: PLC0415

    with db.session_scope() as s:
        try:
            retired = canonical_tools.publish_snapshot_stage(s, generation, expected_count)
        except ValueError as exc:
            raise SnapshotConsistencyError(str(exc)) from exc
        enqueue_tool_names_in_session(s, retired, reason="canonical_retired")
        state = _state(s)
        state.snapshot_next_page = 1
        state.snapshot_expected_count = 0
        state.snapshot_started_at = None
        state.cycles_completed += 1
        state.last_completed_at = utcnow()
        state.status = STATUS_IDLE
        state.last_success_at = utcnow()
        state.last_error = None
        if state.recent_cursor_recovery_required:
            state.recent_latest_marker = state.recent_scan_latest_marker
            state.recent_scan_page = 1
            state.recent_scan_latest_marker = None
            state.recent_scan_boundary_marker = None
            state.recent_cursor_recovery_required = False
        catalog_facets.mark_dirty(s)
    from backend import api_cache  # noqa: PLC0415 - avoid backend import cycle

    for name in retired:
        api_cache.invalidate_tool(name)
    catalog_facets.rebuild_global_payload()
    return retired


def _run_complete_snapshot(
    effective_page_size: int,
    interval: float,
    sleep_fn: Callable[[float], None],
) -> dict[str, int | bool | str]:
    """Run one count-stable snapshot attempt from its current cursor."""
    page, generation, expected_count = _begin_snapshot()
    pages = records = 0
    while pages < MAX_COMPLETE_PAGES:
        if pages:
            sleep_fn(interval)
        rows, has_next, total_count = listing_page(page, effective_page_size)
        if not rows and has_next:
            raise _empty_page_error(page)
        if expected_count and total_count != expected_count:
            raise _changed_count_error(expected_count, total_count)
        expected_count = expected_count or total_count
        stored = _store_snapshot_page(
            rows,
            page=page,
            page_size=effective_page_size,
            generation=generation,
            expected_count=expected_count,
        )
        pages += 1
        records += stored
        if has_next:
            page += 1
            continue

        retired = _publish_snapshot(generation, expected_count)
        return {
            "phase": "complete",
            "pages": pages,
            "records": records,
            "retired": len(retired),
            "generation": generation,
            "completed": True,
        }
    raise _page_limit_error()


def _recent_complete_snapshot(max_age_seconds: int) -> dict[str, int | bool | str] | None:
    """Return a reusable completed snapshot summary when it is still fresh."""
    if max_age_seconds <= 0:
        return None
    with db.session_scope() as s:
        state = _state(s)
        recent_cutoff = utcnow() - timedelta(seconds=max_age_seconds)
        if (
            state.snapshot_started_at is not None
            or state.last_completed_at is None
            or state.last_completed_at < recent_cutoff
        ):
            return None
        return {
            "phase": "complete_cached",
            "pages": 0,
            "records": 0,
            "retired": 0,
            "generation": int(state.snapshot_generation or 0),
            "completed": True,
        }


def run_complete(
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    max_age_seconds: int = 0,
    sleep_fn: Callable[[float], None] = time.sleep,
    consistency_retries: int = DEFAULT_SNAPSHOT_CONSISTENCY_RETRIES,
) -> dict[str, int | bool | str]:
    """Publish one resumable full snapshot and retire confirmed missing tools."""
    cached = _recent_complete_snapshot(max_age_seconds)
    if cached is not None:
        return cached
    effective_page_size = _bounded_page_size(page_size)
    interval = _bounded_interval(min_interval_seconds)
    retries = max(0, min(int(consistency_retries), DEFAULT_SNAPSHOT_CONSISTENCY_RETRIES))
    attempt = 0
    while True:
        try:
            return _run_complete_snapshot(effective_page_size, interval, sleep_fn)
        except SnapshotConsistencyError as exc:
            _restart_snapshot()
            if attempt >= retries:
                _mark_error(exc)
                raise
            attempt += 1
            sleep_fn(interval)
        except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError) as exc:
            _mark_error(exc)
            raise


def run(
    *,
    pages_per_run: int = DEFAULT_PAGES_PER_RUN,
    page_size: int = DEFAULT_PAGE_SIZE,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, int | bool | str]:
    """Run initial backfill, then recent updates plus a slow reconciliation page."""
    pages_limit = _bounded_pages(pages_per_run)
    effective_page_size = _bounded_page_size(page_size)
    interval = _bounded_interval(min_interval_seconds)
    _mark_started()
    try:
        with db.session_scope() as s:
            state = s.get(ToolCatalogSyncState, STATE_KEY)
            initial_complete = bool(state and state.cycles_completed > 0)
        if not initial_complete:
            backfill = _initial_backfill(
                pages_limit=pages_limit, page_size=effective_page_size, interval=interval, sleep_fn=sleep_fn
            )
            return {"phase": "backfill", **backfill}
        try:
            recent = _recent_updates(interval, sleep_fn)
        except RecentCursorLostError as exc:
            _prepare_recent_cursor_recovery(exc)
            snapshot = run_complete(
                page_size=effective_page_size,
                min_interval_seconds=interval,
                sleep_fn=sleep_fn,
            )
            return {**snapshot, "phase": "cursor_recovery", "recent_events_preserved": len(exc.rows)}
        hydration = _hydrate_graph_details(interval, sleep_fn)
        reconcile = _reconcile_if_due(effective_page_size)
    except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError) as exc:
        _mark_error(exc)
        raise
    else:
        return {
            "phase": "steady",
            "pages": 0,
            "records": 0,
            "next_page": 1,
            "completed": True,
            **recent,
            **hydration,
            **reconcile,
        }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=_env_int("CATALOG_SYNC_PAGES", DEFAULT_PAGES_PER_RUN))
    parser.add_argument("--page-size", type=int, default=_env_int("CATALOG_SYNC_PAGE_SIZE", DEFAULT_PAGE_SIZE))
    parser.add_argument(
        "--min-interval",
        type=float,
        default=_env_float("CATALOG_SYNC_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS),
    )
    parser.add_argument(
        "--complete", action="store_true", help="finish a validated full snapshot and prune retired tools"
    )
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=0,
        help="with --complete, reuse a snapshot completed within this many seconds",
    )
    args = parser.parse_args(argv)
    job_runner.configure()
    with db.advisory_lock("toolhub-evolved:catalog-sync") as acquired:
        if not acquired:
            summary = {"status": "locked", "completed": False}
        elif args.complete:
            summary = run_complete(
                page_size=args.page_size,
                min_interval_seconds=args.min_interval,
                max_age_seconds=max(0, args.max_age_seconds),
            )
        else:
            summary = run(pages_per_run=args.pages, page_size=args.page_size, min_interval_seconds=args.min_interval)
    sys.stdout.write("catalog-sync: " + " ".join(f"{key}={value}" for key, value in summary.items()) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
