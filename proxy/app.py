# SPDX-License-Identifier: GPL-3.0-or-later
"""Toolforge webservice for Toolhub Evolved.

Serves the static single-page app AND reverse-proxies read-only GET requests to
the live Toolhub API at the same origin, so the browser can read live catalog
data without hitting CORS (the upstream API sends no CORS headers).

It is NOT an open proxy: requests only ever go to UPSTREAM/api/... and only GET.
"""
import os

import requests
from flask import Flask, Response, request, send_from_directory

HERE = os.path.dirname(os.path.realpath(__file__))
STATIC_DIR = os.path.normpath(os.path.join(HERE, "..", "public_html"))
UPSTREAM = "https://toolhub.wikimedia.org"
UA = "toolhub-evolved/0.1 (https://toolhub-evolved.toolforge.org; christophe@aeptus.com)"

app = Flask(__name__, static_folder=None)


@app.route("/api/", defaults={"path": ""})
@app.route("/api/<path:path>")
def api_proxy(path):
    """Read-only reverse proxy to the live Toolhub API (same-origin for the SPA)."""
    if request.method != "GET":
        return Response('{"error":"read-only proxy"}', status=405, content_type="application/json")
    qs = request.query_string.decode()
    url = UPSTREAM + "/api/" + path + (("?" + qs) if qs else "")
    try:
        upstream = requests.get(
            url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=20
        )
    except requests.RequestException:
        return Response('{"error":"upstream unavailable"}', status=502, content_type="application/json")
    resp = Response(
        upstream.content,
        status=upstream.status_code,
        content_type=upstream.headers.get("content-type", "application/json"),
    )
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_files(path):
    """Serve a static file if it exists, else index.html (hash-routed SPA)."""
    candidate = os.path.normpath(os.path.join(STATIC_DIR, path))
    if path and candidate.startswith(STATIC_DIR) and os.path.isfile(candidate):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
