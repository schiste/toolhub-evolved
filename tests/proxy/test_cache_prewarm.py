# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the scheduled Toolhub API cache prewarmer."""

import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import cache_prewarm  # noqa: E402
from backend import api_cache, db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()
    api_cache.clear()


class FakePrewarmResponse:
    def __init__(self, status_code=200, body=b'{"ok":true}', headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {"content-type": "application/json"}
        self.closed = False

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


class FakePrewarmSession:
    def __init__(self, responses=None, raises=None):
        self.responses = list(responses or [])
        self.raises = raises
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.responses.pop(0) if self.responses else FakePrewarmResponse()


def test_hot_endpoint_urls_cover_spa_entrypoints_and_search_terms(monkeypatch):
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    monkeypatch.setenv("TOOLHUB_CACHE_PREWARM_SEARCH_QUERIES", "wikidata, commons, wikidata, toolforge")

    urls = [cache_prewarm.url_for_endpoint(endpoint) for endpoint in cache_prewarm.hot_endpoints()]

    assert "https://toolhub.example/api/ui/home/" in urls
    assert "https://toolhub.example/api/recent/?page_size=30" in urls
    assert "https://toolhub.example/api/schema/" in urls
    assert "https://toolhub.example/api/lists/?page_size=30" in urls
    assert "https://toolhub.example/api/lists/?featured=true&page_size=6" in urls
    # Two first pages: 21 is the search view's default (public_html/lib/core/paging.js),
    # 24 is the fixed size the home strip asks for. Different callers, both hot.
    assert "https://toolhub.example/api/search/tools/?page=1&page_size=21" in urls
    assert "https://toolhub.example/api/search/tools/?page=1&page_size=24" in urls
    assert "https://toolhub.example/api/search/tools/?ordering=-modified_date&page_size=5" in urls
    assert "https://toolhub.example/api/search/tools/?q=wikidata&page=1&page_size=21" in urls
    assert "https://toolhub.example/api/search/tools/?q=commons&page=1&page_size=21" in urls
    assert len(urls) == len(set(urls))


def test_the_audit_page_asks_for_a_page_size_the_prewarmer_keeps_hot(monkeypatch):
    """/v1/catalog/auditlogs/ is answered only from the replica, keyed on the
    exact url including its query string. A page_size nothing prewarms is a 503,
    and views/audit.js turns a failed read into an empty feed -- so a mismatch
    here does not look like a bug, it looks like a catalog where nothing has
    ever changed. Assert against the number the view actually asks for rather
    than a copy of it, since a copy drifts in exactly the same silence.
    """
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    source = (ROOT / "public_html" / "views" / "audit.js").read_text(encoding="utf-8")
    asked = re.search(r'apiGet\(\s*"/auditlogs/"\s*,\s*\{\s*page_size:\s*"(\d+)"', source)
    assert asked is not None, "views/audit.js no longer reads /auditlogs/ with a literal page_size"

    urls = [cache_prewarm.url_for_endpoint(endpoint) for endpoint in cache_prewarm.hot_endpoints()]

    assert f"https://toolhub.example/api/auditlogs/?page_size={asked.group(1)}" in urls


def test_the_history_page_asks_for_a_page_size_the_prewarmer_uses(monkeypatch):
    """Same coupling as the audit feed, and the same silent failure if it drifts."""
    monkeypatch.setenv("TOOLHUB_API_BASE", "https://toolhub.example")
    source = (ROOT / "public_html" / "views" / "tool.js").read_text(encoding="utf-8")
    asked = re.search(r"/revisions/`,\s*\{\s*page_size:\s*\"(\d+)\"", source)
    assert asked is not None, "views/tool.js no longer reads /revisions/ with a literal page_size"

    assert cache_prewarm.REVISIONS_PAGE_SIZE == asked.group(1)


def test_revision_endpoints_are_bounded_and_leave_the_tool_name_unencoded():
    """The lookup key is built from an already-decoded path, so encoding here
    would file an awkwardly named tool under a key no request can produce."""
    endpoints = cache_prewarm.tool_revision_endpoints([f"tool-{i}" for i in range(100)])
    assert len(endpoints) == cache_prewarm.REVISION_MAX_TOOLS

    spaced = cache_prewarm.tool_revision_endpoints(["a tool"])
    assert spaced[0].path == "/api/tools/a tool/revisions/"


def test_run_once_warms_missing_endpoint_and_skips_fresh_endpoint():
    endpoint = cache_prewarm.HotEndpoint("/api/schema/")
    url = cache_prewarm.url_for_endpoint(endpoint)
    session = FakePrewarmSession([FakePrewarmResponse(body=b'{"schema":true}', headers={"etag": "schema-v1"})])

    summary = cache_prewarm.run_once(session, endpoints=[endpoint])

    assert summary.warmed == 1
    assert summary.skipped == 0
    assert len(session.calls) == 1
    cached = api_cache.get(url)
    assert cached is not None
    assert cached.body == b'{"schema":true}'
    assert cached.etag == "schema-v1"

    skipped = cache_prewarm.run_once(session, endpoints=[endpoint])
    assert skipped.warmed == 0
    assert skipped.skipped == 1
    assert len(session.calls) == 1


def test_run_once_revalidates_cached_endpoint_with_conditional_headers(monkeypatch):
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    monkeypatch.setattr(api_cache, "utcnow", lambda: clock["t"])
    endpoint = cache_prewarm.HotEndpoint("/api/recent/", (("page_size", "30"),))
    url = cache_prewarm.url_for_endpoint(endpoint)
    api_cache.put_success(
        url,
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=b'{"old":true}',
            etag="recent-v1",
            last_modified="Wed, 01 Jan 2026 12:00:00 GMT",
        ),
        fresh_seconds=1,
    )
    clock["t"] += timedelta(seconds=2)
    session = FakePrewarmSession([FakePrewarmResponse(status_code=304, body=b"")])

    summary = cache_prewarm.run_once(session, endpoints=[endpoint])

    assert summary.revalidated == 1
    assert session.calls[0][1]["headers"]["If-None-Match"] == "recent-v1"
    assert session.calls[0][1]["headers"]["If-Modified-Since"] == "Wed, 01 Jan 2026 12:00:00 GMT"
    assert api_cache.get(url) is not None
    assert api_cache.get(url).stale is False


def test_run_once_records_transient_failures_without_caching_error():
    endpoint = cache_prewarm.HotEndpoint("/api/lists/", (("page_size", "30"),))
    url = cache_prewarm.url_for_endpoint(endpoint)
    summary = cache_prewarm.run_once(FakePrewarmSession([FakePrewarmResponse(status_code=503)]), endpoints=[endpoint])

    assert summary.failed == 1
    assert api_cache.get(url, allow_stale=True) is None


def test_run_once_prewarms_recent_owner_cache_from_warmed_recent_feed(monkeypatch):
    calls = []

    def fake_resolve(names):
        calls.append(names)
        return {
            "owners": {"alpha": "Ada", "bravo": "Grace"},
            "meta": {"alpha": {"cached": False}, "bravo": {"cached": True}},
        }

    monkeypatch.setattr(cache_prewarm.recent_owners, "resolve_owners", fake_resolve)
    endpoint = cache_prewarm.HotEndpoint("/api/recent/", (("page_size", "30"),))
    session = FakePrewarmSession(
        [
            FakePrewarmResponse(
                body=b'{"results":[{"content_type":"tool","content_id":"alpha"},{"content_type":"list","content_id":"77"},{"content_type":"tool","content_id":"bravo"},{"content_type":"tool","content_id":"alpha"}]}'
            )
        ]
    )

    summary = cache_prewarm.run_once(session, endpoints=[endpoint])

    assert summary.warmed == 1
    assert summary.owners == 2
    assert summary.owner_cached == 1
    assert calls == [["alpha", "bravo"]]


def test_main_configures_db_runs_once_and_prints(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/cache.sqlite3")
    monkeypatch.setattr(
        cache_prewarm,
        "run_once",
        lambda: cache_prewarm.PrewarmSummary(endpoints=2, warmed=1, revalidated=1),
    )
    assert cache_prewarm.main() == 0
    assert (
        "cache-prewarm: warmed=1 revalidated=1 skipped=0 failed=0 endpoints=2 owners=0 owner_cached=0"
        in capsys.readouterr().out
    )
    assert os.environ["TOOLHUB_DB_URL"].endswith("cache.sqlite3")
