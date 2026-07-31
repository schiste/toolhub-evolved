# SPDX-License-Identifier: GPL-3.0-or-later
"""Paced, resumable synchronization of the official Toolhub catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

import requests

from backend import DEFAULT_DB_URL, canonical_tools, db, toolhub
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
MAX_RECENT_DETAILS_PER_RUN = 20
RECONCILE_INTERVAL = timedelta(hours=12)
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"
CATALOG_PATH = "/api/tools/"


class CatalogSyncError(RuntimeError):
    """Raised when an official catalog page cannot be consumed safely."""


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


def _state(s: Any) -> ToolCatalogSyncState:  # noqa: ANN401 - SQLAlchemy session
    row = s.get(ToolCatalogSyncState, STATE_KEY)
    if row is None:
        row = ToolCatalogSyncState(key=STATE_KEY)
        s.add(row)
    return row


def listing_page(page: int, page_size: int) -> tuple[list[dict[str, Any]], bool]:
    """Fetch and validate one paginated official catalog response."""
    payload = toolhub.public_api_get(CATALOG_PATH, params={"page": page, "page_size": page_size})
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        return rows, False
    if not isinstance(payload, dict):
        raise _invalid_catalog_shape_error()
    raw_rows = payload.get("results")
    if not isinstance(raw_rows, list):
        raise _missing_results_error()
    rows = [row for row in raw_rows if isinstance(row, dict)]
    return rows, bool(payload.get("next"))


def recent_page() -> list[dict[str, Any]]:
    """Fetch the newest official changes for incremental catalog updates."""
    payload = toolhub.public_api_get(RECENT_PATH, params={"page_size": RECENT_PAGE_SIZE})
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise _missing_results_error()
    return [row for row in payload["results"] if isinstance(row, dict)]


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


def _new_recent_rows(rows: list[dict[str, Any]], last_marker: str | None) -> list[dict[str, Any]]:
    if last_marker is None:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if _marker(row) == last_marker:
            break
        out.append(row)
    return out


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
        rows, has_next = listing_page(current_page, page_size)
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
    rows = recent_page()
    latest = _latest_marker(rows)
    with db.session_scope() as s:
        state = _state(s)
        previous = state.recent_latest_marker
        pending = list(state.recent_pending_tools or [])
    if latest is None:
        return {"recent_tools": 0, "recent_errors": 0}
    if previous is None:
        with db.session_scope() as s:
            state = _state(s)
            state.recent_latest_marker = latest
            state.recent_last_at = utcnow()
            state.status = STATUS_IDLE
        return {"recent_tools": 0, "recent_errors": 0}
    names = _dedupe_names(pending + _tool_names(_new_recent_rows(rows, previous)))
    successful = errors = 0
    remaining: list[str] = []
    for index, name in enumerate(names[:MAX_RECENT_DETAILS_PER_RUN]):
        if index:
            sleep_fn(interval)
        try:
            payload = toolhub.public_api_get(f"/api/tools/{quote(name, safe='')}/")
            if not isinstance(payload, dict):
                raise _invalid_detail_error(name)
            successful += canonical_tools.upsert_records([payload], source_url=detail_url(name), detail=True)
        except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError):
            errors += 1
            remaining.append(name)
    remaining.extend(names[MAX_RECENT_DETAILS_PER_RUN:])
    with db.session_scope() as s:
        state = _state(s)
        state.recent_latest_marker = latest
        state.recent_pending_tools = _dedupe_names(remaining)
        state.recent_last_at = utcnow()
        state.last_success_at = utcnow()
        state.status = STATUS_IDLE
        state.source = SOURCE_OFFICIAL
        state.sync_status = SYNC_OFFICIAL
    return {"recent_tools": successful, "recent_errors": errors}


def _reconcile_if_due(page_size: int) -> dict[str, int]:
    now = utcnow()
    with db.session_scope() as s:
        state = _state(s)
        if state.reconcile_last_at is not None and now - state.reconcile_last_at < RECONCILE_INTERVAL:
            return {"reconcile_pages": 0, "reconcile_records": 0}
        page = max(1, state.reconcile_next_page)
    rows, has_next = listing_page(page, page_size)
    if not rows and has_next:
        raise _empty_page_error(page)
    inserted = _store_page(page, page_size, rows, has_next=has_next, reconcile=True)
    return {"reconcile_pages": 1, "reconcile_records": inserted}


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
        recent = _recent_updates(interval, sleep_fn)
        reconcile = _reconcile_if_due(effective_page_size)
    except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError) as exc:
        _mark_error(exc)
        raise
    else:
        return {"phase": "steady", "pages": 0, "records": 0, "next_page": 1, "completed": True, **recent, **reconcile}


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
    args = parser.parse_args(argv)
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    summary = run(pages_per_run=args.pages, page_size=args.page_size, min_interval_seconds=args.min_interval)
    sys.stdout.write("catalog-sync: " + " ".join(f"{key}={value}" for key, value in summary.items()) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
