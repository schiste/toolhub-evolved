# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge webservice for Toolhub Evolved.

Serves the static single-page app, reverse-proxies read-only GET requests to
the live Toolhub API at the same origin (so the browser can read live catalog
data without hitting CORS — the upstream API sends no CORS headers), and hosts
the site's own backend (backend/): Toolhub OAuth sign-in, the /v1 overlay API,
and the official Toolhub write bridge over the project-specific database that
complements the live catalog.

The /api proxy is NOT an open proxy: requests only ever go to UPSTREAM/api/...
and only GET. Official writes go through /v1/toolhub/* with a stored per-user
OAuth grant; Evolved-only overlay writes land in the local database via /v1.
"""

from pathlib import Path

import requests
from flask import Flask, Response, request, send_from_directory

import backend
from backend import api_cache

HERE = Path(__file__).resolve().parent
_SOURCE_DIR = (HERE.parent / "public_html").resolve()
_DIST_DIR = (HERE.parent / "dist").resolve()
UPSTREAM = "https://toolhub.wikimedia.org"


def _static_root() -> Path:
    """Serve the minified `dist/` build when present (production), else raw source."""
    return _DIST_DIR if _DIST_DIR.is_dir() else _SOURCE_DIR


UA = "toolhub-evolved/0.1 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"

# The proxy buffers the upstream body before relaying it; cap that buffer so a
# (hypothetical) runaway upstream response can't exhaust the webservice's memory.
# Toolhub JSON pages are a few hundred KiB at most, so 10 MiB is generous slack.
_MAX_UPSTREAM_BYTES = 10 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_UPSTREAM_CACHE = "public, max-age=300"
_UPSTREAM_STALE_CACHE = "public, max-age=30"
_VERSIONED_STATIC_CACHE = "public, max-age=31536000, immutable"
_REVALIDATED_STATIC_CACHE = "no-cache"
_HTTP_NOT_MODIFIED = 304
_TRANSIENT_UPSTREAM_STATUSES = {502, 503, 504}

app = Flask(__name__, static_folder=None)
backend.register(app)

# One pooled HTTPS connection set to the upstream, reused across requests so each
# proxied call skips a fresh TCP + TLS handshake to toolhub.wikimedia.org
# (~100-200ms saved per request — the SPA makes several per page).
_SESSION = requests.Session()


def _cached_api_response(hit: api_cache.CachedResponse, state: str) -> Response:
    """Build a proxy response from a detached cache hit."""
    resp = Response(hit.body, status=hit.status, content_type=hit.content_type)
    resp.headers["Cache-Control"] = _UPSTREAM_STALE_CACHE if hit.stale else _UPSTREAM_CACHE
    resp.headers["X-Toolhub-Evolved-Cache"] = state
    if hit.stale:
        resp.headers["Warning"] = '110 - "Response is stale"'
    return resp


def _upstream_headers(stale: api_cache.CachedResponse | None = None) -> dict[str, str]:
    """Headers for anonymous Toolhub API reads, optionally conditional."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if stale and stale.etag:
        headers["If-None-Match"] = stale.etag
    if stale and stale.last_modified:
        headers["If-Modified-Since"] = stale.last_modified
    return headers


def _oversize_response() -> Response:
    """Return the fixed JSON error for an oversized upstream body."""
    return Response('{"error":"upstream response too large"}', status=502, content_type="application/json")


def _unavailable_response() -> Response:
    """Return the fixed JSON error for an unavailable upstream."""
    return Response('{"error":"upstream unavailable"}', status=502, content_type="application/json")


def _fetch_upstream(
    url: str, stale: api_cache.CachedResponse | None
) -> tuple[requests.Response | None, bytes | None, Response | None]:
    """Fetch upstream under the proxy's no-redirect and response-size limits."""
    try:
        # allow_redirects=False: this is a fixed-target read-only proxy, so it must
        # never chase a 3xx the upstream returns (an upstream open redirect would
        # otherwise become SSRF to whatever host the Location names). A 3xx is
        # relayed through verbatim instead. stream=True so the body is read under
        # the size cap below rather than fully buffered by requests up front. The
        # pooled _SESSION reuses the TCP/TLS connection to the upstream.
        upstream = _SESSION.get(
            url,
            headers=_upstream_headers(stale),
            timeout=20,
            allow_redirects=False,
            stream=True,
        )
        body = bytearray()
        for chunk in upstream.iter_content(_CHUNK_BYTES):
            body.extend(chunk)
            if len(body) > _MAX_UPSTREAM_BYTES:
                upstream.close()
                return None, None, _oversize_response()
    except requests.RequestException as exc:
        api_cache.mark_failure(url, str(exc))
        if stale is not None:
            return None, None, _cached_api_response(stale, "stale")
        return None, None, _unavailable_response()
    return upstream, bytes(body), None


def _freshened_cached_response(stale: api_cache.CachedResponse) -> Response:
    """Return a stale body as fresh after upstream replied 304."""
    return _cached_api_response(
        api_cache.CachedResponse(
            status=stale.status,
            content_type=stale.content_type,
            body=stale.body,
            stale=False,
            etag=stale.etag,
            last_modified=stale.last_modified,
        ),
        "revalidated",
    )


def _relay_upstream_response(
    url: str, upstream: requests.Response, payload: bytes, stale: api_cache.CachedResponse | None
) -> Response:
    """Persist/relay an upstream response according to the anonymous read-cache contract."""
    content_type = upstream.headers.get("content-type", "application/json")
    if upstream.status_code == _HTTP_NOT_MODIFIED and stale is not None:
        api_cache.refresh(url)
        return _freshened_cached_response(stale)
    # Only cache successful payloads. Caching a transient 4xx/5xx would serve the
    # error for 5 minutes and defeat the SPA's own retry of 502/503/504 (api.js).
    if upstream.ok:
        api_cache.put_success(
            url,
            api_cache.CacheableResponse(
                status=upstream.status_code,
                content_type=content_type,
                body=payload,
                etag=upstream.headers.get("etag"),
                last_modified=upstream.headers.get("last-modified"),
            ),
        )
    elif stale is not None and upstream.status_code in _TRANSIENT_UPSTREAM_STATUSES:
        api_cache.mark_failure(url, f"HTTP {upstream.status_code}")
        return _cached_api_response(stale, "stale")
    resp = Response(payload, status=upstream.status_code, content_type=content_type)
    resp.headers["Cache-Control"] = _UPSTREAM_CACHE if upstream.ok else "no-store"
    resp.headers["X-Toolhub-Evolved-Cache"] = "miss"
    return resp


# CSP hash of the one inline theme script in index.html (kept inline so the theme
# resolves before first paint — no FOUC). tests/proxy/test_app.py recomputes this
# from index.html and fails if it drifts, so the value can never silently rot.
# script-src is strict (no 'unsafe-inline'); style-src allows inline because the
# UI emits data-driven inline styles (avatar colours, progress widths, graph node
# colours). img-src allows any https origin: tool icons are arbitrary remote
# images. The browser only ever fetches same-origin (/api/ is proxied
# server-side), hence connect-src 'self'.
_THEME_SCRIPT_HASH = "sha256-XASlFDDB4Ati9OFy/+a7zp7h86hBsK6RJ9H/0Db17GA="
_CSP = (
    "default-src 'self'; "
    f"script-src 'self' '{_THEME_SCRIPT_HASH}'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https: data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


@app.after_request
def set_security_headers(resp: Response) -> Response:
    """Apply baseline security headers (CSP, nosniff, HSTS, framing, …) to every response."""
    for header, value in _SECURITY_HEADERS.items():
        resp.headers.setdefault(header, value)
    return resp


# Accept write verbs at the routing layer (not just GET) so the view itself can
# answer them with a JSON 405 — the explicit read-only contract — instead of
# Flask's generic HTML 405. The SPA only ever issues GETs.
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@app.route("/api/", defaults={"path": ""}, methods=_PROXY_METHODS)
@app.route("/api/<path:path>", methods=_PROXY_METHODS)
def api_proxy(path: str) -> Response:
    """Read-only reverse proxy to the live Toolhub API (same-origin for the SPA)."""
    if request.method != "GET":
        return Response('{"error":"read-only proxy"}', status=405, content_type="application/json")
    qs = request.query_string.decode()
    url = UPSTREAM + "/api/" + path + (("?" + qs) if qs else "")
    cached = api_cache.get(url)
    if cached is not None:
        return _cached_api_response(cached, "hit")
    stale = api_cache.get(url, allow_stale=True)
    upstream, payload, early = _fetch_upstream(url, stale)
    if early is not None:
        return early
    if upstream is None or payload is None:
        raise RuntimeError
    return _relay_upstream_response(url, upstream, payload, stale)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_files(path: str) -> Response:
    """Serve a static file if it exists, else index.html (clean-routed SPA).

    The production dist build stamps JS/CSS URLs with ?v=<build>, so those
    immutable assets can stay in the browser cache across visits. Unstamped
    assets and the SPA shell keep ETag revalidation to avoid stale module graphs.
    """
    root = _static_root()
    candidate = (root / path).resolve()
    if path and root in candidate.parents and candidate.is_file():
        resp = send_from_directory(root, path)
        resp.headers["Cache-Control"] = _VERSIONED_STATIC_CACHE if request.args.get("v") else _REVALIDATED_STATIC_CACHE
        return resp
    resp = send_from_directory(root, "index.html")
    resp.headers["Cache-Control"] = _REVALIDATED_STATIC_CACHE
    return resp


if __name__ == "__main__":  # pragma: no cover - local dev entrypoint, not exercised by tests
    app.run(host="127.0.0.1", port=8000)
