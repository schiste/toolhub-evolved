# SPDX-License-Identifier: GPL-3.0-or-later
"""Resumable synchronization of official Toolhub account registrations."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import requests
from sqlalchemy import delete, func, select

from backend import DEFAULT_DB_URL, db, people_index, toolhub
from backend.models import ToolhubAccountProjection, ToolhubAccountSyncState, utcnow
from backend.sync import SOURCE_OFFICIAL, SYNC_OFFICIAL, clean_error

if TYPE_CHECKING:
    from collections.abc import Callable

STATE_KEY = "official_accounts"
ACCOUNT_PATH = "/api/users/"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 100
DEFAULT_PAGES_PER_RUN = 10
MAX_PAGES_PER_RUN = 50
DEFAULT_MIN_INTERVAL_SECONDS = 1.0
MAX_MIN_INTERVAL_SECONDS = 60.0
MAX_COMPLETE_PAGES = 100
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"
LOCK_NAME = "toolhub-evolved-account-sync"


class AccountSyncError(RuntimeError):
    """Raised when an official account page cannot be mirrored safely."""


def _account_error(message: str) -> AccountSyncError:
    return AccountSyncError(message)


def _invalid_payload_error() -> AccountSyncError:
    return _account_error("Toolhub account response was not an object")


def _missing_results_error() -> AccountSyncError:
    return _account_error("Toolhub account response did not contain a results list")


def _invalid_count_error() -> AccountSyncError:
    return _account_error("Toolhub account response did not contain a valid count")


def _invalid_rows_error() -> AccountSyncError:
    return _account_error("Toolhub account response contained invalid rows")


def _empty_page_error(page: int) -> AccountSyncError:
    return _account_error(f"Toolhub returned an empty account page {page} with a next page")


def _invalid_account_error() -> AccountSyncError:
    return _account_error("Toolhub account row lacked an id or username")


def _cursor_error() -> AccountSyncError:
    return _account_error("Toolhub account sync cursor changed during the run")


def _page_limit_error() -> AccountSyncError:
    return _account_error(f"Toolhub account sync exceeded {MAX_COMPLETE_PAGES} pages without completing")


def _state(s: Any) -> ToolhubAccountSyncState:  # noqa: ANN401 - SQLAlchemy session
    row = s.get(ToolhubAccountSyncState, STATE_KEY)
    if row is None:
        row = ToolhubAccountSyncState(
            key=STATE_KEY,
            next_page=1,
            active_generation=0,
            cycles_completed=0,
            pages_fetched=0,
            records_seen=0,
            cycle_records_seen=0,
            total_count=0,
            status=STATUS_IDLE,
        )
        s.add(row)
    return row


def _bounded_pages(value: int) -> int:
    return max(1, min(MAX_PAGES_PER_RUN, value))


def _bounded_page_size(value: int) -> int:
    return max(1, min(MAX_PAGE_SIZE, value))


def _bounded_interval(value: float) -> float:
    return max(DEFAULT_MIN_INTERVAL_SECONDS, min(MAX_MIN_INTERVAL_SECONDS, value))


def listing_url(page: int, page_size: int) -> str:
    """Return the official page URL recorded as projection provenance."""
    query = urlencode({"ordering": "id", "page": page, "page_size": page_size})
    return f"{toolhub.base_url()}{ACCOUNT_PATH}?{query}"


def listing_page(page: int, page_size: int) -> tuple[list[dict[str, Any]], bool, int]:
    """Fetch and validate one stable-id-ordered official account page."""
    payload = toolhub.public_api_get(
        ACCOUNT_PATH,
        params={"ordering": "id", "page": page, "page_size": page_size},
    )
    if not isinstance(payload, dict):
        raise _invalid_payload_error()
    raw_rows = payload.get("results")
    if not isinstance(raw_rows, list):
        raise _missing_results_error()
    try:
        total = int(payload.get("count"))
    except (TypeError, ValueError) as exc:
        raise _invalid_count_error() from exc
    if total < 0 or any(not isinstance(row, dict) for row in raw_rows):
        raise _invalid_rows_error()
    if not raw_rows and payload.get("next"):
        raise _empty_page_error(page)
    return raw_rows, bool(payload.get("next")), total


def _parse_datetime(value: Any) -> datetime | None:  # noqa: ANN401 - official JSON
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _wikimedia_registered(row: dict[str, Any]) -> str:
    social = row.get("social_auth")
    if not isinstance(social, list):
        return ""
    for item in social:
        if isinstance(item, dict) and item.get("provider") == "wikimedia":
            return str(item.get("registered") or "").strip()[:32]
    return ""


def _normalized_account(row: dict[str, Any]) -> dict[str, Any]:
    toolhub_user_id = str(row.get("id") or "").strip()[:64]
    username = str(row.get("username") or "").strip()[:255]
    if not toolhub_user_id or not username:
        raise _invalid_account_error()
    raw_groups = row.get("groups")
    groups = sorted(
        {
            str(group).strip()[:255]
            for group in (raw_groups if isinstance(raw_groups, list) else [])
            if str(group).strip()
        },
        key=str.casefold,
    )
    return {
        "toolhub_user_id": toolhub_user_id,
        "username": username,
        "normalized_username": username.casefold(),
        "groups": groups,
        "groups_search": "\n" + "\n".join(group.casefold() for group in groups) + "\n" if groups else "",
        "wikimedia_global_user_id": toolhub.wikimedia_global_user_id(row) or None,
        "wikimedia_registered_at": _wikimedia_registered(row),
        "date_joined": _parse_datetime(row.get("date_joined")),
    }


def _begin_cycle() -> tuple[int, int]:
    with db.session_scope() as s:
        state = _state(s)
        if state.cycle_started_at is None:
            state.active_generation += 1
            state.cycle_started_at = utcnow()
            state.cycle_records_seen = 0
            state.next_page = 1
        state.status = STATUS_RUNNING
        state.last_started_at = utcnow()
        state.last_error = None
        state.source = SOURCE_OFFICIAL
        state.sync_status = SYNC_OFFICIAL
        return max(1, state.next_page), state.active_generation


def _mark_error(error: BaseException) -> None:
    with db.session_scope() as s:
        state = _state(s)
        state.status = STATUS_ERROR
        state.last_error = clean_error(str(error))
        state.source = SOURCE_OFFICIAL
        state.sync_status = SYNC_OFFICIAL


def _store_page(  # noqa: C901, PLR0913, PLR0915 - explicit page transaction contract
    page: int,
    page_size: int,
    generation: int,
    rows: list[dict[str, Any]],
    *,
    has_next: bool,
    total_count: int,
) -> tuple[int, bool]:
    """Upsert one generation page and prune old rows only after full validation."""
    normalized = [_normalized_account(row) for row in rows]
    now = utcnow()
    mismatch = ""
    with db.session_scope() as s:
        state = _state(s)
        if state.active_generation != generation or state.next_page != page or state.cycle_started_at is None:
            raise _cursor_error()
        existing = {
            row.toolhub_user_id: row
            for row in s.execute(
                select(ToolhubAccountProjection).where(
                    ToolhubAccountProjection.toolhub_user_id.in_(
                        {item["toolhub_user_id"] for item in normalized} or {""}
                    )
                )
            ).scalars()
        }
        source_url = listing_url(page, page_size)
        for item in normalized:
            account = existing.get(item["toolhub_user_id"])
            created = account is None
            if account is None:
                account = ToolhubAccountProjection(toolhub_user_id=item["toolhub_user_id"], first_seen_at=now)
                s.add(account)
            identity_changed = (
                created
                or account.username != item["username"]
                or (account.wikimedia_global_user_id != item["wikimedia_global_user_id"])
            )
            projection_changed = created or any(
                getattr(account, field) != value for field, value in item.items() if field != "toolhub_user_id"
            )
            for field, value in item.items():
                if field != "toolhub_user_id":
                    setattr(account, field, value)
            account.source_url = source_url
            account.generation = generation
            account.source = SOURCE_OFFICIAL
            account.sync_status = SYNC_OFFICIAL
            account.last_seen_at = now
            if projection_changed:
                account.updated_at = now
            if identity_changed:
                people_index.ensure_official_account_person(
                    s,
                    toolhub_user_id=item["toolhub_user_id"],
                    username=item["username"],
                    wikimedia_global_user_id=item["wikimedia_global_user_id"] or "",
                    checked_at=now,
                )
        state.pages_fetched += 1
        state.records_seen += len(normalized)
        state.cycle_records_seen += len(normalized)
        state.total_count = total_count
        state.last_success_at = now
        state.last_error = None
        completed = not has_next
        if completed:
            s.flush()
            distinct_seen = int(
                s.scalar(
                    select(func.count())
                    .select_from(ToolhubAccountProjection)
                    .where(ToolhubAccountProjection.generation == generation)
                )
                or 0
            )
            if distinct_seen != total_count:
                mismatch = (
                    f"Toolhub account generation saw {distinct_seen} distinct rows "
                    f"but the official count was {total_count}; restarting without pruning"
                )
                state.next_page = 1
                state.cycle_started_at = None
                state.cycle_records_seen = 0
                state.status = STATUS_ERROR
                state.last_error = mismatch
            else:
                s.execute(delete(ToolhubAccountProjection).where(ToolhubAccountProjection.generation != generation))
                state.next_page = 1
                state.cycle_started_at = None
                state.cycle_records_seen = 0
                state.cycles_completed += 1
                state.last_completed_at = now
                state.status = STATUS_IDLE
        else:
            state.next_page = page + 1
            state.status = STATUS_RUNNING
    if mismatch:
        raise _account_error(mismatch)
    return len(normalized), completed


def run(
    *,
    pages_per_run: int = DEFAULT_PAGES_PER_RUN,
    page_size: int = DEFAULT_PAGE_SIZE,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, int | bool | str]:
    """Advance one bounded account synchronization generation."""
    page_limit = _bounded_pages(pages_per_run)
    effective_page_size = _bounded_page_size(page_size)
    interval = _bounded_interval(min_interval_seconds)
    with db.advisory_lock(LOCK_NAME) as acquired:
        if not acquired:
            return {"status": "locked", "pages": 0, "records": 0, "completed": False}
        page, generation = _begin_cycle()
        pages = records = 0
        try:
            for offset in range(page_limit):
                if offset:
                    sleep_fn(interval)
                rows, has_next, total_count = listing_page(page, effective_page_size)
                stored, completed = _store_page(
                    page,
                    effective_page_size,
                    generation,
                    rows,
                    has_next=has_next,
                    total_count=total_count,
                )
                pages += 1
                records += stored
                if completed:
                    return {
                        "status": STATUS_IDLE,
                        "pages": pages,
                        "records": records,
                        "next_page": 1,
                        "generation": generation,
                        "completed": True,
                    }
                page += 1
        except (AccountSyncError, OSError, requests.RequestException, toolhub.ToolhubAPIError) as exc:
            _mark_error(exc)
            raise
        return {
            "status": STATUS_RUNNING,
            "pages": pages,
            "records": records,
            "next_page": page,
            "generation": generation,
            "completed": False,
        }


def run_complete(
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, int | bool | str]:
    """Finish the active generation for deploys and manual repair runs."""
    pages = records = 0
    while pages < MAX_COMPLETE_PAGES:
        summary = run(
            pages_per_run=min(MAX_PAGES_PER_RUN, MAX_COMPLETE_PAGES - pages),
            page_size=page_size,
            min_interval_seconds=min_interval_seconds,
            sleep_fn=sleep_fn,
        )
        pages += int(summary.get("pages") or 0)
        records += int(summary.get("records") or 0)
        if summary.get("status") == "locked":
            return {**summary, "pages": pages, "records": records}
        if summary.get("completed"):
            return {**summary, "pages": pages, "records": records}
    raise _page_limit_error()


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
    parser.add_argument("--complete", action="store_true", help="finish a complete safe generation")
    parser.add_argument("--pages", type=int, default=_env_int("ACCOUNT_SYNC_PAGES", DEFAULT_PAGES_PER_RUN))
    parser.add_argument("--page-size", type=int, default=_env_int("ACCOUNT_SYNC_PAGE_SIZE", DEFAULT_PAGE_SIZE))
    parser.add_argument(
        "--min-interval",
        type=float,
        default=_env_float("ACCOUNT_SYNC_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS),
    )
    args = parser.parse_args(argv)
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    runner = run_complete if args.complete else run
    kwargs = {"page_size": args.page_size, "min_interval_seconds": args.min_interval}
    if not args.complete:
        kwargs["pages_per_run"] = args.pages
    summary = runner(**kwargs)
    sys.stdout.write("account-sync: " + " ".join(f"{key}={value}" for key, value in summary.items()) + "\n")
    if args.complete and not summary.get("completed"):
        sys.stderr.write("account-sync: complete generation was not obtained\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
