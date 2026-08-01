"""Behaviour + security tests for the Toolforge proxy (proxy/app.py).

Covers the reverse-proxy contract (read-only, no-follow-redirects, size cap,
cache-only-on-success, transparent status relay), the static-file traversal
guard, and the baseline security headers. The CSP test recomputes the inline
theme-script hash from index.html and asserts the proxy's CSP carries it, so the
hash can never silently drift out of sync.
"""

import base64
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

# app.py calls backend.register() at import time, which refuses to start without
# a session secret. Supply one before the import rather than weakening the guard.
os.environ.setdefault("TOOLHUB_SECRET_KEY", "test-secret")

import app as proxy_app  # noqa: E402  (path injected above)
from backend import db  # noqa: E402
from backend.models import ApiCache, CanonicalToolCache, PersonReconciliationQueue  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """The proxy's API cache and read limiter are process-wide; isolate tests."""
    proxy_app.api_cache.clear()
    proxy_app.security.clear_rate_limits()
    with proxy_app._BACKGROUND_REFRESH_LOCK:
        proxy_app._BACKGROUND_REFRESHING.clear()
    monkeypatch.setattr(proxy_app.api_cache, "maybe_poll_recent_changes", lambda *_args, **_kwargs: 0)
    yield
    proxy_app.api_cache.clear()
    proxy_app.security.clear_rate_limits()
    with proxy_app._BACKGROUND_REFRESH_LOCK:
        proxy_app._BACKGROUND_REFRESHING.clear()


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


@pytest.fixture
def fake_background_get(monkeypatch):
    """Stub the background refresh session's `.get`; return captured args + call count."""
    captured = {"calls": 0}

    def install(response=None, *, raises=None):
        def _get(url, **kwargs):
            captured["calls"] += 1
            captured["url"] = url
            captured["kwargs"] = kwargs
            if raises is not None:
                raise raises
            return response

        monkeypatch.setattr(proxy_app._BACKGROUND_SESSION, "get", _get)
        return captured

    return install


@pytest.fixture
def scheduled_revalidations(monkeypatch):
    """Capture background revalidation scheduling without running a thread."""
    scheduled = []
    monkeypatch.setattr(proxy_app, "_schedule_background_revalidation", lambda url, stale: scheduled.append((url, stale)))
    return scheduled


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
    assert "worker-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


# ---- reverse proxy ---------------------------------------------------------


def test_non_get_is_rejected_read_only(client):
    resp = client.post("/api/tools/")
    assert resp.status_code == 405
    assert resp.get_json()["error"] == "read-only proxy"


def test_parent_directory_segments_are_rejected(client, fake_get):
    captured = fake_get()
    # Flask decodes %2f before routing, so this reaches the view as "../../o/token/"
    # and would otherwise be normalized by requests into a fetch outside /api/.
    for path in ("..%2f..%2fo%2ftoken%2f", "../admin/", "tools/../../admin/"):
        resp = client.get(f"/api/{path}")
        assert resp.status_code == 400, path
        assert resp.get_json()["error"] == "invalid api path"
    assert captured["calls"] == 0, "no upstream request may be made for a rejected path"


def test_anonymous_reads_are_rate_limited(client, fake_get, monkeypatch):
    fake_get(FakeUpstream(200, b"{}"))
    clock = {"t": 100.0}
    monkeypatch.setattr(proxy_app.security.time, "monotonic", lambda: clock["t"])
    for _ in range(proxy_app.security.READ_LIMIT):
        assert client.get("/api/tools/x/").status_code == 200
    resp = client.get("/api/tools/x/")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"]
    clock["t"] += proxy_app.security.WRITE_WINDOW_SECONDS + 1  # window rolls over
    assert client.get("/api/tools/x/").status_code == 200


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
    search_ttl = proxy_app.api_cache.SEARCH_FRESH_SECONDS
    assert resp.headers["Cache-Control"] == f"public, max-age={search_ttl}, stale-if-error=86400"
    # query string forwarded verbatim, and redirects must not be followed
    assert captured["url"] == "https://toolhub.wikimedia.org/api/search/tools/?q=wiki&page=2"
    assert captured["kwargs"]["allow_redirects"] is False
    assert captured["kwargs"]["timeout"] == 20
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "200"
    timing = resp.headers["Server-Timing"]
    assert 'cache;desc="miss"' in timing
    assert re.search(r'upstream;dur=\d+\.\d;desc="200"', timing)
    assert re.search(r"app;dur=\d+\.\d", timing)
    with db.session_scope() as s:
        row = s.query(ApiCache).one()
        assert row.url == captured["url"]
        assert row.status == 200
        assert row.body == b'{"ok":true}'


def test_successful_tool_payload_populates_canonical_tool_cache(client, fake_get):
    body = b'{"results":[{"name":"toolforge-demo","title":"Demo","description":"Cached canonical tool"}]}'
    fake_get(FakeUpstream(200, body))

    resp = client.get("/api/search/tools/?q=demo")

    assert resp.status_code == 200
    with db.session_scope() as s:
        row = s.get(CanonicalToolCache, "toolforge-demo")
        assert row is not None
        assert row.record["title"] == "Demo"
        assert row.source_url == "https://toolhub.wikimedia.org/api/search/tools/?q=demo"
        queue = s.get(PersonReconciliationQueue, "toolforge-demo")
        assert queue is not None
        assert queue.reason == "canonical_fetch"


def test_successful_list_detail_payload_populates_canonical_tool_cache(client, fake_get):
    body = b'{"id":"L1","tools":[{"name":"listed-tool","title":"Listed","description":"From a list"}]}'
    fake_get(FakeUpstream(200, body))

    resp = client.get("/api/lists/L1/")

    assert resp.status_code == 200
    with db.session_scope() as s:
        row = s.get(CanonicalToolCache, "listed-tool")
        assert row is not None
        assert row.record["title"] == "Listed"
        assert row.source_url == "https://toolhub.wikimedia.org/api/lists/L1/"


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
    default_ttl = proxy_app.api_cache.DEFAULT_FRESH_SECONDS
    assert second.headers["Cache-Control"] == f"public, max-age={default_ttl}, stale-if-error=86400"
    assert second.headers["X-Toolhub-Evolved-Cache"] == "hit"
    assert second.headers["X-Toolhub-Evolved-Upstream"] == "200"
    timing = second.headers["Server-Timing"]
    assert 'cache;desc="hit"' in timing
    assert 'upstream;desc="200"' in timing
    assert re.search(r"app;dur=\d+\.\d", timing)


def test_cache_policy_uses_endpoint_specific_ttls():
    """Pin the freshness windows. These are deliberately long: the
    api-cache-invalidator evicts what actually changed, so a short window
    only adds upstream revalidations. Changing a number here should be a
    conscious retune, not a side effect."""
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/recent/").fresh_seconds == 5 * 60
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/search/tools/?q=wiki").fresh_seconds == 30 * 60
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/tools/citoid/").fresh_seconds == 6 * 60 * 60
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/lists/123/").fresh_seconds == 6 * 60 * 60
    assert proxy_app.api_cache.policy_for_url("https://toolhub.wikimedia.org/api/schema/").fresh_seconds == 86400


def test_detail_cache_stores_stale_if_error_after_fresh_window(client, fake_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"name":"citoid"}'))
    resp = client.get("/api/tools/citoid/")
    detail_ttl = proxy_app.api_cache.DETAIL_FRESH_SECONDS
    assert resp.headers["Cache-Control"] == f"public, max-age={detail_ttl}, stale-if-error=86400"
    with db.session_scope() as s:
        row = s.query(ApiCache).one()
        assert row.expires_at == clock["t"] + timedelta(seconds=detail_ttl)
        assert row.stale_until == clock["t"] + timedelta(seconds=detail_ttl + 86400)


def test_stale_cache_is_served_immediately_after_ttl(client, fake_get, monkeypatch, scheduled_revalidations):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    assert captured["calls"] == 1
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)  # past the fresh window
    resp = client.get("/api/tools/")
    assert captured["calls"] == 1, "stale cache must not wait for upstream"
    assert resp.status_code == 200
    assert resp.data == b'{"v":1}'
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "stale"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "background"
    assert 'cache;desc="stale"' in resp.headers["Server-Timing"]
    assert 'upstream;desc="background"' in resp.headers["Server-Timing"]
    assert "Response is stale" in resp.headers["Warning"]
    assert len(scheduled_revalidations) == 1
    assert scheduled_revalidations[0][0] == "https://toolhub.wikimedia.org/api/tools/"
    assert scheduled_revalidations[0][1].stale is True


def test_background_revalidation_is_scheduled_once_and_refreshes_the_row(client, fake_get, fake_background_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)

    ran = []
    monkeypatch.setattr(proxy_app._BACKGROUND_REFRESH, "submit", lambda fn, *a: ran.append((fn, a)))
    client.get("/api/tools/")
    client.get("/api/tools/")  # already in flight → not queued twice
    assert len(ran) == 1

    background = fake_background_get(FakeUpstream(200, b'{"v":2}'))
    ran[0][0](*ran[0][1])  # run what the pool would have run
    assert background["calls"] == 1
    assert proxy_app._BACKGROUND_REFRESHING == set(), "in-flight marker must be cleared"
    assert client.get("/api/tools/").data == b'{"v":2}'


def test_background_revalidation_swallows_failures(client, fake_get, fake_background_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)
    stale = proxy_app.api_cache.get("https://toolhub.wikimedia.org/api/tools/", allow_stale=True)

    # An unreachable upstream returns early; anything else is caught. Either way the
    # served response must be unaffected and the in-flight marker released.
    fake_background_get(raises=proxy_app.requests.RequestException("boom"))
    proxy_app._background_revalidate("https://toolhub.wikimedia.org/api/tools/", stale)
    monkeypatch.setattr(proxy_app, "_fetch_upstream", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kaboom")))
    proxy_app._background_revalidate("https://toolhub.wikimedia.org/api/tools/", stale)
    assert proxy_app._BACKGROUND_REFRESHING == set()
    assert client.get("/api/tools/").data == b'{"v":1}'


def test_background_revalidation_keeps_the_stale_row_on_a_transient_upstream_status(
    client, fake_get, fake_background_get, monkeypatch
):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)
    stale = proxy_app.api_cache.get("https://toolhub.wikimedia.org/api/tools/", allow_stale=True)

    # Serving stale happens in the request path now, so the relay only sees a
    # non-None stale row during a background refresh. A 503 there must not
    # overwrite the good body we are still serving.
    fake_background_get(FakeUpstream(503, b'{"error":"down"}'))
    proxy_app._background_revalidate("https://toolhub.wikimedia.org/api/tools/", stale)
    assert client.get("/api/tools/").data == b'{"v":1}'


def test_server_timing_helpers_handle_empty_and_untimed_requests(client):
    resp = proxy_app.Response("{}")
    proxy_app._append_server_timing(resp)  # nothing to add → header untouched
    assert "Server-Timing" not in resp.headers
    # A response built outside the request lifecycle has no recorded start time.
    with proxy_app.app.test_request_context("/"):
        out = proxy_app.set_security_headers(proxy_app.Response("{}"))
    assert "app;dur=" not in out.headers.get("Server-Timing", "")


def test_error_response_is_not_cached(client, fake_get):
    captured = fake_get(FakeUpstream(503, b'{"error":"x"}'))
    client.get("/api/tools/")
    client.get("/api/tools/")
    assert captured["calls"] == 2, "a 5xx must not be cached — every call re-fetches"


def test_cache_miss_does_not_poll_recent_changes_on_request_path(client, fake_get, monkeypatch):
    captured = fake_get(FakeUpstream(200, b'{"ok":true}'))

    def fail_if_polled(_fetch_recent):
        raise AssertionError("recent-change polling belongs to the scheduled job")

    monkeypatch.setattr(proxy_app.api_cache, "maybe_poll_recent_changes", fail_if_polled)
    resp = client.get("/api/tools/no-cache-yet/")
    assert resp.status_code == 200
    assert captured["calls"] == 1
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "miss"


def test_stale_cache_does_not_block_on_upstream_exception(client, fake_get, monkeypatch, scheduled_revalidations):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)
    calls_before_stale = captured["calls"]

    stale_captured = fake_get(raises=proxy_app.requests.RequestException("timeout"))
    resp = client.get("/api/tools/")
    assert captured["calls"] == calls_before_stale
    assert stale_captured["calls"] == calls_before_stale
    assert resp.status_code == 200
    assert resp.data == b'{"v":1}'
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "stale"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "background"
    assert "Response is stale" in resp.headers["Warning"]
    assert len(scheduled_revalidations) == 1


def test_stale_cache_does_not_block_on_transient_upstream_status(client, fake_get, monkeypatch, scheduled_revalidations):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    captured = fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)
    calls_before_stale = captured["calls"]

    stale_captured = fake_get(FakeUpstream(503, b'{"error":"upstream"}'))
    resp = client.get("/api/tools/")
    assert captured["calls"] == calls_before_stale
    assert stale_captured["calls"] == calls_before_stale
    assert resp.status_code == 200
    assert resp.data == b'{"v":1}'
    assert resp.headers["X-Toolhub-Evolved-Cache"] == "stale"
    assert resp.headers["X-Toolhub-Evolved-Upstream"] == "background"
    assert len(scheduled_revalidations) == 1


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


def test_background_revalidation_updates_stale_cache(client, fake_get, fake_background_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(FakeUpstream(200, b'{"v":1}'))
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)
    stale = proxy_app.api_cache.get("https://toolhub.wikimedia.org/api/tools/", allow_stale=True)
    assert stale is not None

    captured = fake_background_get(FakeUpstream(200, b'{"v":2}'))
    proxy_app._background_revalidate("https://toolhub.wikimedia.org/api/tools/", stale)
    refreshed = proxy_app.api_cache.get("https://toolhub.wikimedia.org/api/tools/")
    assert captured["calls"] == 1
    assert refreshed is not None
    assert refreshed.body == b'{"v":2}'
    assert refreshed.stale is False


def test_background_revalidation_uses_conditional_headers_for_304(client, fake_get, fake_background_get, monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(proxy_app.api_cache, "utcnow", lambda: clock["t"])
    fake_get(
        FakeUpstream(
            200,
            b'{"v":1}',
            headers={"etag": '"abc"', "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        )
    )
    client.get("/api/tools/")
    clock["t"] += timedelta(seconds=proxy_app.api_cache.FRESH_SECONDS + 1)
    stale = proxy_app.api_cache.get("https://toolhub.wikimedia.org/api/tools/", allow_stale=True)
    assert stale is not None

    captured = fake_background_get(FakeUpstream(304, b""))
    proxy_app._background_revalidate("https://toolhub.wikimedia.org/api/tools/", stale)
    assert captured["kwargs"]["headers"]["If-None-Match"] == '"abc"'
    assert captured["kwargs"]["headers"]["If-Modified-Since"] == "Mon, 01 Jan 2024 00:00:00 GMT"
    refreshed = proxy_app.api_cache.get("https://toolhub.wikimedia.org/api/tools/")
    assert refreshed is not None
    assert refreshed.body == b'{"v":1}'
    assert refreshed.stale is False


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


def test_client_cache_policy_mirrors_the_server_policy():
    """The SPA duplicates the server's freshness windows; fail if they drift.

    public_html/lib/core/api.js keeps its own copy of the cache policy so it can
    decide synchronously whether a cached response is still fresh. Two hand-kept
    copies of the same numbers drift, and the failure is silent: the browser
    would serve something the shared cache already considers stale (or refetch
    something it considers fresh). Recompute one from the other instead.
    """
    from backend import api_cache

    source = (ROOT / "public_html" / "lib" / "core" / "api.js").read_text(encoding="utf-8")

    def js_ttl_ms(name: str) -> int:
        # e.g. `const API_SEARCH_TTL_MS = 30 * 60 * 1000;`
        match = re.search(rf"const {name}\s*=\s*([0-9*\s]+);", source)
        assert match, f"{name} not found in api.js — the client policy moved"
        return eval(match.group(1))  # noqa: S307 - digits and '*' only, matched by the regex above

    expected = {
        "API_RECENT_TTL_MS": api_cache.RECENT_FRESH_SECONDS,
        "API_SEARCH_TTL_MS": api_cache.SEARCH_FRESH_SECONDS,
        "API_DETAIL_TTL_MS": api_cache.DETAIL_FRESH_SECONDS,
        "API_CRAWLER_TTL_MS": api_cache.CRAWLER_FRESH_SECONDS,
        "API_CONFIG_TTL_MS": api_cache.CONFIG_FRESH_SECONDS,
        "API_DEFAULT_TTL_MS": api_cache.DEFAULT_FRESH_SECONDS,
        "API_STALE_IF_ERROR_MS": api_cache.STALE_IF_ERROR_SECONDS,
    }
    for js_name, server_seconds in expected.items():
        assert js_ttl_ms(js_name) == server_seconds * 1000, (
            f"{js_name} in api.js disagrees with backend/api_cache.py ({server_seconds}s)"
        )
