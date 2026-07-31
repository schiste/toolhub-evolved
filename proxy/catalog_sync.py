# SPDX-License-Identifier: GPL-3.0-or-later
"""Paced, resumable synchronization of the complete official Toolhub catalog."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

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


def listing_url(page: int, page_size: int) -> str:
    """Return the stable source URL recorded for one catalog page."""
    return f"{toolhub.base_url()}{CATALOG_PATH}?{urlencode({'page': page, 'page_size': page_size})}"


def _bounded_pages(value: int) -> int:
    return max(1, min(MAX_PAGES_PER_RUN, value))


def _bounded_page_size(value: int) -> int:
    return max(1, min(MAX_PAGE_SIZE, value))


def _bounded_interval(value: float) -> float:
    return max(DEFAULT_MIN_INTERVAL_SECONDS, min(MAX_MIN_INTERVAL_SECONDS, value))


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


def run(
    *,
    pages_per_run: int = DEFAULT_PAGES_PER_RUN,
    page_size: int = DEFAULT_PAGE_SIZE,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, int | bool]:
    """Fetch a bounded page window and persist the resumable catalog cursor."""
    pages_limit = _bounded_pages(pages_per_run)
    effective_page_size = _bounded_page_size(page_size)
    interval = _bounded_interval(min_interval_seconds)
    _mark_started()
    result: dict[str, int | bool] = {
        "pages": 0,
        "records": 0,
        "next_page": 1,
        "completed": False,
    }
    try:
        with db.session_scope() as s:
            state = s.get(ToolCatalogSyncState, STATE_KEY)
            current_page = max(1, state.next_page if state else 1)
        for offset in range(pages_limit):
            if offset:
                sleep_fn(interval)
            rows, has_next = listing_page(current_page, effective_page_size)
            if not rows and has_next:
                raise _empty_page_error(current_page)
            inserted = canonical_tools.upsert_records(
                rows,
                source_url=listing_url(current_page, effective_page_size),
                detail=False,
            )
            next_page = current_page + 1 if has_next else 1
            completed = not has_next
            with db.session_scope() as s:
                state = _state(s)
                state.next_page = next_page
                state.pages_fetched += 1
                state.records_seen += inserted
                state.status = STATUS_IDLE
                state.last_success_at = utcnow()
                state.last_error = None
                if completed:
                    state.cycles_completed += 1
                    state.last_completed_at = utcnow()
                state.source = SOURCE_OFFICIAL
                state.sync_status = SYNC_OFFICIAL
            result["pages"] = int(result["pages"]) + 1
            result["records"] = int(result["records"]) + inserted
            result["next_page"] = next_page
            result["completed"] = completed
            if completed:
                break
            current_page = next_page
    except (CatalogSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError) as exc:
        _mark_error(exc)
        raise
    return result


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
    summary = run(
        pages_per_run=args.pages,
        page_size=args.page_size,
        min_interval_seconds=args.min_interval,
    )
    sys.stdout.write(
        "catalog-sync: "
        f"pages={summary['pages']} records={summary['records']} "
        f"next_page={summary['next_page']} completed={summary['completed']}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
