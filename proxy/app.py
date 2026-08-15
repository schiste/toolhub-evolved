# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge webservice for Toolhub Evolved.

Serves the static single-page app and its local Toolhub catalog replica, plus
the site's own backend: Toolhub OAuth sign-in, the /v1 overlay API, and the
official Toolhub write bridge. Public web requests never fetch Toolhub; only
scheduled synchronizers and authenticated writes perform upstream I/O.

The legacy /api surface is cache-only compatibility for developer examples.
Official writes go through /v1/toolhub/* with a stored per-user OAuth grant;
Evolved-only overlay writes land in the local database via /v1.
"""

from gzip import compress as gzip_compress
from mimetypes import guess_type
from pathlib import Path
from time import perf_counter

from flask import Flask, Response, abort, g, request, send_from_directory

import backend
from backend import activity_privacy, api_cache, security

HERE = Path(__file__).resolve().parent
_SOURCE_DIR = (HERE.parent / "public_html").resolve()
_DIST_DIR = (HERE.parent / "dist").resolve()
UPSTREAM = "https://toolhub.wikimedia.org"


def _static_root() -> Path:
    """Serve the minified `dist/` build when present (production), else raw source."""
    return _DIST_DIR if _DIST_DIR.is_dir() else _SOURCE_DIR


UA = "toolhub-evolved/0.2 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"

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
_HTTP_OK = 200
_HTTP_NOT_MODIFIED = 304
# Statuses that carry no body to compress.
_BODILESS_STATUSES = {204, _HTTP_NOT_MODIFIED}
_CACHE_HEADER = "X-Toolhub-Evolved-Cache"
_UPSTREAM_HEADER = "X-Toolhub-Evolved-Upstream"
_SERVER_TIMING_HEADER = "Server-Timing"

app = Flask(__name__, static_folder=None)
backend.register(app)


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
    if resp.status_code < _HTTP_OK or resp.status_code in _BODILESS_STATUSES:
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
    """Serve a persisted Toolhub response without upstream request-time I/O."""
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
        return _cached_api_response(stale, "stale", upstream="none")
    expired = api_cache.get_local(url)
    if expired is not None:
        return _cached_api_response(expired, "replica", upstream="none")
    resp = Response('{"error":"local replica entry unavailable"}', status=503, content_type="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return _with_proxy_diagnostics(resp, cache="miss", upstream="none")


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
