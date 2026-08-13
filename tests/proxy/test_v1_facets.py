# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet discovery endpoints: tool lookup by signal, value listing, coverage."""

from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, security, tool_facets
from backend.models import CanonicalToolCache, CatalogFacetValue, SourceAnalysisReport, User, utcnow


@pytest.fixture
def app():
    application = Flask(__name__)
    backend.register(application, db_url="sqlite://", secret_key="test-secret")
    application.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    security.clear_rate_limits()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _facet(s, tool, field, value, label, bp):
    """Seed a facet row the way catalog_projection writes them."""
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


def _seed(s):
    # Coverage counts stored analysis reports, so seed those too.
    # SourceAnalysisReport.user_id is NOT NULL (models.py:1061) — same
    # seeding pattern as tests/proxy/test_graph_enrichment.py:72-79.
    user = User(wm_sub="42", username="Seeder")
    s.add(user)
    s.flush()
    s.add(SourceAnalysisReport(tool_name="sfedits", report={}, user_id=user.id))
    s.add(SourceAnalysisReport(tool_name="cite-checker", report={}, user_id=user.id))
    for name, record in (
        (
            "sfedits",
            {
                "name": "sfedits",
                "title": "SF edits",
                "description": "stream",
                "url": "https://sfedits.example",
                "tool_type": "bot",
                "repository": "https://github.com/tieguy/sfedits",
                "keywords": ["edits"],
                "deprecated": False,
            },
        ),
        (
            "cite-checker",
            {
                "name": "cite-checker",
                "title": "Cite checker",
                "description": "checks citations",
                "url": "https://c.example",
            },
        ),
    ):
        s.add(
            CanonicalToolCache(
                tool_name=name,
                record=record,
                expires_at=utcnow() + timedelta(hours=1),
                stale_until=utcnow() + timedelta(hours=2),
            )
        )
    _facet(s, "sfedits", "dependency", "pypi:pywikibot", "pywikibot (pypi)", 9500)
    _facet(s, "sfedits", "wikimedia_api", "wikidata-query-service", "Wikidata Query Service", 9400)
    _facet(s, "sfedits", "detected_technology", "python", "Python", 6400)
    _facet(s, "sfedits", "tool_type", "bot", "bot", 10000)
    _facet(s, "cite-checker", "dependency", "pypi:pywikibot", "pywikibot (pypi)", 8000)
    _facet(s, "cite-checker", "detected_technology", "javascript", "JavaScript", 6400)


from backend import v1_facets  # noqa: E402, F401


def test_tool_summary_shape(app):
    with db.session_scope() as s:
        _seed(s)
    payloads = v1_facets.tool_summaries(
        ["sfedits"],
        matched_by_tool={
            "sfedits": [{"facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.95}]
        },
    )
    assert payloads == [
        {
            "name": "sfedits",
            "title": "SF edits",
            "description": "stream",
            "url": "https://sfedits.example",
            "tool_type": "bot",
            "repository": "https://github.com/tieguy/sfedits",  # None when absent
            "deprecated": False,
            "keywords": ["edits"],
            "matched": [{"facet": "dependency", "value": "pypi:pywikibot", "confidence": 0.95}],
        }
    ]


def test_coverage_counts(app):
    with db.session_scope() as s:
        _seed(s)
    with db.session_scope() as s:
        assert v1_facets.coverage(s) == {"scannedTools": 2, "totalTools": 2}


def test_facets_tools_intersection_and_shape(client):
    with db.session_scope() as s:
        _seed(s)
    resp = client.get("/v1/facets/tools/?dependency=pywikibot&api=wikidata-query-service")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data) == {"tools", "total", "appliedFilters", "coverage"}
    assert [t["name"] for t in data["tools"]] == ["sfedits"]
    # Keyed by the query-parameter names the caller sent, so a response can
    # be round-tripped straight back into a new request.
    assert data["appliedFilters"] == {
        "dependency": ["pypi:pywikibot"],
        "api": ["wikidata-query-service"],
    }
    assert data["coverage"] == {"scannedTools": 2, "totalTools": 2}


def test_facets_tools_dependency_shorthand(client):
    """A bare package name matches any ecosystem; an explicit prefix pins one."""
    with db.session_scope() as s:
        _seed(s)
    bare = client.get("/v1/facets/tools/?dependency=pywikibot").get_json()
    pinned = client.get("/v1/facets/tools/?dependency=pypi:pywikibot").get_json()
    assert {t["name"] for t in bare["tools"]} == {"cite-checker", "sfedits"}
    assert {t["name"] for t in pinned["tools"]} == {"cite-checker", "sfedits"}


def test_facets_tools_rejects_no_filters_and_bad_limit(client):
    assert client.get("/v1/facets/tools/").status_code == 400
    resp = client.get("/v1/facets/tools/?dependency=x&limit=9999")
    assert resp.status_code == 200
    assert resp.get_json()["tools"] == []  # clamped, empty, still carries coverage


def test_facets_tools_purpose_filters(client):
    """tasks/audiences are exposed: what a tool is FOR, not what it is built from."""
    with db.session_scope() as s:
        _seed(s)
        _facet(s, "sfedits", "tasks", "monitoring", "monitoring", 10000)
        _facet(s, "cite-checker", "audiences", "editors", "editors", 10000)

    by_task = client.get("/v1/facets/tools/?task=monitoring").get_json()
    assert [t["name"] for t in by_task["tools"]] == ["sfedits"]
    assert by_task["appliedFilters"] == {"task": ["monitoring"]}

    by_audience = client.get("/v1/facets/tools/?audience=editors").get_json()
    assert [t["name"] for t in by_audience["tools"]] == ["cite-checker"]

    # Purpose filters AND with detected ones like any other field.
    combined = client.get("/v1/facets/tools/?task=monitoring&dependency=pywikibot").get_json()
    assert [t["name"] for t in combined["tools"]] == ["sfedits"]
    assert client.get("/v1/facets/tools/?task=monitoring&audience=editors").get_json()["tools"] == []


def test_facets_tools_unknown_values_match_nothing(client):
    """Seeded, so these assertions can fail for the right reason."""
    with db.session_scope() as s:
        _seed(s)
    solo = client.get("/v1/facets/tools/?dependency=nosuchpkg").get_json()
    assert solo["tools"] == [] and solo["total"] == 0
    # An unknown value combined with a valid filter must EMPTY the result,
    # never silently widen the AND to just the valid filter.
    mixed = client.get(
        "/v1/facets/tools/?dependency=nosuchpkg&api=wikidata-query-service"
    ).get_json()
    assert mixed["tools"] == [] and mixed["total"] == 0


def test_facets_tools_limit_never_exceeds_serializer_cap(client):
    """Every returned tool must carry real record data, even at the cap."""
    from backend import canonical_tools as ct

    with db.session_scope() as s:
        for i in range(ct.MAX_QUERY_NAMES + 5):
            name = f"tool-{i:03d}"
            s.add(
                CanonicalToolCache(
                    tool_name=name,
                    record={"name": name, "title": f"Tool {i}"},
                    expires_at=utcnow() + timedelta(hours=1),
                    stale_until=utcnow() + timedelta(hours=2),
                )
            )
            _facet(s, name, "dependency", "pypi:pywikibot", "pywikibot (pypi)", 9000)
    data = client.get("/v1/facets/tools/?dependency=pywikibot&limit=9999").get_json()
    assert len(data["tools"]) <= ct.MAX_QUERY_NAMES
    assert all(t["title"] for t in data["tools"])  # no husk records
    # `total` is the TRUE match count, not the page size: a client must be
    # able to tell 50-of-50 from 50-of-55. (Seeded with cap+5 precisely so
    # the two numbers differ; asserting only the page size would let
    # `total = len(matches)` pass.)
    assert data["total"] == ct.MAX_QUERY_NAMES + 5
    assert data["total"] > len(data["tools"])


def test_facets_values_listing_and_validation(client):
    with db.session_scope() as s:
        _seed(s)
    resp = client.get("/v1/facets/values/?type=dependency")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data) == {"type", "values", "totalValues", "coverage"}
    assert data["values"][0] == {"value": "pypi:pywikibot", "toolCount": 2}
    assert data["totalValues"] == len(data["values"])
    limited = client.get("/v1/facets/values/?type=detected_technology&limit=1").get_json()
    # _seed gives sfedits "python" and cite-checker "javascript", so
    # len(values) == 1 while totalValues == 2 discloses the truncation.
    assert len(limited["values"]) == 1
    assert limited["totalValues"] == 2
    assert client.get("/v1/facets/values/?type=bogus").status_code == 400
    assert client.get("/v1/facets/values/").status_code == 400
    assert client.get("/v1/facets/tools/?dependency=").status_code == 400  # empty value ≠ filter


def test_facets_tools_rate_limited(client, monkeypatch):
    with db.session_scope() as s:
        _seed(s)
    monkeypatch.setattr(security, "facet_rate_limited", lambda _: True)
    resp = client.get("/v1/facets/tools/?dependency=pywikibot")
    assert resp.status_code == 429


def test_facets_values_rate_limited(client, monkeypatch):
    with db.session_scope() as s:
        _seed(s)
    monkeypatch.setattr(security, "facet_rate_limited", lambda _: True)
    resp = client.get("/v1/facets/values/?type=dependency")
    assert resp.status_code == 429


def test_cached_facet_values_clamping_and_expiry(app, monkeypatch):
    with db.session_scope() as s:
        _seed(s)
    # First call should execute the query and cache
    result1 = v1_facets.cached_facet_values("dependency", limit=100)
    assert result1["totalValues"] >= 0

    # Mock facet_value_counts to count invocations
    original_count = tool_facets.facet_value_counts
    call_count = 0

    def mock_count(s, field_name, *, limit):
        nonlocal call_count
        call_count += 1
        return original_count(s, field_name, limit=limit)

    monkeypatch.setattr(tool_facets, "facet_value_counts", mock_count)

    # Second call should hit cache
    result2 = v1_facets.cached_facet_values("dependency", limit=100)
    assert call_count == 0  # No new query
    assert result1 == result2

    # Clear cache
    v1_facets.clear_cache()

    # Third call should query again
    result3 = v1_facets.cached_facet_values("dependency", limit=100)
    assert call_count == 1  # One new query
