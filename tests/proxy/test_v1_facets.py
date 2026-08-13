# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet discovery endpoints: tool lookup by signal, value listing, coverage."""

from datetime import timedelta

import pytest
from flask import Flask

import backend
from backend import db, security
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
