# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge webservice for Toolhub Evolved.

Serves the static single-page app AND reverse-proxies read-only GET requests to
the live Toolhub API at the same origin, so the browser can read live catalog
data without hitting CORS (the upstream API sends no CORS headers).

It is NOT an open proxy: requests only ever go to UPSTREAM/api/... and only GET.
"""

from pathlib import Path

import requests
from flask import Flask, Response, request, send_from_directory

HERE = Path(__file__).resolve().parent
STATIC_DIR = (HERE.parent / "public_html").resolve()
UPSTREAM = "https://toolhub.wikimedia.org"
UA = "toolhub-evolved/0.1 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"

# The proxy buffers the upstream body before relaying it; cap that buffer so a
# (hypothetical) runaway upstream response can't exhaust the webservice's memory.
# Toolhub JSON pages are a few hundred KiB at most, so 10 MiB is generous slack.
_MAX_UPSTREAM_BYTES = 10 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_UPSTREAM_CACHE = "public, max-age=300"

app = Flask(__name__, static_folder=None)

# CSP hash of the one inline theme script in index.html (kept inline so the theme
# resolves before first paint — no FOUC). tests/proxy/test_app.py recomputes this
# from index.html and fails if it drifts, so the value can never silently rot.
# script-src is strict (no 'unsafe-inline'); style-src allows inline because the
# UI emits data-driven inline styles (avatar colours, progress widths, graph node
# colours). img-src allows any https origin: tool icons are arbitrary remote
# images. The browser only ever fetches same-origin (/api/ is proxied
# server-side), hence connect-src 'self'.
_THEME_SCRIPT_HASH = "sha256-mfahDh9sflhz+LKpkp0YGqaHhBK2KGi66qeLZGevMBI="
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
    try:
        # allow_redirects=False: this is a fixed-target read-only proxy, so it must
        # never chase a 3xx the upstream returns (an upstream open redirect would
        # otherwise become SSRF to whatever host the Location names). A 3xx is
        # relayed through verbatim instead. stream=True so the body is read under
        # the size cap below rather than fully buffered by requests up front.
        upstream = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=20,
            allow_redirects=False,
            stream=True,
        )
        body = bytearray()
        for chunk in upstream.iter_content(_CHUNK_BYTES):
            body.extend(chunk)
            if len(body) > _MAX_UPSTREAM_BYTES:
                upstream.close()
                return Response('{"error":"upstream response too large"}', status=502, content_type="application/json")
    except requests.RequestException:
        return Response('{"error":"upstream unavailable"}', status=502, content_type="application/json")
    resp = Response(
        bytes(body),
        status=upstream.status_code,
        content_type=upstream.headers.get("content-type", "application/json"),
    )
    # Only cache successful payloads. Caching a transient 4xx/5xx would serve the
    # error for 5 minutes and defeat the SPA's own retry of 502/503/504 (api.js).
    resp.headers["Cache-Control"] = _UPSTREAM_CACHE if upstream.ok else "no-store"
    return resp


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_files(path: str) -> Response:
    """Serve a static file if it exists, else index.html (clean-routed SPA).

    Flask's default send_from_directory adds ETag + Cache-Control: no-cache, so
    assets are cached but always revalidated (304 when unchanged, fresh after a
    deploy) — no stale modules, no blanket no-store perf hit.
    """
    candidate = (STATIC_DIR / path).resolve()
    if path and STATIC_DIR in candidate.parents and candidate.is_file():
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


if __name__ == "__main__":  # pragma: no cover - local dev entrypoint, not exercised by tests
    app.run(host="127.0.0.1", port=8000)
