# SPDX-License-Identifier: GPL-3.0-or-later
"""The storage/public facet-name boundary, checked at every crossing.

Storage field names are internal and free to change; public facet names are
what clients see. These tests hold that line on the request side, the response
side, and the value-listing side at once, because the boundary previously
existed only on the request side and the other two leaked storage names.
"""

import json
from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, facet_names, security, v1_facets
from backend.models import CanonicalToolCache, CatalogFacetValue, utcnow


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    v1_facets.clear_cache()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _facet(s, tool, field, value, label, bp=9000):
    s.add(
        CatalogFacetValue(
            tool_name=tool,
            field=field,
            value=value.casefold(),
            label=label,
            provenance=[{"source": "repository_analysis"}],
            confidence_basis_points=bp,
            refreshed_at=utcnow(),
        )
    )


@pytest.fixture(autouse=True)
def seeded(app):
    """One tool carrying a facet in every stored field, including the orphans."""
    with app.app_context(), db.session_scope() as s:
        s.add(
            CanonicalToolCache(
                tool_name="sfedits",
                record={"name": "sfedits", "title": "SF edits", "url": "https://sfedits.example"},
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )
        _facet(s, "sfedits", "dependency", "npm:m3api", "m3api (npm)")
        _facet(s, "sfedits", "wikimedia_api", "mediawiki-action-api", "MediaWiki Action API")
        _facet(s, "sfedits", "detected_technology", "javascript", "JavaScript")
        _facet(s, "sfedits", "technology", "node.js", "Node.js")
        _facet(s, "sfedits", "keywords", "bot", "bot")
        _facet(s, "sfedits", "tasks", "monitoring", "monitoring")
        _facet(s, "sfedits", "audiences", "readers", "readers")
        _facet(s, "sfedits", "ui_language", "en", "English")
        _facet(s, "sfedits", "wiki", "en.wikipedia.org", "en.wikipedia.org")
        _facet(s, "sfedits", "tool_type", "bot", "bot")
        _facet(s, "sfedits", "license", "mit", "MIT")


def _call_tool(client, name, arguments):
    body = {"jsonrpc": "2.0", "method": "tools/call", "id": 1, "params": {"name": name, "arguments": arguments}}
    return client.post("/mcp", json=body).get_json()["result"]


# --- the value-listing crossing ------------------------------------------


def test_list_facet_values_accepts_public_names(client):
    for public in sorted(facet_names.PUBLIC_TO_STORAGE):
        result = _call_tool(client, "list_facet_values", {"type": public})
        assert not result.get("isError"), f"{public} rejected: {result}"
        assert result["structuredContent"]["type"] == public


def test_list_facet_values_rejects_storage_only_names(client):
    for storage_only in sorted(facet_names.STORAGE_ONLY_NAMES):
        result = _call_tool(client, "list_facet_values", {"type": storage_only})
        assert result.get("isError"), f"{storage_only} should not be a public type"


def test_rest_values_endpoint_uses_the_same_public_names(client):
    assert client.get("/v1/facets/values/?type=api").status_code == 200
    assert client.get("/v1/facets/values/?type=wikimedia_api").status_code == 400


# --- the response crossing ------------------------------------------------


def test_matched_facets_are_reported_under_public_names(client):
    result = _call_tool(client, "facet_tools", {"api": ["mediawiki-action-api"], "keyword": ["bot"]})
    matched = result["structuredContent"]["tools"][0]["matched"]
    assert {m["facet"] for m in matched} == {"api", "keyword"}


# --- the orphaned fields --------------------------------------------------


def test_declared_technology_is_reachable_and_distinct_from_detected(client):
    declared = _call_tool(client, "facet_tools", {"technology": ["node.js"]})
    assert declared["structuredContent"]["total"] == 1
    detected = _call_tool(client, "facet_tools", {"detected_technology": ["javascript"]})
    assert detected["structuredContent"]["total"] == 1
    # Same tool, two different assertions: one claimed, one found in source.
    assert _call_tool(client, "facet_tools", {"technology": ["javascript"]})["structuredContent"]["total"] == 0


def test_ui_language_is_reachable(client):
    result = _call_tool(client, "facet_tools", {"ui_language": ["en"]})
    assert result["structuredContent"]["total"] == 1


# --- the invariant --------------------------------------------------------


def _facet_names_in(payload, found=None):
    """Collect every string in a payload that sits in a facet-naming position.

    A blanket substring scan cannot work here: `keywords`, `tasks`, and
    `audiences` are also upstream toolinfo field names, and the projection
    endpoint publishes those legitimately because matching Toolhub's schema is
    its contract. So this walks the four positions where *this* API names a
    facet — a `facet` key, a `type` key, `appliedFilters` keys, and JSON-Schema
    `properties` keys — and ignores everything else.

    A new surface that names facets through one of those conventions is covered
    automatically. One that invents a fifth position is not, and must add it
    here; that is a deliberately small, visible cost.
    """
    found = found if found is not None else set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"facet", "type"} and isinstance(value, str):
                found.add(value)
            elif key in {"appliedFilters", "properties"} and isinstance(value, dict):
                found.update(value.keys())
            _facet_names_in(value, found)
    elif isinstance(payload, list):
        for item in payload:
            _facet_names_in(item, found)
    return found


def test_no_storage_only_name_appears_in_any_public_response(client):
    """The guard that generalizes across surfaces rather than per assertion."""
    payloads = [
        client.get("/v1/facets/tools/?keyword=bot").get_json(),
        client.get("/v1/facets/values/?type=task").get_json(),
        # Included to prove the walk does NOT false-positive on the upstream
        # toolinfo vocabulary this endpoint is contractually required to echo.
        client.get("/v1/catalog/tools/sfedits/projection/").get_json(),
        _call_tool(client, "facet_tools", {"keyword": ["bot"], "task": ["monitoring"]}),
        _call_tool(client, "list_facet_values", {"type": "audience"}),
        client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1}).get_json(),
    ]
    for payload in payloads:
        leaked = _facet_names_in(payload) & facet_names.STORAGE_ONLY_NAMES
        assert not leaked, f"storage names {sorted(leaked)} leaked into a public response: {json.dumps(payload)[:400]}"
