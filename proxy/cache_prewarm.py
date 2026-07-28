# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled shared API cache prewarming for high-traffic Toolhub reads."""

import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from backend import DEFAULT_DB_URL, api_cache, db, recent_owners

DEFAULT_UPSTREAM = "https://toolhub.wikimedia.org"
UA = "toolhub-evolved-cache-prewarm/1.0 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"
TIMEOUT = 20
MAX_UPSTREAM_BYTES = 10 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
HTTP_NOT_MODIFIED = 304
CACHEABLE_MIN_STATUS = 200
CACHEABLE_MAX_STATUS = 300
REFRESH_AHEAD_SECONDS = 70
TRANSIENT_UPSTREAM_STATUSES = {502, 503, 504}
DEFAULT_SEARCH_QUERIES = ("wikidata", "commons", "toolforge", "template", "bot")


@dataclass(frozen=True)
class HotEndpoint:
    """One anonymous Toolhub API endpoint shape that should stay warm."""

    path: str
    params: tuple[tuple[str, str], ...] = ()


@dataclass
class PrewarmSummary:
    """Counters for one prewarm pass."""

    endpoints: int = 0
    warmed: int = 0
    revalidated: int = 0
    skipped: int = 0
    failed: int = 0
    owners: int = 0
    owner_cached: int = 0

    def observe(self, result: str) -> None:
        """Record one endpoint prewarm result."""
        self.endpoints += 1
        if result == "warmed":
            self.warmed += 1
        elif result == "revalidated":
            self.revalidated += 1
        elif result == "skipped":
            self.skipped += 1
        else:
            self.failed += 1

    def log_line(self) -> str:
        """Return the concise operator log line for Toolforge job output."""
        return (
            "cache-prewarm: "
            f"warmed={self.warmed} revalidated={self.revalidated} "
            f"skipped={self.skipped} failed={self.failed} endpoints={self.endpoints} "
            f"owners={self.owners} owner_cached={self.owner_cached}"
        )


def upstream_base() -> str:
    """Return the official Toolhub base URL, overridable for tests/staging."""
    return os.environ.get("TOOLHUB_API_BASE", DEFAULT_UPSTREAM).rstrip("/")


def configured_search_queries() -> tuple[str, ...]:
    """Return search terms to keep warm, configurable without a deploy."""
    raw = os.environ.get("TOOLHUB_CACHE_PREWARM_SEARCH_QUERIES")
    if raw is None:
        return DEFAULT_SEARCH_QUERIES
    return tuple(term for term in (part.strip() for part in raw.split(",")) if term)


def hot_endpoints() -> tuple[HotEndpoint, ...]:
    """Return the Toolhub API endpoints that should stay hot in shared cache."""
    endpoints = [
        HotEndpoint("/api/ui/home/"),
        HotEndpoint("/api/recent/", (("page_size", "30"),)),
        HotEndpoint("/api/schema/"),
        HotEndpoint("/api/lists/", (("page_size", "30"),)),
        HotEndpoint("/api/lists/", (("featured", "true"), ("page_size", "6"))),
        HotEndpoint("/api/search/tools/", (("page", "1"), ("page_size", "24"))),
        HotEndpoint("/api/search/tools/", (("ordering", "-modified_date"), ("page_size", "5"))),
    ]
    endpoints.extend(
        HotEndpoint("/api/search/tools/", (("q", query), ("page", "1"), ("page_size", "24")))
        for query in configured_search_queries()
    )

    seen: set[str] = set()
    unique: list[HotEndpoint] = []
    for endpoint in endpoints:
        key = f"{endpoint.path}?{urlencode(endpoint.params)}"
        if key not in seen:
            seen.add(key)
            unique.append(endpoint)
    return tuple(unique)


def url_for_endpoint(endpoint: HotEndpoint) -> str:
    """Build the official Toolhub URL for one hot endpoint."""
    query = urlencode(endpoint.params)
    return f"{upstream_base()}{endpoint.path}{('?' + query) if query else ''}"


def _cached_for_revalidation(url: str) -> api_cache.CachedResponse | None:
    """Return any usable cached row that can provide conditional GET headers."""
    cached = api_cache.get(url)
    return cached if cached is not None else api_cache.get(url, allow_stale=True)


def _read_capped_body(resp: requests.Response) -> bytes | None:
    """Read a response body under the same size cap as the user-facing proxy."""
    body = bytearray()
    for chunk in resp.iter_content(CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > MAX_UPSTREAM_BYTES:
            resp.close()
            return None
    return bytes(body)


def _headers(stale: api_cache.CachedResponse | None) -> dict[str, str]:
    """Return anonymous prewarm headers, including validators when available."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if stale and stale.etag:
        headers["If-None-Match"] = stale.etag
    if stale and stale.last_modified:
        headers["If-Modified-Since"] = stale.last_modified
    return headers


def prewarm_endpoint(endpoint: HotEndpoint, *, session: requests.Session | None = None) -> str:
    """Prewarm one endpoint; return warmed, revalidated, skipped, or failed."""
    url = url_for_endpoint(endpoint)
    if not api_cache.needs_refresh(url, refresh_ahead_seconds=REFRESH_AHEAD_SECONDS):
        return "skipped"

    stale = _cached_for_revalidation(url)
    http = session or requests.Session()
    try:
        upstream = http.get(
            url,
            headers=_headers(stale),
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as exc:
        api_cache.mark_failure(url, str(exc))
        return "failed"

    if upstream.status_code == HTTP_NOT_MODIFIED and stale is not None:
        api_cache.refresh(url)
        return "revalidated"

    body = _read_capped_body(upstream)
    if body is None:
        api_cache.mark_failure(url, "upstream response too large")
        return "failed"

    if CACHEABLE_MIN_STATUS <= upstream.status_code < CACHEABLE_MAX_STATUS:
        api_cache.put_success(
            url,
            api_cache.CacheableResponse(
                status=upstream.status_code,
                content_type=upstream.headers.get("content-type", "application/json"),
                body=body,
                etag=upstream.headers.get("etag"),
                last_modified=upstream.headers.get("last-modified"),
            ),
        )
        return "warmed"

    if upstream.status_code in TRANSIENT_UPSTREAM_STATUSES:
        api_cache.mark_failure(url, f"HTTP {upstream.status_code}")
    return "failed"


def _recent_rows_from_cache() -> list[dict[str, object]]:
    """Read the warmed recent feed from shared cache for owner prewarming."""
    url = url_for_endpoint(HotEndpoint("/api/recent/", (("page_size", "30"),)))
    cached = api_cache.get(url) or api_cache.get(url, allow_stale=True)
    if cached is None:
        return []
    try:
        payload = json.loads(cached.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    return [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []


def _recent_tool_names(rows: list[dict[str, object]]) -> list[str]:
    """Return unique tool names from the current recent feed."""
    return recent_owners.clean_tool_names(
        [row.get("content_id") for row in rows if row.get("content_type") == "tool"],
        limit=recent_owners.OWNER_MAX_NAMES,
    )


def prewarm_recent_owners() -> tuple[int, int]:
    """Prewarm owner-by-tool rows for tools currently visible on /recent."""
    names = _recent_tool_names(_recent_rows_from_cache())
    if not names:
        return 0, 0
    payload = recent_owners.resolve_owners(names)
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    cached = sum(1 for item in meta.values() if isinstance(item, dict) and item.get("cached"))
    return len(names), cached


def run_once(
    session: requests.Session | None = None, *, endpoints: Iterable[HotEndpoint] | None = None
) -> PrewarmSummary:
    """Prewarm the configured hot endpoint set once."""
    summary = PrewarmSummary()
    for endpoint in endpoints or hot_endpoints():
        summary.observe(prewarm_endpoint(endpoint, session=session))
    summary.owners, summary.owner_cached = prewarm_recent_owners()
    return summary


def main() -> int:
    """Jobs-framework entrypoint: configure DB, prewarm hot Toolhub reads, report."""
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    sys.stdout.write(f"{run_once().log_line()}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - job entrypoint, exercised via main() in tests
    raise SystemExit(main())
