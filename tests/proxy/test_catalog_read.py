# SPDX-License-Identifier: GPL-3.0-or-later
"""The public catalog request path is local, complete, and deterministic."""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import api_cache, canonical_tools, catalog_facets, catalog_read, db  # noqa: E402
from backend.models import (  # noqa: E402
    ApiCacheMeta,
    CanonicalToolCache,
    CatalogFacetValue,
    ToolCatalogSyncState,
    catalog_modified_at,
)


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()
    canonical_tools.upsert_records(
        [
            {
                "name": "alpha",
                "title": "Alpha editor",
                "description": "Edit Wikidata",
                "tool_type": "web-app",
                "modified_date": "2026-08-14T10:00:00Z",
            },
            {
                "name": "beta",
                "title": "Beta bot",
                "description": "Maintain Wikipedia",
                "tool_type": "bot",
                "modified_date": "2026-08-15T10:00:00Z",
            },
        ],
        source_url="https://toolhub.wikimedia.org/api/tools/?page=1",
    )
    with db.session_scope() as session:
        session.add(ToolCatalogSyncState(key=catalog_read.STATE_KEY, status="idle", snapshot_generation=7))
        session.add_all(
            [
                CatalogFacetValue(tool_name="alpha", field="tool_type", value="web-app", label="web-app"),
                CatalogFacetValue(tool_name="alpha", field="wiki", value="wikidata.org", label="wikidata.org"),
                CatalogFacetValue(tool_name="beta", field="tool_type", value="bot", label="bot"),
            ]
        )


def test_search_is_locally_filtered_paginated_ordered_and_faceted():
    payload = catalog_read.search_payload(
        {"tool_type__term": "web-app", "ordering": "-modified_date", "page": "1", "page_size": "12"}
    )

    assert payload["count"] == 1
    assert [row["name"] for row in payload["results"]] == ["alpha"]
    assert payload["facets"]["_filter_wiki"]["wiki"]["buckets"] == [{"key": "wikidata.org", "doc_count": 1}]
    assert payload["replica"]["upstreamOnRequest"] is False
    assert payload["replica"]["generation"] == 7


def test_recent_ordering_uses_replica_metadata():
    payload = catalog_read.search_payload({"ordering": "-modified_date", "page_size": "1"})

    assert payload["count"] == 2
    assert payload["results"][0]["name"] == "beta"


def test_card_search_skips_facets_and_returns_only_the_bounded_projection(monkeypatch):
    with db.session_scope() as session:
        row = session.get(CanonicalToolCache, "alpha")
        row.record = {**row.record, "detail_only_payload": "x" * 10_000}

    monkeypatch.setattr(catalog_read, "_facet_payload", lambda *_args: pytest.fail("facets must be deferred"))
    payload = catalog_read.search_payload({"q": "alpha", "page_size": "1", "view": "card", "include_facets": "false"})

    assert payload["canonical"] is True
    assert payload["facets"] == {}
    assert payload["results"][0]["name"] == "alpha"
    assert "detail_only_payload" not in payload["results"][0]


def test_unfiltered_facets_use_the_published_aggregate(monkeypatch):
    assert catalog_facets.rebuild_global_payload(force=True) > 0
    monkeypatch.setattr(
        catalog_read,
        "_facet_payload",
        lambda *_args: pytest.fail("global facets must not aggregate on the request path"),
    )

    payload = catalog_read.search_payload({"page_size": "1"})

    assert payload["facets"]["_filter_tool_type"]["tool_type"]["buckets"] == [
        {"key": "bot", "doc_count": 1},
        {"key": "web-app", "doc_count": 1},
    ]


def test_read_projection_fields_and_indexes_are_materialized():
    with db.session_scope() as session:
        beta = session.get(CanonicalToolCache, "beta")
        assert beta.card_record["name"] == "beta"
        assert beta.modified_at_sort.isoformat() == "2026-08-15T10:00:00"

    indexes = {index["name"] for index in db.inspect(db.engine()).get_indexes("catalog_facet_values")}
    assert "ix_catalog_facet_values_field_value_tool" in indexes


def test_collection_merge_uses_expired_database_rows_without_network():
    url = "https://toolhub.wikimedia.org/api/lists/?page_size=50&page=1"
    api_cache.put_success(
        url,
        api_cache.CacheableResponse(
            status=200,
            content_type="application/json",
            body=json.dumps({"results": [{"id": 1, "title": "Local list", "tools": []}]}).encode(),
        ),
        fresh_seconds=-10,
        stale_if_error_seconds=0,
    )

    payload = catalog_read.collection_payload("/api/lists/", {"page_size": "30"})

    assert payload["count"] == 1
    assert payload["results"][0]["title"] == "Local list"
    assert catalog_read.list_payload("1")["title"] == "Local list"


def test_get_local_returns_expired_row_but_normal_cache_read_does_not():
    url = "https://toolhub.wikimedia.org/api/schema/"
    api_cache.put_success(
        url,
        api_cache.CacheableResponse(status=200, content_type="application/json", body=b'{"openapi":"3"}'),
        fresh_seconds=-10,
        stale_if_error_seconds=0,
    )

    assert api_cache.get(url, allow_stale=True) is None
    assert api_cache.get_local(url).body == b'{"openapi":"3"}'


def test_search_covers_ordering_and_bidirectional_pagination():
    first = catalog_read.search_payload({"ordering": "name", "page_size": "1"})
    second = catalog_read.search_payload({"ordering": "modified_date", "page": "2", "page_size": "1"})

    assert first["next"].endswith("page=2")
    assert second["previous"].endswith("page=1")
    assert second["results"][0]["name"] == "beta"


def test_local_payload_helpers_cover_present_and_missing_rows():
    assert catalog_read.tool_payload(" alpha ")["name"] == "alpha"
    assert catalog_read.tool_payload("missing") is None
    assert catalog_read.home_payload()["total_tools"] == 2
    assert catalog_read.cached_payload("https://missing.example") is None

    url = "https://toolhub.wikimedia.org/api/schema/"
    api_cache.put_success(url, api_cache.CacheableResponse(200, "application/json", b"{}"))
    assert catalog_read.cached_payload(url) == (b"{}", "application/json", 200)

    assert catalog_modified_at({"modified_date": "not-a-date"}) is None
    assert catalog_modified_at({"modified_date": "2026-08-15T10:00:00"}).isoformat() == "2026-08-15T10:00:00"


def test_collection_merge_rejects_malformed_rows_deduplicates_and_paginates(monkeypatch):
    responses = [
        api_cache.CachedResponse("bad", 200, "application/json", b"not-json", False, None, None),
        api_cache.CachedResponse("array", 200, "application/json", b"[]", False, None, None),
        api_cache.CachedResponse("shape", 200, "application/json", b'{"results":"wrong"}', False, None, None),
        api_cache.CachedResponse(
            "rows",
            200,
            "application/json",
            json.dumps(
                {
                    "results": [
                        "wrong",
                        {"id": 1, "featured": False},
                        {"id": 1, "featured": True},
                        {"title": "anonymous", "featured": True},
                        {"id": 2, "featured": True},
                    ]
                }
                ).encode(),
                False,
                None,
                None,
            ),
    ]
    monkeypatch.setattr(api_cache, "responses_for_path", lambda _path: responses)

    page = catalog_read.collection_payload("/api/lists/", {"featured": "true", "page": "2", "page_size": "1"})
    without_status = catalog_read.collection_payload("/api/lists/", {}, include_replica=False)

    assert page["count"] == 2
    assert page["previous"].endswith("page=1&page_size=1")
    assert page["results"] == [{"id": 2, "featured": True}]
    assert "replica" not in without_status


def test_facet_cache_rejects_invalid_envelopes_and_caps_buckets(monkeypatch):
    with db.session_scope() as session:
        session.add(ApiCacheMeta(key=catalog_facets.CACHE_KEY, value="not-json"))
    with db.session_scope() as session:
        assert catalog_facets.cached_global_payload(session) is None
        session.get(ApiCacheMeta, catalog_facets.CACHE_KEY).value = '{"version":0,"facets":{}}'
    with db.session_scope() as session:
        assert catalog_facets.cached_global_payload(session) is None

    rows = [("tool_type", str(index), str(index), 1) for index in range(catalog_facets.FACET_BUCKET_LIMIT + 1)]
    payload = catalog_facets.payload_from_rows(rows)
    assert len(payload["_filter_tool_type"]["tool_type"]["buckets"]) == catalog_facets.FACET_BUCKET_LIMIT

    @contextmanager
    def locked_out(*_args, **_kwargs):
        yield False

    monkeypatch.setattr(db, "advisory_lock", locked_out)
    assert catalog_facets.rebuild_global_payload() == 0
