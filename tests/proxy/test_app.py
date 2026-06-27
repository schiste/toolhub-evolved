"""Behaviour + security tests for the Toolforge proxy (proxy/app.py).

Covers the reverse-proxy contract (read-only, no-follow-redirects, size cap,
cache-only-on-success, transparent status relay), the static-file traversal
guard, and the baseline security headers. The CSP test recomputes the inline
theme-script hash from index.html and asserts the proxy's CSP carries it, so the
hash can never silently drift out of sync.
"""

import base64
import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import app as proxy_app  # noqa: E402  (path injected above)


@pytest.fixture
def client():
    proxy_app.app.config["TESTING"] = True
    return proxy_app.app.test_client()


class FakeUpstream:
    """Minimal stand-in for a streamed `requests` response."""

    def __init__(self, status_code, body=b"{}", content_type="application/json"):
        self.status_code = status_code
        self._body = body
        self.headers = {"content-type": content_type}
        self.closed = False

    @property
    def ok(self):
        return self.status_code < 400

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


@pytest.fixture
def fake_get(monkeypatch):
    """Install a stub `requests.get`; return a dict capturing the call args."""
    captured = {}

    def install(response=None, *, raises=None):
        def _get(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            if raises is not None:
                raise raises
            return response

        monkeypatch.setattr(proxy_app.requests, "get", _get)
        return captured

    return install


# ---- security headers ------------------------------------------------------


def test_baseline_security_headers(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "max-age=" in resp.headers["Strict-Transport-Security"]
    assert "geolocation=()" in resp.headers["Permissions-Policy"]


def test_csp_is_strict_and_matches_inline_script(client):
    html = (ROOT / "public_html" / "index.html").read_text(encoding="utf-8")
    inline = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(inline) == 1, "index.html must have exactly one inline <script> (the CSP carries one hash)"
    digest = base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode()

    csp = client.get("/").headers["Content-Security-Policy"]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert f"sha256-{digest}" in script_src, "CSP script-src hash is stale vs the index.html inline script"
    assert "'unsafe-inline'" not in script_src, "script-src must stay strict (no unsafe-inline)"
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


# ---- reverse proxy ---------------------------------------------------------


def test_non_get_is_rejected_read_only(client):
    resp = client.post("/api/tools/")
    assert resp.status_code == 405
    assert resp.get_json()["error"] == "read-only proxy"


def test_upstream_exception_returns_502(client, fake_get):
    fake_get(raises=proxy_app.requests.RequestException("boom"))
    resp = client.get("/api/tools/")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "upstream unavailable"


def test_success_is_relayed_and_cached(client, fake_get):
    captured = fake_get(FakeUpstream(200, b'{"ok":true}'))
    resp = client.get("/api/search/tools/?q=wiki&page=2")
    assert resp.status_code == 200
    assert resp.data == b'{"ok":true}'
    assert resp.headers["Cache-Control"] == "public, max-age=300"
    # query string forwarded verbatim, and redirects must not be followed
    assert captured["url"] == "https://toolhub.wikimedia.org/api/search/tools/?q=wiki&page=2"
    assert captured["kwargs"]["allow_redirects"] is False
    assert captured["kwargs"]["timeout"] == 20


def test_error_status_is_relayed_but_not_cached(client, fake_get):
    fake_get(FakeUpstream(503, b'{"error":"upstream"}'))
    resp = client.get("/api/tools/")
    assert resp.status_code == 503
    assert resp.headers["Cache-Control"] == "no-store"


def test_redirect_is_relayed_not_followed(client, fake_get):
    captured = fake_get(FakeUpstream(302, b"", content_type="text/html"))
    resp = client.get("/api/whatever/")
    assert resp.status_code == 302
    assert captured["kwargs"]["allow_redirects"] is False


def test_oversize_response_is_rejected(client, fake_get, monkeypatch):
    monkeypatch.setattr(proxy_app, "_MAX_UPSTREAM_BYTES", 8)
    upstream = FakeUpstream(200, b"x" * 64)
    fake_get(upstream)
    resp = client.get("/api/tools/")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "upstream response too large"
    assert upstream.closed is True, "the oversized stream must be closed"


# ---- static files ----------------------------------------------------------


def test_existing_asset_is_served(client):
    resp = client.get("/main.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["Content-Type"]


def test_unknown_route_falls_back_to_index(client):
    resp = client.get("/tools/some-tool")
    assert resp.status_code == 200
    assert "<!doctype html" in resp.get_data(as_text=True).lower()


def test_path_traversal_falls_back_to_index_not_the_file():
    # A path that resolves OUTSIDE public_html must serve index.html, never the
    # target file — the containment guard, belt-and-suspenders to Werkzeug.
    with proxy_app.app.test_request_context("/"):
        resp = proxy_app.static_files("../proxy/app.py")
    resp.direct_passthrough = False  # allow reading the file-backed body in-test
    body = resp.get_data(as_text=True)
    assert "Toolforge webservice for Toolhub Evolved" not in body, "app.py source must never leak"
    assert "<!doctype html" in body.lower()
