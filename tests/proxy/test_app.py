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
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import app as proxy_app  # noqa: E402  (path injected above)
from backend import db  # noqa: E402
from backend.models import ApiCache  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """The proxy's API cache is shared through the DB; isolate tests."""
    proxy_app.api_cache.clear()
    monkeypatch.setattr(proxy_app.api_cache, "maybe_poll_recent_changes", lambda *_args, **_kwargs: 0)
    yield
    proxy_app.api_cache.clear()


@pytest.fixture
def client():
    proxy_app.app.config["TESTING"] = True
    return proxy_app.app.test_client()


class FakeUpstream:
    """Minimal stand-in for a streamed `requests` response."""

    def __init__(self, status_code, body=b"{}", content_type="application/json", headers=None, json_payload=None):
        self.status_code = status_code
        self._body = body
        self._json_payload = json_payload
        self.headers = {"content-type": content_type, **(headers or {})}
        self.closed = False

    @property
    def ok(self):
        return self.status_code < 400

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True

    def json(self):
        if isinstance(self._json_payload, ValueError):
            raise self._json_payload
        return self._json_payload


@pytest.fixture
def fake_get(monkeypatch):
    """Stub the pooled session's `.get`; return a dict capturing args + call count."""
    captured = {"calls": 0}

    def install(response=None, *, raises=None):
        def _get(url, **kwargs):
            captured["calls"] += 1
            captured["url"] = url
            captured["kwargs"] = kwargs
            if raises is not None:
                raise raises
            return response

        monkeypatch.setattr(proxy_app._SESSION, "get", _get)
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
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "timeout"


def test_success_is_relayed_and_cached(client, fake_get):
    captured = fake_get(FakeUpstream(200, b'{"ok":true}'))
    resp = client.get("/api/search/tools/?q=wiki&page=2")
    assert resp.status_code == 200
    assert resp.data == b'{"ok":true}'
    assert resp.headers["Cache-Control"] == "public, max-age=120, stale-if-error=86400"
    # query string forwarded verbatim, and redirects must not be followed
    assert captured["url"] == "https://toolhub.wikimedia.org/api/search/tools/?q=wiki&page=2"
    assert captured["kwargs"]["allow_redirects"] is False
    assert captured["kwargs"]["timeout"] == 20
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "200"
    with db.session_scope() as s:
        row = s.query(ApiCache).one()
        assert row.url == captured["url"]
        assert row.status == 200
        assert row.body == b'{"ok":true}'


def test_recent_invalidation_fetch_reads_toolhub_recent_rows(fake_get):
    captured = fake_get(
        FakeUpstream(
            200,
            json_payload={
                "results": [
                    {"id": 2, "content_type": "tool"},
                    "not-a-row",
                    {"id": 1, "content_type": "list"},
                ]
            },
        )
    )
    assert proxy_app._fetch_recent_change_rows() == [
        {"id": 2, "content_type": "tool"},
        {"id": 1, "content_type": "list"},
    ]
    assert captured["url"] == "https://toolhub.wikimedia.org/api/recent/?page_size=50"
    assert captured["kwargs"]["allow_redirects"] is False
    assert captured["kwargs"]["timeout"] == 10


def test_recent_invalidation_fetch_treats_failures_as_no_rows(fake_get):
    fake_get(raises=proxy_app.requests.RequestException("timeout"))
    assert proxy_app._fetch_recent_change_rows() == []

    fake_get(FakeUpstream(503, json_payload={"results": [{"id": 1}]}))
    assert proxy_app._fetch_recent_change_rows() == []

    fake_get(FakeUpstream(200, json_payload=ValueError("bad json")))
    assert proxy_app._fetch_recent_change_rows() == []

    fake_get(FakeUpstream(200, json_payload={"results": "not-list"}))
    assert proxy_app._fetch_recent_change_rows() == []


def test_error_status_is_relayed_but_not_cached(client, fake_get):
    fake_get(FakeUpstream(503, b'{"error":"upstream"}'))
    resp = client.get("/api/tools/")
    assert resp.status_code == 503
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "503"


def test_redirect_is_relayed_not_followed(client, fake_get):
    captured = fake_get(FakeUpstream(302, b"", content_type="text/html"))
    resp = client.get("/api/whatever/")
    assert resp.status_code == 302
    assert captured["kwargs"]["allow_redirects"] is False
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "302"


def test_oversize_response_is_rejected(client, fake_get, monkeypatch):
    monkeypatch.setattr(proxy_app, "_MAX_UPSTREAM_BYTES", 8)
    upstream = FakeUpstream(200, b"x" * 64)
    fake_get(upstream)
    resp = client.get("/api/tools/")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "upstream response too large"
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "200"
    assert upstream.closed is True, "the oversized stream must be closed"


def test_repeated_get_is_served_from_the_ttl_cache(client, fake_get):
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    first = client.get("/api/ui/home/")
    second = client.get("/api/ui/home/")
    assert captured["calls"] == 1, "second identical GET must hit the persistent API cache"
    assert first.data == second.data == b'{"v":1}'
    assert second.headers["Cache-Control"] == "public, max-age=60, stale-if-error=86400"
    assert second.headers["X-Toolhub-Evolved-Cache"] == "hit"
    assert second.headers["X-Toolhub-Evolved-Upstream"] == "200"


def test_cache_policy_uses_endpoint_specific_ttls():
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/recent/").fresh_seconds == 30
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/search/tools/?q=wiki").fresh_seconds == 120
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/tools/citoid/").fresh_seconds == 900
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/lists/123/").fresh_seconds == 900
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/schema/").fresh_seconds == 86400


def test_detail_cache_stores_stale_if_error_after_fresh_window(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"name":"citoid"}'))
    resp = client.get("/api/tools/citoid/")
    assert resp.headers["Cache-Control"] == "public, max-age=900, stale-if-error=86400"
    with db.session_scope() as s:
        row = s.query(ApiCache).one()
        assert row.expires_at == clock["t"] + timedelta(seconds=900)
        assert row.stale_until == clock["t"] + timedelta(seconds=900 + 86400)


def test_cache_expires_after_ttl(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    assert captured["calls"] == 1
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)  # past the fresh window
    client.get("/api/tools/")
    assert captured["calls"] == 2, "an expired entry must be re-fetched"


def test_error_response_is_not_cached(client, fake_get):
    captured = fake_get(FakeUpstream(503, b'{"error":"x"}'))
    client.get("/api/tools/")
    client.get("/api/tools/")
    assert captured["calls"] == 2, "a 5xx must not be cached — every call re-fetches"


def test_stale_cache_is_served_on_transient_upstream_exception(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)

    fake_get(raises=proxy_app.requests.RequestException("timeout"))
    resp = client.get("/api/tools/")
    assert captured["calls"] == 2
    assert resp.status_code == 200
    assert resp.data == b'{"v":1}'
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "stale"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "timeout"
    assert "Response is stale" in resp.headers["Warning"]


def test_stale_cache_is_served_on_transient_upstream_status(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)

    fake_get(FakeUpstream(503, b'{"error":"upstream"}'))
    resp = client.get("/api/tools/")
    assert captured["calls"] == 2
    assert resp.status_code == 200
    assert resp.data == b'{"v":1}'
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "stale"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "503"


def test_stale_cache_is_not_served_after_stale_window(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + proxy_app.api_cache.STALE_SECONDS + 1)

    fake_get(raises=proxy_app.requests.RequestException("timeout"))
    resp = client.get("/api/tools/")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "upstream unavailable"


def test_proxy_raises_if_fetch_contract_is_broken(client, monkeypatch):
    monkeypatch.setattr(proxy_app, "_fetch_upstream", lambda *_args: (None, None, None))
    with pytest.raises(RuntimeError):
        client.get("/api/tools/")


def test_stale_cache_revalidates_with_conditional_headers(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(
        FakeUpstream(
            200,
            b'{"v":1}',
            headers={"etag": '"abc"', "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        )
    )
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)

    fake_get(FakeUpstream(304, b""))
    resp = client.get("/api/tools/")
    assert captured["calls"] == 2
    assert captured["kwargs"]["headers"]["If-None-Match"] == '"abc"'
    assert captured["kwargs"]["headers"]["If-Modified-Since"] == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert resp.status_code == 200
    assert resp.data == b'{"v":1}'
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "revalidated"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "304"


# ---- static files ----------------------------------------------------------


def test_existing_asset_is_served(client):
    resp = client.get("/main.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["Content-Type"]
    assert resp.headers["Cache-Control"] == "no-cache"


def test_versioned_asset_is_cached_immutably(client):
    resp = client.get("/main.js?v=test-build")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_unknown_route_falls_back_to_index(client):
    resp = client.get("/tools/some-tool")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-cache"
    assert "<!doctype html" in resp.get_data(as_text=True).lower()


def test_serves_from_dist_build_when_present(client, monkeypatch, tmp_path):
    # A built dist/ (production) must be preferred over the raw public_html source.
    dist = tmp_path.resolve()
    (dist / "main.js").write_text("//min\n", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html><title>min</title>", encoding="utf-8")
    monkeypatch.setattr(proxy_app, "_DIST_DIR", dist)
    assert proxy_app._static_root() == dist
    served = client.get("/main.js")
    assert served.status_code == 200
    assert b"//min" in served.data
    assert b"<title>min</title>" in client.get("/any/spa/route").data  # SPA fallback from dist


def test_path_traversal_falls_back_to_index_not_the_file():
    # A path that resolves OUTSIDE public_html must serve index.html, never the
    # target file — the containment guard, belt-and-suspenders to Werkzeug.
    with proxy_app.app.test_request_context("/"):
        resp = proxy_app.static_files("../proxy/app.py")
    resp.direct_passthrough = False  # allow reading the file-backed body in-test
    body = resp.get_data(as_text=True)
    assert "Toolforge webservice for Toolhub Evolved" not in body, "app.py source must never leak"
    assert "<!doctype html" in body.lower()
