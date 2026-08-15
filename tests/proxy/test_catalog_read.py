# SPDX-License-Identifier: GPL-3.0-or-later
"""The public catalog request path is local, complete, and deterministic."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import api_cache, canonical_tools, catalog_facets, catalog_read, db  # noqa: E402
from backend.models import CanonicalToolCache, CatalogFacetValue, ToolCatalogSyncState  # noqa: E402


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
