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

from concurrent.futures import ThreadPoolExecutor
from gzip import compress as gzip_compress
from mimetypes import guess_type
from pathlib import Path
from threading import Lock
from time import perf_counter

import requests
from flask import Flask, Response, abort, g, request, send_from_directory

import backend
from backend import activity_privacy, api_cache, canonical_tools, security

HERE = Path(__file__).resolve().parent
_SOURCE_DIR = (HERE.parent / "public_html").resolve()
_DIST_DIR = (HERE.parent / "dist").resolve()
UPSTREAM = "https://toolhub.wikimedia.org"


def _static_root() -> Path:
    """Serve the minified `dist/` build when present (production), else raw source."""
    return _DIST_DIR if _DIST_DIR.is_dir() else _SOURCE_DIR


UA = "toolhub-evolved/0.2 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"

# The proxy buffers the upstream body before relaying it; cap that buffer so a
# (hypothetical) runaway upstream response can't exhaust the webservice's memory.
# Toolhub JSON pages are a few hundred KiB at most, so 10 MiB is generous slack.
_MAX_UPSTREAM_BYTES = 10 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
# Types the edge does not already compress, plus text/* handled by prefix.
_COMPRESSIBLE_TYPES = {
    "application/json",
    "application/javascript",
    "application/manifest+json",
    "application/rss+xml",
    "application/xml",
    "image/svg+xml",
}
_COMPRESS_MIN_BYTES = 1400
_COMPRESS_MAX_BYTES = 2 * 1024 * 1024
_COMPRESS_LEVEL = 6
_VERSIONED_STATIC_CACHE = "public, max-age=31536000, immutable"
_REVALIDATED_STATIC_CACHE = "no-cache"
_HTTP_NOT_MODIFIED = 304
_CACHEABLE_MIN_STATUS = 200
# Statuses that carry no body to compress.
_BODILESS_STATUSES = {204, _HTTP_NOT_MODIFIED}
_CACHEABLE_MAX_STATUS = 300
_TRANSIENT_UPSTREAM_STATUSES = {502, 503, 504}
_CACHE_HEADER = "X-Toolhub-Evolved-Cache"
_UPSTREAM_HEADER = "X-Toolhub-Evolved-Upstream"
_SERVER_TIMING_HEADER = "Server-Timing"
_UPSTREAM_TIMEOUT = "timeout"
_UPSTREAM_BACKGROUND = "background"

app = Flask(__name__, static_folder=None)
backend.register(app)

# One pooled HTTPS connection set to the upstream, reused across requests so each
# proxied call skips a fresh TCP + TLS handshake to toolhub.wikimedia.org
# (~100-200ms saved per request — the SPA makes several per page).
_SESSION = requests.Session()
_BACKGROUND_SESSION = requests.Session()
_BACKGROUND_REFRESH = ThreadPoolExecutor(max_workers=1, thread_name_prefix="api-cache-refresh")
_BACKGROUND_REFRESHING: set[str] = set()
_BACKGROUND_REFRESH_LOCK = Lock()


def _server_timing_desc(value: int | str) -> str:
    """Return a quoted Server-Timing desc value with unsafe characters removed."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _timing_metric(name: str, *, desc: int | str | None = None, dur_ms: float | None = None) -> str:
    """Build one Server-Timing metric value."""
    metric = name
    if dur_ms is not None:
        metric += f";dur={max(dur_ms, 0):.1f}"
    if desc is not None:
        metric += f';desc="{_server_timing_desc(desc)}"'
    return metric


def _append_server_timing(resp: Response, *metrics: str) -> None:
    """Append Server-Timing metrics without clobbering earlier instrumentation."""
    values = [metric for metric in metrics if metric]
    if not values:
        return
    existing = resp.headers.get(_SERVER_TIMING_HEADER)
    resp.headers[_SERVER_TIMING_HEADER] = ", ".join([existing, *values] if existing else values)


def _with_proxy_diagnostics(
    resp: Response, *, cache: str, upstream: int | str, upstream_dur_ms: float | None = None
) -> Response:
    """Attach cache/upstream diagnostics to one proxied Toolhub API response."""
    resp.headers[_CACHE_HEADER] = cache
    resp.headers[_UPSTREAM_HEADER] = str(upstream)
    _append_server_timing(
        resp,
        _timing_metric("cache", desc=cache),
        _timing_metric("upstream", desc=upstream, dur_ms=upstream_dur_ms),
    )
    return resp


def _cached_api_response(
    hit: api_cache.CachedResponse,
    state: str,
    *,
    upstream: int | str | None = None,
    upstream_dur_ms: float | None = None,
) -> Response:
    """Build a proxy response from a detached cache hit."""
    body = activity_privacy.sanitize_public_api_payload(hit.url, hit.body)
    resp = Response(body, status=hit.status, content_type=hit.content_type)
    resp.headers["Cache-Control"] = api_cache.cache_control(hit.url, stale=hit.stale)
    _with_proxy_diagnostics(
        resp,
        cache=state,
        upstream=hit.status if upstream is None else upstream,
        upstream_dur_ms=upstream_dur_ms,
    )
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


def _oversize_response(upstream_status: int | str, upstream_dur_ms: float | None = None) -> Response:
    """Return the fixed JSON error for an oversized upstream body."""
    resp = Response('{"error":"upstream response too large"}', status=502, content_type="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return _with_proxy_diagnostics(resp, cache="miss", upstream=upstream_status, upstream_dur_ms=upstream_dur_ms)


def _unavailable_response(upstream_dur_ms: float | None = None) -> Response:
    """Return the fixed JSON error for an unavailable upstream."""
    resp = Response('{"error":"upstream unavailable"}', status=502, content_type="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return _with_proxy_diagnostics(resp, cache="miss", upstream=_UPSTREAM_TIMEOUT, upstream_dur_ms=upstream_dur_ms)


def _fetch_upstream(
    url: str, stale: api_cache.CachedResponse | None, *, session: requests.Session | None = None
) -> tuple[requests.Response | None, bytes | None, Response | None]:
    """Fetch upstream under the proxy's no-redirect and response-size limits."""
    http = session or _SESSION
    started = perf_counter()
    try:
        # allow_redirects=False: this is a fixed-target read-only proxy, so it must
        # never chase a 3xx the upstream returns (an upstream open redirect would
        # otherwise become SSRF to whatever host the Location names). A 3xx is
        # relayed through verbatim instead. stream=True so the body is read under
        # the size cap below rather than fully buffered by requests up front. The
        # pooled _SESSION reuses the TCP/TLS connection to the upstream.
        upstream = http.get(
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
                elapsed_ms = (perf_counter() - started) * 1000
                upstream.close()
                return None, None, _oversize_response(upstream.status_code, elapsed_ms)
    except requests.RequestException as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        api_cache.mark_failure(url, str(exc))
        if stale is not None:
            return (
                None,
                None,
                _cached_api_response(stale, "stale", upstream=_UPSTREAM_TIMEOUT, upstream_dur_ms=elapsed_ms),
            )
        return None, None, _unavailable_response(elapsed_ms)
    # Stashed on the response so the relay helpers can report upstream time without
    # threading it through every signature. Public name: a leading underscore would
    # read as touching requests' internals.
    upstream.toolhub_evolved_upstream_ms = (perf_counter() - started) * 1000
    return upstream, bytes(body), None


def _background_revalidate(url: str, stale: api_cache.CachedResponse) -> None:
    """Refresh one stale shared-cache row without holding up the user request."""
    try:
        upstream, payload, early = _fetch_upstream(url, stale, session=_BACKGROUND_SESSION)
        if early is not None or upstream is None or payload is None:
            return
        _relay_upstream_response(url, upstream, payload, stale)
    except Exception as exc:  # noqa: BLE001 - background refresh must never affect the served response.
        api_cache.mark_failure(url, f"background refresh failed: {exc}")
    finally:
        with _BACKGROUND_REFRESH_LOCK:
            _BACKGROUND_REFRESHING.discard(url)


def _schedule_background_revalidation(url: str, stale: api_cache.CachedResponse) -> None:
    """Queue at most one background refresh for a stale anonymous API response."""
    with _BACKGROUND_REFRESH_LOCK:
        if url in _BACKGROUND_REFRESHING:
            return
        _BACKGROUND_REFRESHING.add(url)
    _BACKGROUND_REFRESH.submit(_background_revalidate, url, stale)


def _relay_upstream_response(
    url: str, upstream: requests.Response, payload: bytes, stale: api_cache.CachedResponse | None
) -> Response:
    """Persist/relay an upstream response according to the anonymous read-cache contract."""
    payload = activity_privacy.sanitize_public_api_payload(url, payload)
    content_type = upstream.headers.get("content-type", "application/json")
    cacheable = _CACHEABLE_MIN_STATUS <= upstream.status_code < _CACHEABLE_MAX_STATUS
    if upstream.status_code == _HTTP_NOT_MODIFIED and stale is not None:
        api_cache.refresh(url)
        return _cached_api_response(
            api_cache.CachedResponse(
                url=stale.url,
                status=stale.status,
                content_type=stale.content_type,
                body=stale.body,
                stale=False,
                etag=stale.etag,
                last_modified=stale.last_modified,
            ),
            "revalidated",
            upstream=upstream.status_code,
            upstream_dur_ms=getattr(upstream, "toolhub_evolved_upstream_ms", None),
        )
    # Only cache successful payloads. Caching a transient 4xx/5xx would serve the
    # error for 5 minutes and defeat the SPA's own retry of 502/503/504 (api.js).
    if cacheable:
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
        canonical_tools.ingest_payload(url, payload)
    elif stale is not None and upstream.status_code in _TRANSIENT_UPSTREAM_STATUSES:
        api_cache.mark_failure(url, f"HTTP {upstream.status_code}")
        return _cached_api_response(
            stale,
            "stale",
            upstream=upstream.status_code,
            upstream_dur_ms=getattr(upstream, "toolhub_evolved_upstream_ms", None),
        )
    resp = Response(payload, status=upstream.status_code, content_type=content_type)
    resp.headers["Cache-Control"] = api_cache.cache_control(url) if cacheable else "no-store"
    return _with_proxy_diagnostics(
        resp,
        cache="miss",
        upstream=upstream.status_code,
        upstream_dur_ms=getattr(upstream, "toolhub_evolved_upstream_ms", None),
    )


# CSP hash of the one inline theme script in index.html (kept inline so the theme
# resolves before first paint — no FOUC). tests/proxy/test_app.py recomputes this
# from index.html and fails if it drifts, so the value can never silently rot.
# script-src is strict (no 'unsafe-inline'); style-src allows inline because the
# UI emits data-driven inline styles (avatar colours, progress widths, graph node
# colours). img-src allows any https origin: tool icons are arbitrary remote
# images. The browser only ever fetches same-origin (/api/ is proxied
# server-side), hence connect-src 'self'.
_THEME_SCRIPT_HASH = "sha256-izz39nmNCIB17JW9URoFiyyhWgVE/RJng4CucQCIOnI="
_CSP = (
    "default-src 'self'; "
    f"script-src 'self' '{_THEME_SCRIPT_HASH}'; "
    "worker-src 'self'; "
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


@app.before_request
def start_request_timing() -> None:
    """Capture total Flask request duration for Server-Timing."""
    g.toolhub_evolved_request_start = perf_counter()


def _compressible(resp: Response) -> bool:
    """Report whether this response is worth gzipping and safe to gzip."""
    if resp.status_code < _CACHEABLE_MIN_STATUS or resp.status_code in _BODILESS_STATUSES:
        return False
    if "Content-Encoding" in resp.headers or "Content-Range" in resp.headers:
        return False
    mimetype = (resp.mimetype or "").lower()
    if mimetype not in _COMPRESSIBLE_TYPES and not mimetype.startswith("text/"):
        return False
    size = resp.content_length
    if size is None:
        return False
    # Below roughly one network packet, compressing costs CPU and saves nothing.
    # Above the cap, refuse rather than pull an arbitrarily large file into
    # memory to compress it — static assets here are tens of KB.
    return _COMPRESS_MIN_BYTES <= size <= _COMPRESS_MAX_BYTES


@app.after_request
def compress_response(resp: Response) -> Response:
    """Gzip text responses the edge leaves uncompressed.

    The ingress compresses text/javascript and text/css but not text/html, so
    the SPA shell went out as 28.7 KB of uncompressed markup — measured at
    852ms of body transfer against a 1.8ms server time. It gzips to 6.8 KB,
    which fits in about one round trip.

    The ETag is deliberately left alone. Flask compares If-None-Match against
    the uncompressed file's tag before this runs, so re-tagging here would make
    every revalidation miss and turn free 304s back into full downloads.
    `Vary` is what keeps caches from handing a gzipped body to a client that
    did not ask for one.
    """
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        return resp
    resp.headers.add("Vary", "Accept-Encoding")
    if not _compressible(resp):
        return resp
    # send_from_directory streams from a file wrapper, which get_data() refuses
    # to touch; the size cap above is what makes buffering it safe.
    resp.direct_passthrough = False
    body = gzip_compress(resp.get_data(), _COMPRESS_LEVEL)
    resp.set_data(body)
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(body))
    return resp


@app.after_request
def set_security_headers(resp: Response) -> Response:
    """Apply baseline security headers (CSP, nosniff, HSTS, framing, …) to every response."""
    for header, value in _SECURITY_HEADERS.items():
        resp.headers.setdefault(header, value)
    started = getattr(g, "toolhub_evolved_request_start", None)
    if started is not None:
        _append_server_timing(resp, _timing_metric("app", dur_ms=(perf_counter() - started) * 1000))
    return resp


# Accept write verbs at the routing layer (not just GET) so the view itself can
# answer them with a JSON 405 — the explicit read-only contract — instead of
# Flask's generic HTML 405. The SPA only ever issues GETs.
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _escapes_api_prefix(path: str) -> bool:
    """Report whether a proxied path could climb out of the upstream /api/ prefix.

    Flask decodes %2e and %2f before the view sees `path`, and `requests`
    normalizes dot segments when it builds the request line. So `..%2f..%2fadmin`
    arrives here as `../../admin` and would go out as a request for /admin. The
    host is fixed by the UPSTREAM prefix, so this is not SSRF — but the proxy is
    documented as read-only access to /api/, and this keeps that true.
    """
    return any(part == ".." for part in path.split("/"))


def _rejected_proxy_request(path: str) -> Response | None:
    """Return the refusal for a proxied request that must not reach upstream.

    Three separate contracts, checked before any upstream work: the proxy is
    read-only, it never leaves the /api/ tree, and it is rate limited so it
    cannot be used to amplify traffic at toolhub.wikimedia.org.
    """
    if request.method != "GET":
        return Response('{"error":"read-only proxy"}', status=405, content_type="application/json")
    if _escapes_api_prefix(path):
        return Response('{"error":"invalid api path"}', status=400, content_type="application/json")
    if security.read_rate_limited(request.remote_addr):
        resp = Response('{"error":"rate limit exceeded"}', status=429, content_type="application/json")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Retry-After"] = str(int(security.WRITE_WINDOW_SECONDS))
        return resp
    return None


@app.route("/api/", defaults={"path": ""}, methods=_PROXY_METHODS)
@app.route("/api/<path:path>", methods=_PROXY_METHODS)
def api_proxy(path: str) -> Response:
    """Read-only reverse proxy to the live Toolhub API (same-origin for the SPA)."""
    rejected = _rejected_proxy_request(path)
    if rejected is not None:
        return rejected
    qs = request.query_string.decode()
    url = UPSTREAM + "/api/" + path + (("?" + qs) if qs else "")
    cached = api_cache.get(url)
    if cached is not None:
        return _cached_api_response(cached, "hit")
    stale = api_cache.get(url, allow_stale=True)
    if stale is not None:
        _schedule_background_revalidation(url, stale)
        return _cached_api_response(stale, "stale", upstream=_UPSTREAM_BACKGROUND)
    upstream, payload, early = _fetch_upstream(url, stale)
    if early is not None:
        return early
    if upstream is None or payload is None:
        raise RuntimeError
    return _relay_upstream_response(url, upstream, payload, stale)


def _twin_is_current(packed: Path, plain: Path) -> bool:
    """Whether a gzipped twin is at least as new as the file it represents."""
    try:
        return packed.stat().st_mtime >= plain.stat().st_mtime
    except OSError:
        # No plain file to compare against: the twin is all there is.
        return True


def _send_static(root: Path, path: str) -> Response:
    """Serve a static file, preferring the twin gzipped at build time.

    Compressing in the request path cost CPU on every hit, and this pod is
    capped at 500m — it was spending 66% of its scheduling periods throttled
    while a cold page load fetched 33 modules. tools/build_dist.py stores a
    `.gz` beside each text asset, so serving one is a file read.

    Flask derives the ETag and answers If-None-Match from whichever file it is
    given, so the gzipped twin carries its own tag and revalidation keeps
    working. `Vary` is what stops a cache handing that body to a client that
    did not ask for it.

    A twin older than the file it stands for is ignored. The build writes both
    together, so this only happens when something else rewrites a file in
    place — correcting a generated release manifest, say — and the stale twin
    would otherwise win silently for every client that accepts gzip, which is
    all of them.
    """
    if "gzip" in request.headers.get("Accept-Encoding", "").lower():
        packed = (root / f"{path}.gz").resolve()
        plain = (root / path).resolve()
        if root in packed.parents and packed.is_file() and _twin_is_current(packed, plain):
            resp = send_from_directory(root, f"{path}.gz")
            # send_from_directory typed this from the .gz suffix; the client
            # needs the type of what it will have after decoding.
            guessed = guess_type(path)[0]
            if guessed:
                resp.headers["Content-Type"] = guessed
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers.add("Vary", "Accept-Encoding")
            return resp
    return send_from_directory(root, path)


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
        resp = _send_static(root, path)
        resp.headers["Cache-Control"] = _VERSIONED_STATIC_CACHE if request.args.get("v") else _REVALIDATED_STATIC_CACHE
        return resp
    # A locale catalog that is not shipped must 404 rather than fall through to
    # the SPA shell. The frontend asks for /i18n/<locale>.json and treats a null
    # body as "not translated yet"; an index.html body under a 200 would instead
    # reach JSON.parse and surface a routine missing translation as a fetch error.
    if path.startswith("i18n/") and path.endswith(".json"):
        abort(404)
    resp = send_from_directory(root, "index.html")
    resp.headers["Cache-Control"] = _REVALIDATED_STATIC_CACHE
    return resp


if __name__ == "__main__":  # pragma: no cover - local dev entrypoint, not exercised by tests
    app.run(host="127.0.0.1", port=8000)
