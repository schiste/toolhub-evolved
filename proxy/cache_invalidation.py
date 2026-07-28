# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled shared API cache invalidation from Toolhub recent changes.

This job keeps recent-change polling out of user-facing /api/* requests. It
polls official Toolhub's recent feed, stores the latest marker in ToolsDB via
backend.api_cache, invalidates only affected anonymous GET cache rows, then
prewarms high-traffic rows so the next user request can hit shared cache.
"""

import os
import sys
from typing import Any

import requests

import cache_prewarm
from backend import DEFAULT_DB_URL, api_cache, db

UPSTREAM = "https://toolhub.wikimedia.org"
RECENT_INVALIDATION_URL = f"{UPSTREAM}/api/recent/?page_size=50"
UA = "toolhub-evolved-cache-invalidator/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
TIMEOUT = 10


def fetch_recent_change_rows(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Fetch Toolhub's newest recent rows for cache invalidation only."""
    http = session or requests.Session()
    try:
        upstream = http.get(
            RECENT_INVALIDATION_URL,
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException:
        return []
    if not upstream.ok:
        return []
    try:
        payload = upstream.json()
    except ValueError:
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    return [row for row in results if isinstance(row, dict)]


def run_once(session: requests.Session | None = None) -> int:
    """Poll recent changes once and invalidate affected shared cache rows."""
    return api_cache.maybe_poll_recent_changes(lambda: fetch_recent_change_rows(session))


def main() -> int:
    """Jobs-framework entrypoint: invalidate changed rows, then prewarm hot reads."""
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    removed = run_once()
    sys.stdout.write(f"cache-invalidation: {removed} rows invalidated\n")
    sys.stdout.write(f"{cache_prewarm.run_once().log_line()}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
