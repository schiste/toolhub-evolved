# SPDX-License-Identifier: GPL-3.0-or-later
"""Paced, resumable backfill of public Toolforge maintainer evidence."""

from __future__ import annotations

import argparse
import os
import time
from typing import TYPE_CHECKING, Any

import requests

from backend import canonical_tools, db, job_runner, maintainer_index
from backend.author_claims import (
    TOOLFORGE_CLAIM_TTL,
    ToolforgeMaintainerProvider,
    parse_toolsadmin_maintainer_entries,
    toolforge_names_from_toolhub_tool,
)
from backend.models import MaintainerBackfillState, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable


STATE_KEY = "toolforge_toolsadmin"
DEFAULT_LIMIT = 60
MAX_LIMIT = 100
DEFAULT_MIN_INTERVAL_SECONDS = 3.0
MAX_MIN_INTERVAL_SECONDS = 60.0
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400


def _state(s: Any) -> MaintainerBackfillState:  # noqa: ANN401 - SQLAlchemy session
    row = s.get(MaintainerBackfillState, STATE_KEY)
    if row is None:
        row = MaintainerBackfillState(key=STATE_KEY)
        s.add(row)
    return row


def _bounded_limit(value: int) -> int:
    return max(1, min(MAX_LIMIT, int(value or DEFAULT_LIMIT)))


def _bounded_interval(value: float) -> float:
    return max(DEFAULT_MIN_INTERVAL_SECONDS, min(MAX_MIN_INTERVAL_SECONDS, float(value)))


def _candidates() -> list[tuple[str, dict[str, Any], list[str]]]:
    """Return cached canonical tools that map deterministically to Toolforge accounts."""
    rows: list[tuple[str, dict[str, Any], list[str]]] = []
    for item in canonical_tools.records():
        name = str(item.get("toolName") or "").strip()
        record = item.get("record")
        if not name or not isinstance(record, dict):
            continue
        toolforge_names = toolforge_names_from_toolhub_tool(name, record)
        if toolforge_names:
            rows.append((name, record, toolforge_names))
    return sorted(rows, key=lambda item: item[0])


def _batch(
    rows: list[tuple[str, dict[str, Any], list[str]]],
    cursor: str | None,
    limit: int,
) -> tuple[list[tuple[str, dict[str, Any], list[str]]], bool]:
    if not rows:
        return [], True
    names = [row[0] for row in rows]
    start = names.index(cursor) + 1 if cursor in names else 0
    selected = rows[start : start + limit]
    return selected, start + len(selected) >= len(rows)


def _fetch_pages(
    provider: ToolforgeMaintainerProvider,
    toolforge_names: list[str],
    *,
    sleep_fn: Callable[[float], None],
    request_count: int,
) -> tuple[list[tuple[str, list, str]], bool, int]:
    """Fetch all account pages for one tool; return success and request count."""
    pages: list[tuple[str, list, str]] = []
    for toolforge_name in toolforge_names:
        if request_count:
            sleep_fn(DEFAULT_MIN_INTERVAL_SECONDS)
        request_count += 1
        evidence_url = provider.evidence_url(toolforge_name)
        try:
            status, body = provider.fetcher(toolforge_name)
        except requests.RequestException:
            return pages, False, request_count
        if status == HTTP_NOT_FOUND:
            continue
        if status >= HTTP_BAD_REQUEST:
            return pages, False, request_count
        pages.append((toolforge_name, parse_toolsadmin_maintainer_entries(body), evidence_url))
    return pages, True, request_count


def run(
    *,
    limit: int = DEFAULT_LIMIT,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
    provider: ToolforgeMaintainerProvider | None = None,
) -> dict[str, int | bool | str]:
    """Process one bounded cursor window and checkpoint every tool."""
    effective_limit = _bounded_limit(limit)
    interval = _bounded_interval(min_interval_seconds)
    provider = provider or ToolforgeMaintainerProvider()
    rows = _candidates()
    with db.session_scope() as s:
        state = _state(s)
        cursor = state.next_tool_name
        state.status = "running"
        state.last_started_at = utcnow()
        state.last_error = None
    batch, cycle_complete = _batch(rows, cursor, effective_limit)
    checked = found = failed = 0
    request_count = 0
    for index, (tool_name, _record, toolforge_names) in enumerate(batch):
        pages, success, request_count = _fetch_pages(
            provider,
            toolforge_names,
            sleep_fn=lambda seconds: sleep_fn(max(interval, seconds)),
            request_count=request_count,
        )

        # Loop values are bound as defaults so the closure records the tool it
        # was built for, not whatever the loop reached by the time it runs.
        def record(
            tool_name: str = tool_name,
            index: int = index,
            pages: list = pages,
            *,
            success: bool = success,
        ) -> int:
            with db.session_scope() as s:
                state = _state(s)
                edge_count = 0
                if success:
                    edge_count = len(
                        maintainer_index.replace_toolforge_maintainer_edges(
                            s,
                            tool_name,
                            pages,
                            checked_at=utcnow(),
                            expires_at=utcnow() + TOOLFORGE_CLAIM_TTL,
                        )
                    )
                    state.last_success_at = utcnow()
                state.tools_checked += 1
                state.maintainers_found += edge_count
                state.failed_tools += 0 if success else 1
                state.next_tool_name = None if cycle_complete and index == len(batch) - 1 else tool_name
                state.status = "idle"
                return edge_count

        # Several bounded jobs update the shared identity tables every minute
        # and MariaDB breaks a lock cycle by undoing one of them. Recording one
        # tool's maintainers is idempotent, so losing that race should cost a
        # moment rather than the rest of the sweep.
        found += db.run_with_lock_retry(record)
        checked += 1
        failed += 0 if success else 1
    if not batch:
        with db.session_scope() as s:
            state = _state(s)
            state.next_tool_name = None
            state.status = "idle"
            state.last_success_at = utcnow()
    elif cycle_complete:
        with db.session_scope() as s:
            state = _state(s)
            state.cycles_completed += 1
            state.last_completed_at = utcnow()
            state.next_tool_name = None
    return {
        "tools": checked,
        "maintainers": found,
        "failed": failed,
        "requests": request_count,
        "cycleComplete": cycle_complete,
        "remaining": max(0, len(rows) - checked) if not cycle_complete else 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=int(os.environ.get("MAINTAINER_BACKFILL_LIMIT", DEFAULT_LIMIT)))
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=float(os.environ.get("MAINTAINER_BACKFILL_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)),
    )
    args = parser.parse_args(argv)
    return job_runner.run_job(
        "maintainer-backfill",
        lambda: run(limit=args.limit, min_interval_seconds=args.min_interval_seconds),
        lock=True,
    )


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
