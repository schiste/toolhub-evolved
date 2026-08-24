# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the server-side crawler job (proxy/crawl.py)."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import crawl  # noqa: E402
from backend import db, outbound  # noqa: E402
from backend.models import (  # noqa: E402
    CrawlerRun,
    CrawlerUrl,
    PersonReconciliationQueue,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolRecord,
    User,
    utcnow,
)
from backend.sync import AUTHOR_CLAIM_SIGNED_TOOLINFO, AUTHOR_CLAIM_VERIFIED, SYNC_ERROR  # noqa: E402


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
        monkeypatch.setattr(outbound, "require_allowed", lambda *_a, **_k: None)
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
    # The skip is a successful no-op: it must stay out of `errors`, which alone
    # sets the exit code the job guard disables the crawler from.
    assert run.errors == []
    assert run.ok is True
    assert "exists upstream" in run.skipped[0]
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps([ITEM]).encode(), raises="upstream"))
    assert run.added == 0  # upstream check erring never shadows an upstream record


def test_crawl_skipped_run_keeps_url_and_exit_status_healthy(monkeypatch, capsys):
    """A registered URL whose only name exists upstream must not fail the job."""
    add_url()
    session = FakeSession(feed_body=json.dumps([ITEM]).encode(), upstream_status=200)
    monkeypatch.setattr(crawl.requests, "Session", lambda: session)
    monkeypatch.setattr(outbound, "require_allowed", lambda *_a, **_k: None)
    monkeypatch.setattr(crawl.db, "configure", lambda *_a, **_k: None)
    monkeypatch.setattr(crawl.db, "init_schema", lambda: None)
    assert crawl.main() == 0  # job guard counts any non-zero exit as a failure
    assert "1 skipped (0 upstream unreachable), 0 errors" in capsys.readouterr().out
    with db.session_scope() as s:
        row = s.query(CrawlerUrl).one()
        assert row.last_status != SYNC_ERROR
        assert row.last_error is None


def test_classify_upstream_routes_each_state():
    assert crawl.classify_upstream(crawl.UPSTREAM_ABSENT, "t") is None  # only state we ingest
    present = crawl.classify_upstream(crawl.UPSTREAM_PRESENT, "t")
    assert present is not None and present[0] == crawl.BUCKET_SKIPPED
    unreachable = crawl.classify_upstream(crawl.UPSTREAM_UNREACHABLE, "t")
    # Pinned, not "either bucket": routing this to BUCKET_ERROR restores the
    # three-strike disable the bucket split exists to prevent.
    assert unreachable == (crawl.BUCKET_SKIPPED, "t: upstream check unavailable — skipped (never shadow an upstream record)")


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_upstream_failure_status_is_unreachable_not_present(monkeypatch, status):
    """A failing Toolhub must never be read as 'this name already exists there'."""
    session = FakeSession(upstream_status=status)
    assert crawl.upstream_state(session, "any-name") == crawl.UPSTREAM_UNREACHABLE


@pytest.mark.parametrize("status", [200, 204])
def test_upstream_success_status_is_present(monkeypatch, status):
    session = FakeSession(upstream_status=status)
    assert crawl.upstream_state(session, "any-name") == crawl.UPSTREAM_PRESENT


def test_upstream_404_is_absent():
    assert crawl.upstream_state(FakeSession(upstream_status=404), "any-name") == crawl.UPSTREAM_ABSENT


def test_toolhub_outage_does_not_claim_the_tool_exists_upstream(monkeypatch):
    """The whole point of F4: a 503 used to produce a green run whose log said
    'exists upstream on Toolhub' about a name nobody successfully looked up."""
    add_url()
    body = json.dumps([ITEM]).encode()
    monkeypatch.setattr(crawl.requests, "Session", lambda: FakeSession(feed_body=body, upstream_status=503))
    monkeypatch.setattr(outbound, "require_allowed", lambda *_a, **_k: None)
    run, unreachable = crawl.run_crawl_with_counts()
    assert run.added == 0  # still never shadows an upstream record
    assert run.ok is True  # still green: an outage must not trip the job guard
    assert unreachable == 1  # but it is now countable
    assert "exists upstream" not in " ".join(run.skipped)
    assert "unavailable" in " ".join(run.skipped)


def test_crawl_records_signed_toolinfo_claim_even_when_upstream_exists(monkeypatch):
    owner_id = add_url()
    with db.session_scope() as s:
        user = s.get(User, owner_id)
        assert user is not None
        s.add(ToolAuthorKey(toolhub_username=user.username, key_id="k1", public_key="pk"))
    monkeypatch.setattr(crawl.SIGNED_TOOLINFO_PROVIDER, "verifier", lambda *_args: None)
    signed_item = {
        **ITEM,
        "author": [{"name": "Crawler Fan"}],
        "x_toolhub_evolved_signature": {"key_id": "k1", "signature": "c2ln"},
    }
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps([signed_item]).encode(), upstream_status=200))
    assert run.added == 0
    with db.session_scope() as s:
        claim = s.query(ToolAuthorClaim).one()
        assert claim.tool_name == "fresh-tool"
        assert claim.author_name == "Crawler Fan"
        assert claim.verification_status == AUTHOR_CLAIM_VERIFIED
        assert claim.verification_method == AUTHOR_CLAIM_SIGNED_TOOLINFO
        assert claim.evidence_url == "https://example.org/toolinfo.json"
        queue = s.get(PersonReconciliationQueue, "fresh-tool")
        assert queue is not None
        assert queue.reason == "toolinfo_ingestion"


def test_crawl_fetch_failure_and_size_cap(monkeypatch):
    add_url()
    run = run_with(monkeypatch, FakeSession(raises="feed"))
    assert run.ok is False
    monkeypatch.setattr(outbound, "STRICT_PUBLIC", replace(outbound.STRICT_PUBLIC, max_body_bytes=4))
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


def test_crawl_ingests_when_url_owner_row_is_missing(monkeypatch):
    with db.session_scope() as s:
        s.add(CrawlerUrl(user_id=999, url="https://orphan.example/toolinfo.json"))
    run = run_with(monkeypatch, FakeSession(feed_body=json.dumps([ITEM]).encode()))
    assert run.added == 1
    with db.session_scope() as s:
        assert s.query(ToolRecord).one().user_id == 999


def test_main_exit_codes(monkeypatch, capsys, tmp_path):
    # File-backed DB: main() reconfigures the engine itself, so state must survive.
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/crawl.sqlite3")
    monkeypatch.setattr(crawl.requests, "Session", lambda: FakeSession())
    assert crawl.main() == 0  # no urls registered → clean run
    assert "0 urls" in capsys.readouterr().out
    add_url()  # lands in the file-backed DB main() just configured
    monkeypatch.setattr(crawl.requests, "Session", lambda: FakeSession(raises="feed"))
    # An unreachable feed is a recorded observation, not a failed sweep: this
    # job has one registered URL, so exiting non-zero here tripped the guard's
    # breaker after three flaky hours and stopped the job for ten days.
    assert crawl.main() == 0
    with db.session_scope() as s:
        assert s.query(CrawlerRun).order_by(CrawlerRun.id.desc()).first().ok is False


def guard(url):
    """Apply the crawler's fetch policy to one URL (the guard now lives in backend.outbound)."""
    return outbound.require_allowed(url, outbound.STRICT_PUBLIC, scheme_error="only https toolinfo URLs are crawled")


def test_require_public_https_guard(monkeypatch):
    with pytest.raises(ValueError, match="only https"):
        guard("http://example.org/toolinfo.json")
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        guard("https://sneaky.example/toolinfo.json")
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("10.0.0.7", 443))])
    with pytest.raises(ValueError, match="non-public"):
        guard("https://internal.example/toolinfo.json")

    def nxdomain(*a, **k):
        raise OSError("nxdomain")

    monkeypatch.setattr(outbound.socket, "getaddrinfo", nxdomain)
    with pytest.raises(ValueError, match="cannot resolve"):
        guard("https://nope.example/toolinfo.json")
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))])
    guard("https://ok.example/toolinfo.json")  # public → no raise


def test_crawl_refuses_redirects_and_private_hosts(monkeypatch):
    add_url()
    # Real guard first (a later run_with(public=True) no-ops it for the rest of the test).
    monkeypatch.setattr(outbound.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("192.168.1.10", 443))])
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

    def ingest_and_delete(_items, _owner_id, _toolinfo_url, _session, _counts, _errors, _skipped):
        with db.session_scope() as s:
            s.delete(s.get(CrawlerUrl, second_id))

    monkeypatch.setattr(crawl, "_ingest_items", ingest_and_delete)
    assert crawl.run_crawl().ok is True
