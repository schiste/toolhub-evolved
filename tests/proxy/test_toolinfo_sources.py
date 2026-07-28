# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for official Toolhub crawler source indexing."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

import toolinfo_sources as toolinfo_sources_job  # noqa: E402
from backend import db, toolhub, toolinfo_sources  # noqa: E402
from backend.models import ToolinfoSource, ToolinfoSourceItem  # noqa: E402
from backend.sync import SOURCE_OFFICIAL, SYNC_ERROR, SYNC_OFFICIAL  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.configure("sqlite://")
    db.init_schema()


def http_error(status):
    exc = toolinfo_sources.requests.HTTPError(str(status))
    exc.response = type("Resp", (), {"status_code": status})()
    return exc


class FakeResp:
    def __init__(self, body=b"{}", status=200, headers=None):
        self._body = body
        self.status_code = status
        self.headers = headers or {}
        self.is_redirect = 300 <= status < 400
        self.is_permanent_redirect = status in (301, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise http_error(self.status_code)

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_classifies_source_urls_and_labels():
    assert (
        toolinfo_sources.classify_source_url(
            "https://toolsadmin.wikimedia.org/tools/toolinfo/v1.2/toolinfo.json"
        )
        == "toolsadmin"
    )
    assert (
        toolinfo_sources.classify_source_url(
            "https://tools-static.wmflabs.org/toolinfo-scraper/enwiki_userscripts.json"
        )
        == "user_script_feed"
    )
    assert toolinfo_sources.classify_source_url("https://raw.githubusercontent.com/a/b/toolinfo.json") == "github_raw"
    assert toolinfo_sources.classify_source_url("https://wikitech.wikimedia.org/wiki/Foo?action=raw") == "wiki_raw"
    assert toolinfo_sources.classify_source_url("https://tool.example/toolinfo.json") == "self_hosted_toolinfo"
    assert toolinfo_sources.classify_source_url("https://tool.example/feed.json") == "other_feed"
    assert toolinfo_sources.source_label("unknown") == "Official crawler feed"


def test_registered_row_payload_helpers_and_registry_pagination(monkeypatch):
    calls = []

    def fake_public_api_get(path, *, params=None):
        calls.append((path, params))
        if params["page"] == 1:
            return {
                "results": [
                    {
                        "id": "5",
                        "url": "https://tool.example/toolinfo.json",
                        "created_by": {"id": "8", "username": "Toolhub"},
                        "created_date": "2026-07-28T12:00:00Z",
                    }
                ],
                "next": "page 2",
            }
        return {"results": [{"id": "6", "url": " ", "createdBy": "Ada", "created": "not a date"}], "next": None}

    monkeypatch.setattr(toolhub, "public_api_get", fake_public_api_get)
    assert toolinfo_sources.official_crawler_url_rows(page_size=2)[0]["id"] == "5"
    assert calls == [
        ("/api/crawler/urls/", {"page": 1, "page_size": 2}),
        ("/api/crawler/urls/", {"page": 2, "page_size": 2}),
    ]
    assert toolinfo_sources._registered_rows_from_payload([{"url": "x"}, "bad"]) == ([{"url": "x"}], False)
    assert toolinfo_sources._registered_rows_from_payload("bad") == ([], False)


def test_sync_registered_sources_upserts_and_preserves_fetch_errors(monkeypatch):
    with db.session_scope() as s:
        s.add(
            ToolinfoSource(
                official_id=7,
                url="https://old.example/toolinfo.json",
                source_kind="other_feed",
                sync_status=SYNC_ERROR,
            )
        )

    monkeypatch.setattr(
        toolinfo_sources,
        "official_crawler_url_rows",
        lambda: [
            {
                "id": 7,
                "url": "https://new.example/toolinfo.json",
                "createdBy": {"id": "9", "name": "Crawler admin"},
                "createdDate": "2026-07-28T12:00:00Z",
            },
            {
                "url": "https://wikitech.wikimedia.org/w/index.php?title=User:Ada/toolinfo&ctype=application%2Fjson",
                "created_by": "Ada",
                "created": "not a date",
            },
            {"url": ""},
        ],
    )
    assert toolinfo_sources.sync_registered_sources() == {"registered": 2, "skipped": 1}

    with db.session_scope() as s:
        sources = {source.url: source for source in s.query(ToolinfoSource).all()}
        source = sources["https://new.example/toolinfo.json"]
        assert source.url == "https://new.example/toolinfo.json"
        assert source.created_by_username == "Crawler admin"
        assert source.created_by_user_id == 9
        assert source.created_date is not None
        assert source.source == SOURCE_OFFICIAL
        assert source.sync_status == SYNC_ERROR
        wiki_source = sources[
            "https://wikitech.wikimedia.org/w/index.php?title=User:Ada/toolinfo&ctype=application%2Fjson"
        ]
        assert wiki_source.official_id is None
        assert wiki_source.source_kind == "wiki_raw"
        assert wiki_source.created_by_username == "Ada"
        assert wiki_source.created_date is None


def test_guard_and_fetch_helpers(monkeypatch):
    with pytest.raises(ValueError, match="only public"):
        toolinfo_sources._require_public_http("ftp://example.org/feed.json")
    monkeypatch.setattr(toolinfo_sources.socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(OSError("nx")))
    with pytest.raises(ValueError, match="cannot resolve"):
        toolinfo_sources._require_public_http("https://missing.example/feed.json")
    monkeypatch.setattr(
        toolinfo_sources.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        toolinfo_sources._require_public_http("https://private.example/feed.json")
    toolinfo_sources._require_public_http("https://hay.toolforge.org/toolinfo.json")
    toolinfo_sources._require_public_http("https://ia-upload.wmcloud.org/toolinfo.json")
    toolinfo_sources._require_public_http("https://tools-static.wmflabs.org/toolinfo-scraper/enwiki_userscripts.json")
    monkeypatch.setattr(
        toolinfo_sources.socket,
        "getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 80))],
    )
    toolinfo_sources._require_public_http("http://public.example/feed.json")
    monkeypatch.setattr(toolinfo_sources, "_require_public_http", lambda _url: None)
    session = FakeSession([FakeResp(b'{"name":"ok","title":"Ok","description":"d","url":"https://ok.example"}')])
    assert toolinfo_sources.fetch_toolinfo_feed_once("https://public.example/feed.json", session)["name"] == "ok"
    assert session.calls[0][1]["allow_redirects"] is False
    monkeypatch.setattr(toolinfo_sources.requests, "Session", lambda: FakeSession([FakeResp(b"[]")]))
    assert toolinfo_sources.fetch_toolinfo_feed_once("https://public.example/feed.json") == []
    with pytest.raises(ValueError, match="Location"):
        toolinfo_sources.fetch_toolinfo_feed_once("https://public.example/feed.json", FakeSession([FakeResp(status=302)]))
    redirect_session = FakeSession(
        [
            FakeResp(status=302, headers={"Location": "/final.json"}),
            FakeResp(b'[{"name":"next","title":"Next","description":"d","url":"https://next.example"}]'),
        ]
    )
    assert toolinfo_sources.fetch_toolinfo_feed_once("https://public.example/feed.json", redirect_session)[0]["name"] == "next"
    assert redirect_session.calls[1][0] == "https://public.example/final.json"
    monkeypatch.setattr(toolinfo_sources, "MAX_REDIRECTS", 0)
    with pytest.raises(ValueError, match="too many redirects"):
        toolinfo_sources.fetch_toolinfo_feed_once(
            "https://public.example/feed.json",
            FakeSession([FakeResp(status=302, headers={"Location": "/loop.json"})]),
        )
    monkeypatch.setattr(toolinfo_sources, "MAX_BODY_BYTES", 1)
    with pytest.raises(ValueError, match="larger than"):
        toolinfo_sources.fetch_toolinfo_feed_once("https://public.example/feed.json", FakeSession([FakeResp(b"{}")]))


def test_item_rows_accepts_valid_object_or_array_and_rejects_invalid():
    item = {"name": "a-tool", "title": "A", "description": "Desc", "url": "https://a.example"}
    assert toolinfo_sources._item_rows(item)[0]["tool_name"] == "a-tool"
    assert toolinfo_sources._item_rows([item, item, {"name": "bad"}, "bad"]) == [
        {"tool_name": "a-tool", "title": "A", "tool_url": "https://a.example", "payload": item}
    ]
    with pytest.raises(TypeError, match="JSON object or array"):
        toolinfo_sources._item_rows("bad")


def test_index_official_crawler_sources_stores_valid_invalid_and_error_rows(monkeypatch):
    feeds = {
        "https://valid.example/feed.json": [
            {
                "name": "valid-tool",
                "title": "Valid Tool",
                "description": "Valid",
                "url": "https://valid.example",
            },
            {
                "name": "valid-tool",
                "title": "Duplicate",
                "description": "Duplicate",
                "url": "https://duplicate.example",
            },
            {"name": "invalid-tool", "title": "Invalid"},
        ],
        "https://invalid.example/feed.json": [],
        "https://broken.example/feed.json": ValueError("feed failed"),
    }
    monkeypatch.setattr(
        toolinfo_sources,
        "official_crawler_url_rows",
        lambda: [{"id": index, "url": url} for index, url in enumerate(feeds, start=1)],
    )

    def fake_fetch(url, _session=None):
        value = feeds[url]
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(toolinfo_sources, "fetch_toolinfo_feed_once", fake_fetch)
    summary = toolinfo_sources.index_official_crawler_sources(limit=3)
    assert summary == {
        "registered": 3,
        "skipped": 0,
        "fetched": 3,
        "valid": 1,
        "invalid": 1,
        "errors": 1,
        "items": 1,
    }

    with db.session_scope() as s:
        sources = {source.url: source for source in s.query(ToolinfoSource).all()}
        assert sources["https://valid.example/feed.json"].status == "valid"
        assert sources["https://valid.example/feed.json"].item_count == 1
        assert sources["https://invalid.example/feed.json"].status == "invalid"
        assert sources["https://invalid.example/feed.json"].sync_status == SYNC_ERROR
        assert sources["https://broken.example/feed.json"].status == "error"
        assert sources["https://broken.example/feed.json"].last_error == "feed failed"
        item = s.query(ToolinfoSourceItem).one()
        assert item.tool_name == "valid-tool"
        assert item.source_url == "https://valid.example/feed.json"
        assert item.payload["description"] == "Valid"


def test_store_and_error_helpers_tolerate_missing_sources():
    toolinfo_sources._mark_source_error(404, "missing")
    assert toolinfo_sources._store_source_items(404, [{"tool_name": "x", "title": "x", "tool_url": "x", "payload": {}}]) == 0


def test_sources_for_tools_prefers_lowest_official_source_id_and_serializes():
    with db.session_scope() as s:
        slow = ToolinfoSource(
            official_id=None,
            url="https://later.example/feed.json",
            source_kind="other_feed",
            status="valid",
            valid=True,
            item_count=1,
        )
        fast = ToolinfoSource(
            official_id=2,
            url="https://toolsadmin.wikimedia.org/tools/toolinfo/v1.2/toolinfo.json",
            source_kind="toolsadmin",
            status="valid",
            valid=True,
            item_count=2880,
            created_by_username="Toolhub",
        )
        s.add_all([slow, fast])
        s.flush()
        s.add_all(
            [
                ToolinfoSourceItem(
                    tool_name="same-tool",
                    source_id=slow.id,
                    source_url=slow.url,
                    title="Later",
                    tool_url="https://later.example",
                ),
                ToolinfoSourceItem(
                    tool_name="same-tool",
                    source_id=fast.id,
                    source_url=fast.url,
                    title="Fast",
                    tool_url="https://fast.example",
                ),
            ]
        )

    assert toolinfo_sources.sources_for_tools([]) == {}
    payload = toolinfo_sources.sources_for_tools(["same-tool", "same-tool"])["same-tool"]
    assert payload["sourceLabel"] == "Toolsadmin feed"
    assert payload["sourceUrl"] == "https://toolsadmin.wikimedia.org/tools/toolinfo/v1.2/toolinfo.json"
    assert payload["source"] == SOURCE_OFFICIAL
    assert payload["syncStatus"] == SYNC_OFFICIAL


def test_job_main_reports_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("TOOLHUB_DB_URL", f"sqlite:///{tmp_path}/sources.sqlite3")
    monkeypatch.setenv("TOOLINFO_SOURCE_INDEX_LIMIT", "bad")
    monkeypatch.setattr(
        toolinfo_sources_job.toolinfo_sources,
        "index_official_crawler_sources",
        lambda limit=150: {
            "registered": limit,
            "skipped": 0,
            "fetched": 1,
            "valid": 1,
            "invalid": 0,
            "errors": 0,
            "items": 2,
        },
    )
    assert toolinfo_sources_job.main() == 0
    assert "limit=150 registered=150" in capsys.readouterr().out
    monkeypatch.setenv("TOOLINFO_SOURCE_INDEX_LIMIT", "3")
    assert toolinfo_sources_job.main() == 0
    assert "limit=3 registered=3" in capsys.readouterr().out
