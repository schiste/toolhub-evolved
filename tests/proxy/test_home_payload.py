# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the composed landing-page payload."""

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import api_cache, db, home_payload  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state():
    """Every test gets a clean shared cache and a clean per-worker cache."""
    db.configure("sqlite://")
    db.init_schema()
    api_cache.clear()
    home_payload._CACHE.clear()
    yield
    home_payload._CACHE.clear()


def _put_shared(payload_dict, **kwargs):
    body = json.dumps(payload_dict).encode("utf-8")
    api_cache.put_success(
        home_payload._cache_url(),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=body),
        **kwargs,
    )


# --- _cache_url -----------------------------------------------------------


def test_cache_url_is_stable_and_carries_the_version():
    url = home_payload._cache_url()
    assert url == f"https://toolhub-evolved.local/v1/home/?version={home_payload.HOME_CACHE_VERSION}"
    assert home_payload._cache_url() == url


# --- _results ---------------------------------------------------------------


def test_results_returns_empty_for_non_dict_payload():
    assert home_payload._results("not a dict") == []
    assert home_payload._results(None) == []


def test_results_returns_empty_when_results_key_missing_or_not_a_list():
    assert home_payload._results({}) == []
    assert home_payload._results({"results": "not-a-list"}) == []


def test_results_filters_out_non_dict_rows():
    payload = {"results": [{"a": 1}, "skip-me", 3, {"b": 2}]}
    assert home_payload._results(payload) == [{"a": 1}, {"b": 2}]


# --- _tool_names --------------------------------------------------------------


def test_tool_names_dedupes_preserves_order_and_skips_blank():
    tools = [
        {"name": "Alpha"},
        {"name": "  "},
        {"name": "Alpha"},
        {},
        {"name": "Beta"},
    ]
    assert home_payload._tool_names(tools) == ["Alpha", "Beta"]


# --- _featured_lists ------------------------------------------------------------


def test_featured_lists_requests_the_featured_page_and_filters_rows(monkeypatch):
    captured = {}

    def fake(path, params, *, include_replica):
        captured["path"] = path
        captured["params"] = params
        captured["include_replica"] = include_replica
        return {"results": [{"id": "1"}, "bad"]}

    monkeypatch.setattr(home_payload.catalog_read, "collection_payload", fake)
    result = home_payload._featured_lists()

    assert result == [{"id": "1"}]
    assert captured["path"] == "/api/lists/"
    assert captured["params"] == {"featured": "true", "page_size": home_payload.FEATURED_LIST_COUNT}
    assert captured["include_replica"] is False


# --- _recent_tools --------------------------------------------------------------


def test_recent_tools_requests_the_modified_ordering(monkeypatch):
    captured = {}

    def fake(params):
        captured["params"] = params
        return {"results": [{"name": "Recent"}]}

    monkeypatch.setattr(home_payload.catalog_read, "search_payload", fake)
    result = home_payload._recent_tools()

    assert result == [{"name": "Recent"}]
    assert captured["params"] == {
        "ordering": "-modified_date",
        "page_size": home_payload.RECENT_TOOL_COUNT,
        "include_facets": "false",
        "view": "card",
    }


# --- _memberships -----------------------------------------------------------------


def test_memberships_walks_pages_filters_rows_and_stops_without_next(monkeypatch):
    pages = {
        1: {
            "results": [
                {
                    "id": 1,
                    "title": "Public List",
                    "published": True,
                    "tools": [
                        {"name": "Alpha"},
                        {"name": ""},
                        "not-a-dict",
                        None,
                    ],
                },
                {
                    "published": False,
                    "tools": [{"name": "Alpha"}],
                },
                {
                    # no "id" and no "title" -> default fallbacks
                    "published": True,
                    "tools": [{"name": "Beta"}],
                },
            ],
            "next": "https://example/page2",
        },
        2: {"results": [], "next": None},
    }

    def fake(_path, params, *, include_replica):
        assert include_replica is False
        page = params["page"]
        return pages.get(page, {"results": [], "next": None})

    monkeypatch.setattr(home_payload.catalog_read, "collection_payload", fake)
    result = home_payload._memberships()

    assert result == {
        "Alpha": [{"id": "1", "title": "Public List"}],
        "Beta": [{"id": "", "title": "Untitled list"}],
    }


def test_memberships_stops_when_a_page_returns_no_rows_immediately(monkeypatch):
    monkeypatch.setattr(
        home_payload.catalog_read,
        "collection_payload",
        lambda *_a, **_k: {"results": [], "next": True},
    )
    assert home_payload._memberships() == {}


def test_memberships_exhausts_the_page_budget_without_a_next_marker(monkeypatch):
    calls = []

    def fake(_path, params, *, include_replica):
        assert include_replica is False
        page = params["page"]
        calls.append(page)
        return {
            "results": [{"id": page, "title": f"List {page}", "published": True, "tools": [{"name": "Alpha"}]}],
            "next": "more",
        }

    monkeypatch.setattr(home_payload.catalog_read, "collection_payload", fake)
    result = home_payload._memberships()

    assert calls == list(range(1, home_payload.MEMBERSHIP_MAX_PAGES + 1))
    assert len(result["Alpha"]) == home_payload.MEMBERSHIP_MAX_PAGES


# --- build --------------------------------------------------------------------------


def test_build_composes_payload_from_its_helpers(monkeypatch):
    monkeypatch.setattr(home_payload, "_featured_lists", lambda: [{"tools": [{"name": "Alpha"}, "bad"]}])
    monkeypatch.setattr(home_payload, "_recent_tools", lambda: [{"name": "Beta"}])
    monkeypatch.setattr(home_payload, "_memberships", lambda: {"Alpha": [{"id": "1", "title": "L"}]})
    monkeypatch.setattr(home_payload.catalog_read, "replica_status", lambda: {"recordCount": 99})

    class FakeRead:
        results = {"Alpha": {"summary": "x"}}

    seen_names = {}

    def fake_summaries_for(names):
        seen_names["names"] = names
        return FakeRead()

    result = home_payload.build(fake_summaries_for)

    assert seen_names["names"] == ["Alpha", "Beta"]
    assert result["totalTools"] == 99
    assert result["lists"] == [{"tools": [{"name": "Alpha"}, "bad"]}]
    assert result["recentTools"] == [{"name": "Beta"}]
    assert result["summaries"] == {"Alpha": {"summary": "x"}}
    assert result["endorsements"] == {"Alpha": [{"id": "1", "title": "L"}], "Beta": []}
    assert result["source"] == "local"
    assert "cachePolicy" in result


# --- _remember / _remembered ---------------------------------------------------------


def test_remembered_is_none_when_nothing_stored():
    assert home_payload._remembered() is None


def test_remember_then_remembered_round_trips():
    home_payload._remember({"lists": []})
    assert home_payload._remembered() == {"lists": []}


def test_remembered_is_none_once_expired():
    home_payload._remember({"lists": []})
    home_payload._CACHE["expires_at"] = home_payload.utcnow() - timedelta(seconds=1)
    assert home_payload._remembered() is None


# --- _shared -----------------------------------------------------------------------


def test_shared_is_none_when_nothing_cached():
    assert home_payload._shared() is None


def test_shared_is_none_for_invalid_json_body():
    api_cache.put_success(
        home_payload._cache_url(),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=b"not json"),
    )
    assert home_payload._shared() is None


def test_shared_is_none_for_undecodable_body_bytes():
    api_cache.put_success(
        home_payload._cache_url(),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=b"\xff\xfe\xfa"),
    )
    assert home_payload._shared() is None


def test_shared_is_none_when_payload_shape_is_wrong():
    _put_shared({"no": "lists-key"})
    assert home_payload._shared() is None

    body = json.dumps(["not", "a", "dict"]).encode("utf-8")
    api_cache.put_success(
        home_payload._cache_url(),
        api_cache.CacheableResponse(status=200, content_type="application/json", body=body),
    )
    assert home_payload._shared() is None


def test_shared_returns_the_stored_payload_when_valid():
    _put_shared({"lists": [], "other": 1})
    assert home_payload._shared() == {"lists": [], "other": 1}


def test_shared_passes_allow_stale_through_to_the_cache_read(monkeypatch):
    captured = {}

    def fake_get(_url, *, allow_stale=False):
        captured["allow_stale"] = allow_stale
        return None

    monkeypatch.setattr(api_cache, "get", fake_get)
    home_payload._shared(allow_stale=True)
    assert captured["allow_stale"] is True


# --- payload -----------------------------------------------------------------------


def test_payload_returns_the_remembered_copy_without_building(monkeypatch):
    home_payload._remember({"lists": ["remembered"]})

    def fail_build(_summaries_for):
        raise AssertionError("build should not run when a fresh per-worker copy exists")

    monkeypatch.setattr(home_payload, "build", fail_build)
    assert home_payload.payload(lambda _names: None) == {"lists": ["remembered"]}


def test_payload_uses_the_shared_cache_and_remembers_it(monkeypatch):
    _put_shared({"lists": ["shared"]})

    def fail_build(_summaries_for):
        raise AssertionError("build should not run when the shared cache has a row")

    monkeypatch.setattr(home_payload, "build", fail_build)
    result = home_payload.payload(lambda _names: None)

    assert result == {"lists": ["shared"]}
    assert home_payload._remembered() == {"lists": ["shared"]}


def test_payload_builds_and_populates_both_caches_when_nothing_stored(monkeypatch):
    composed = {"lists": ["built"]}
    monkeypatch.setattr(home_payload, "build", lambda _summaries_for: composed)

    result = home_payload.payload(lambda _names: None)

    assert result == composed
    assert home_payload._remembered() == composed
    home_payload._CACHE.clear()
    assert home_payload._shared() == composed


def test_payload_falls_back_to_stale_shared_copy_on_build_failure(monkeypatch):
    _put_shared({"lists": ["stale"]}, fresh_seconds=-1, stale_if_error_seconds=3600)

    def boom(_summaries_for):
        raise RuntimeError("upstream unreachable")

    monkeypatch.setattr(home_payload, "build", boom)
    result = home_payload.payload(lambda _names: None)

    assert result == {"lists": ["stale"]}
    assert home_payload._remembered() == {"lists": ["stale"]}


def test_payload_raises_when_build_fails_and_nothing_is_stale(monkeypatch):
    def boom(_summaries_for):
        raise RuntimeError("upstream unreachable")

    monkeypatch.setattr(home_payload, "build", boom)
    with pytest.raises(RuntimeError, match="upstream unreachable"):
        home_payload.payload(lambda _names: None)


# --- invalidate --------------------------------------------------------------------


def test_invalidate_clears_both_the_local_and_shared_caches():
    home_payload._remember({"lists": []})
    _put_shared({"lists": []})

    removed = home_payload.invalidate()

    assert removed == 1
    assert home_payload._CACHE == {}
    assert home_payload._shared() is None
