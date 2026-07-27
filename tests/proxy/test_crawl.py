# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the server-side crawler job (proxy/crawl.py)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import crawl  # noqa: E402
from backend import db  # noqa: E402
from backend.models import CrawlerRun, CrawlerUrl, ToolRecord, User, utcnow  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def add_url(url="https://example.org/toolinfo.json"):
    with db.session_scope() as s:
        user = User(wm_sub="c1", username="Crawler Fan")
        s.add(user)
        s.flush()
        s.add(CrawlerUrl(user_id=user.id, url=url))
        return user.id


class FakeResp:
    def __init__(self, body=b"[]", status=200):
        self._body = body
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        self.is_permanent_redirect = status in (301, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise crawl.requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Routes toolinfo-URL GETs and upstream-existence GETs separately."""

    def __init__(self, feed_body=b"[]", feed_status=200, upstream_status=404, raises=None):
        self.feed_body = feed_body
        self.feed_status = feed_status
        self.upstream_status = upstream_status
        self.raises = raises

    def get(self, url, **kwargs):
        if url.startswith(crawl.UPSTREAM_TOOL):
            if self.raises == "upstream":
                raise crawl.requests.RequestException("upstream down")
            return FakeResp(status=self.upstream_status)
        if self.raises == "feed":
            raise crawl.requests.RequestException("fetch failed")
        return FakeResp(self.feed_body, self.feed_status)


def run_with(monkeypatch, session, *, public=True):
    monkeypatch.setattr(crawl.requests, "Session", lambda: session)
    if public:  # tests must not depend on real DNS; the guard has its own tests
        monkeypatch.setattr(crawl, "_require_public_https", lambda url: None)
    return crawl.run_crawl()


ITEM = {"name": "fresh-tool", "title": "Fresh", "description": "New tool", "url": "https://f.example"}


def test_crawl_adds_then_updates(monkeypatch):
    owner_id = add_url()
    body = json.dumps([ITEM, {"bad": "item"}]).encode()
    run = run_with(monkeypatch, FakeSession(feed_body=body))
    assert (run.added, run.updated, run.ok) == (1, 0, False)  # bad item recorded as error
    assert "invalid item" in run.errors[0]
    with db.session_scope() as s:
        s.query(ToolRecord).one().created_by_user_id = None
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps(ITEM).encode()))  # single object + update path
    assert (run.added, run.updated) == (0, 1)
    with db.session_scope() as s:
        rec = s.query(ToolRecord).one()
        assert rec.record["origin"] == "crawler"
        assert rec.created_by_user_id == owner_id
        assert s.query(CrawlerRun).count() == 2
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps(ITEM).encode()))
    assert (run.added, run.updated) == (0, 1)
    with db.session_scope() as s:
        assert s.query(ToolRecord).one().created_by_user_id == owner_id
        assert s.query(CrawlerRun).count() == 3


def test_crawl_skips_upstream_names(monkeypatch):
    add_url()
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps([ITEM]).encode(), upstream_status=200))
    assert run.added == 0
    assert "exists upstream" in run.errors[0]
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps([ITEM]).encode(), raises="upstream"))
    assert run.added == 0  # upstream check erring counts as "exists" (never shadow)


def test_crawl_fetch_failure_and_size_cap(monkeypatch):
    add_url()
    run = run_with(monkeypatch, FakeSession(raises="feed"))
    assert run.ok is False
    monkeypatch.setattr(crawl, "MAX_BODY_BYTES", 4)
    run = run_with(monkeypatch, FakeSession(feed_body=b"[1,2,3,4,5]"))
    assert "larger than" in run.errors[0]


def test_crawl_http_error_and_keyword_string(monkeypatch):
    add_url()
    run = run_with(monkeypatch, FakeSession(feed_status=500))
    assert run.ok is False
    item = dict(ITEM, keywords="a, b,,c")
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps([item]).encode()))
    with db.session_scope() as s:
        assert s.query(ToolRecord).one().record["keywords"] == ["a", "b", "c"]


def test_main_exit_codes(monkeypatch, capsys, tmp_path):
    # File-backed DB: main() reconfigures the engine itself, so state must survive.
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/crawl.sqlite3")
    monkeypatch.setattr(crawl.requests, "Session", lambda: FakeSession())
    assert crawl.main() == 0  # no urls registered → clean run
    assert "0 urls" in capsys.readouterr().out
    add_url()  # lands in the file-backed DB main() just configured
    monkeypatch.setattr(crawl.requests, "Session", lambda: FakeSession(raises="feed"))
    assert crawl.main() == 1


def test_require_public_https_guard(monkeypatch):
    with pytest.raises(ValueError, match="only https"):
        crawl._require_public_https("http://example.org/toolinfo.json")
    monkeypatch.setattr(crawl.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        crawl._require_public_https("https://sneaky.example/toolinfo.json")
    monkeypatch.setattr(crawl.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("10.0.0.7", 443))])
    with pytest.raises(ValueError, match="non-public"):
        crawl._require_public_https("https://internal.example/toolinfo.json")

    def nxdomain(*a, **k):
        raise OSError("nxdomain")

    monkeypatch.setattr(crawl.socket, "getaddrinfo", nxdomain)
    with pytest.raises(ValueError, match="cannot resolve"):
        crawl._require_public_https("https://nope.example/toolinfo.json")
    monkeypatch.setattr(crawl.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))])
    crawl._require_public_https("https://ok.example/toolinfo.json")  # public → no raise


def test_crawl_refuses_redirects_and_private_hosts(monkeypatch):
    add_url()
    # Real guard first (a later run_with(public=True) no-ops it for the rest of the test).
    monkeypatch.setattr(crawl.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("192.168.1.10", 443))])
    run = run_with(monkeypatch, FakeSession(), public=False)  # private resolution → refused
    assert "non-public" in run.errors[0]
    run = run_with(monkeypatch, FakeSession(feed_status=302))
    assert "redirects are not followed" in run.errors[0]


def test_crawl_tolerates_url_deleted_before_status_update(monkeypatch):
    uid = add_url()
    with db.session_scope() as s:
        first_id = s.query(CrawlerUrl).one().id

    def fetch_delete_then_fail(_session, _url):
        with db.session_scope() as s:
            s.delete(s.get(CrawlerUrl, first_id))
        raise ValueError("gone")

    monkeypatch.setattr(crawl, "_fetch_json", fetch_delete_then_fail)
    run = crawl.run_crawl()
    assert run.ok is False
    assert "gone" in run.errors[0]

    with db.session_scope() as s:
        s.add(CrawlerUrl(user_id=uid, url="https://example.org/second.json"))
        s.flush()
        second_id = s.query(CrawlerUrl).filter_by(url="https://example.org/second.json").one().id

    monkeypatch.setattr(crawl, "_fetch_json", lambda _session, _url: ITEM)

    def ingest_and_delete(_items, _owner_id, _session, _counts, _errors):
        with db.session_scope() as s:
            s.delete(s.get(CrawlerUrl, second_id))

    monkeypatch.setattr(crawl, "_ingest_items", ingest_and_delete)
    assert crawl.run_crawl().ok is True
