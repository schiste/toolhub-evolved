# SPDX-License-Identifier: GPL-3.0-or-later
"""One composed payload for the landing page.

The homepage needed nine separate reads, and not in parallel: the tool
summaries and the "most listed" ordering both depend on knowing which tools
are on the page, so they could only start after the list and search reads came
back. Measured in a browser, that was ~1.6s of wall clock spent on requests
the server answers in tens of milliseconds — the cost was the round trips and
the dependency between them, not the work.

Everything here already exists locally: the anonymous Toolhub reads sit in the
shared cache, and the summaries in tool_summary_cache. Composing them server
side turns the landing page into one request, and caching the composition
turns the common case into a single cache read.

Nothing is fetched that the proxy would not already have fetched: reads go
through toolhub.public_api_get, which is cache-first.
"""

from __future__ import annotations

import json
from datetime import timedelta
from threading import Lock
from typing import Any

from backend import api_cache, toolhub
from backend.models import utcnow

# Bump when the payload shape changes, so old cached rows are ignored rather
# than deserialized into a shape the client no longer understands.
HOME_CACHE_VERSION = 1
HOME_FRESH_SECONDS = 5 * 60
HOME_STALE_SECONDS = 24 * 60 * 60
# Short per-worker copy in front of the shared cache, so a burst of landing-page
# hits does not each pay a ToolsDB read for the same blob.
HOME_MEMORY_FRESH_SECONDS = 30

FEATURED_LIST_COUNT = 6
RECENT_TOOL_COUNT = 5
# Lists are read only to count memberships ("in N lists", and the ordering of
# the most-listed section). Bounded: the catalog is well under this today, and
# a runaway page count must not turn one landing-page request into a crawl.
MEMBERSHIP_PAGE_SIZE = 50
MEMBERSHIP_MAX_PAGES = 4

_CACHE: dict[str, Any] = {}
_CACHE_LOCK = Lock()


def _cache_url() -> str:
    """Return the stable synthetic URL for the shared cache row."""
    return f"https://toolhub-evolved.local/v1/home/?version={HOME_CACHE_VERSION}"


def _results(payload: object) -> list[dict[str, Any]]:
    """Return the `results` array of a Toolhub collection response."""
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    return [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []


def _tool_names(tools: list[dict[str, Any]]) -> list[str]:
    """Return the distinct tool names in a list of tool records, in order."""
    seen: list[str] = []
    for tool in tools:
        name = str(tool.get("name") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def _total_tools() -> int:
    """Return the catalog size shown in the search placeholder."""
    payload = toolhub.public_api_get("/api/ui/home/")
    total = payload.get("total_tools") if isinstance(payload, dict) else None
    return int(total) if isinstance(total, int) else 0


def _featured_lists() -> list[dict[str, Any]]:
    """Return the administrator-featured lists, with their embedded tools."""
    payload = toolhub.public_api_get("/api/lists/", params={"featured": "true", "page_size": FEATURED_LIST_COUNT})
    return _results(payload)


def _recent_tools() -> list[dict[str, Any]]:
    """Return the most recently modified tools."""
    payload = toolhub.public_api_get(
        "/api/search/tools/", params={"ordering": "-modified_date", "page_size": RECENT_TOOL_COUNT}
    )
    return _results(payload)


def _memberships() -> dict[str, list[dict[str, str]]]:
    """Map each tool name to the public lists containing it.

    This is what the browser used to compute by crawling every page of
    /api/lists/ on a cold visit — two requests of ~1.5s each that also gated
    the most-listed ordering. Server side each page is a cache hit.
    """
    memberships: dict[str, list[dict[str, str]]] = {}
    for page in range(1, MEMBERSHIP_MAX_PAGES + 1):
        payload = toolhub.public_api_get("/api/lists/", params={"page_size": MEMBERSHIP_PAGE_SIZE, "page": page})
        rows = _results(payload)
        for row in rows:
            if row.get("published") is False:
                continue  # count only public/curated lists
            entry = {"id": str(row.get("id") or ""), "title": str(row.get("title") or "Untitled list")}
            for tool in row.get("tools") or []:
                name = str((tool or {}).get("name") or "").strip() if isinstance(tool, dict) else ""
                if name:
                    memberships.setdefault(name, []).append(entry)
        if not rows or not (isinstance(payload, dict) and payload.get("next")):
            break
    return memberships


def build(summaries_for: Any) -> dict[str, Any]:  # noqa: ANN401 - injected to avoid a v1 import cycle
    """Compose the landing-page payload from data the server already holds."""
    lists = _featured_lists()
    recent = _recent_tools()
    featured_tools = [tool for row in lists for tool in (row.get("tools") or []) if isinstance(tool, dict)]
    names = _tool_names([*featured_tools, *recent])
    memberships = _memberships()
    read = summaries_for(names)
    return {
        "totalTools": _total_tools(),
        "lists": lists,
        "recentTools": recent,
        # Keyed by tool name so the client can attach without another round trip.
        "summaries": read.results,
        "endorsements": {name: memberships.get(name, []) for name in names},
        "source": "local",
        "cachePolicy": {
            "summary": "Composed server-side from the shared Toolhub read cache and local summaries.",
        },
    }


def _remember(payload: dict[str, Any]) -> None:
    """Keep a short-lived per-worker copy in front of the shared cache."""
    with _CACHE_LOCK:
        _CACHE["payload"] = payload
        _CACHE["expires_at"] = utcnow() + timedelta(seconds=HOME_MEMORY_FRESH_SECONDS)


def _remembered() -> dict[str, Any] | None:
    """Return the per-worker copy while it is fresh."""
    with _CACHE_LOCK:
        expires_at = _CACHE.get("expires_at")
        if expires_at is None or expires_at <= utcnow():
            return None
        return _CACHE.get("payload")


def _shared(*, allow_stale: bool = False) -> dict[str, Any] | None:
    """Read a composed payload from the shared cache.

    Stale is opt-in, and only used when a rebuild fails. Serving stale freely
    would mean that once this row was written the landing page never refreshed
    again until the row expired a day later.
    """
    cached = api_cache.get(_cache_url(), allow_stale=allow_stale)
    if cached is None:
        return None
    try:
        payload = json.loads(cached.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("lists"), list) else None


def payload(summaries_for: Any) -> dict[str, Any]:  # noqa: ANN401 - injected to avoid a v1 import cycle
    """Return the landing-page payload, composing it only when nothing is cached."""
    remembered = _remembered()
    if remembered is not None:
        return remembered
    shared = _shared()
    if shared is not None:
        _remember(shared)
        return shared
    try:
        composed = build(summaries_for)
    except Exception:
        # Upstream is unreachable or a read failed. A day-old landing page beats
        # an error page, and the shared row is kept for exactly this.
        stale = _shared(allow_stale=True)
        if stale is not None:
            _remember(stale)
            return stale
        raise
    body = json.dumps(composed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    api_cache.put_success(
        _cache_url(),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=body),
        fresh_seconds=HOME_FRESH_SECONDS,
        stale_if_error_seconds=HOME_STALE_SECONDS,
    )
    _remember(composed)
    return composed


def invalidate() -> int:
    """Drop the composed payload after a change that affects the landing page."""
    with _CACHE_LOCK:
        _CACHE.clear()
    return api_cache.invalidate_url(_cache_url())
