"""Integration tests for the Evolved-local catalog projection."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import catalog_projection, catalog_validation, db, outbound  # noqa: E402
from backend.models import (  # noqa: E402
    CanonicalToolCache,
    CatalogCuration,
    CatalogFacetValue,
    CatalogToolProjection,
    SourceAnalysisReport,
    ToolinfoDiscovery,
    ToolinfoSource,
    ToolinfoSourceItem,
    User,
    utcnow,
)
from backend.sync import REVIEW_APPROVED  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    db.configure("sqlite://")
    db.init_schema()


def _canonical(name, **fields):
    now = utcnow()
    return CanonicalToolCache(
        tool_name=name,
        record={"name": name, "title": "Official title", **fields},
        source_url=f"https://toolhub.wikimedia.org/api/tools/{name}/",
        fetched_at=now,
        expires_at=now,
        stale_until=now,
    )


def test_projection_preserves_invalid_official_evidence_and_merges_valid_sources():
    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("alpha", url="javascript:alert(1)", technology_used=["Python"]))
        source = ToolinfoSource(url="https://alpha.example/toolinfo.json", valid=True, last_fetched_at=now)
        s.add(source)
        s.flush()
        s.add(
            ToolinfoSourceItem(
                tool_name="alpha",
                source_id=source.id,
                source_url=source.url,
                payload={"url": "https://alpha.example", "technology_used": ["Django"]},
                last_seen_at=now,
            )
        )

    summary = catalog_projection.refresh_tool_names(["alpha"])

    assert summary == {"requested": 1, "refreshed": 1, "changed": 1, "errors": 0}
    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["url"] == "https://alpha.example"
    assert payload["record"]["technology_used"] == ["Python", "Django"]
    assert payload["provenance"]["url"][0]["valid"] is False
    assert payload["provenance"]["url"][0]["effective"] is False
    assert payload["validation"]["url"]["invalidEvidenceCount"] == 1
    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).all()}
    assert facets >= {("technology", "python"), ("technology", "django")}


def test_approved_curation_is_only_source_that_replaces_valid_canonical_scalar():
    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("alpha", url="https://official.example"))
        user = User(wm_sub="reviewer", username="Reviewer")
        s.add(user)
        s.flush()
        s.add(
            CatalogCuration(
                tool_name="alpha",
                created_by_user_id=user.id,
                reviewed_by_user_id=user.id,
                patch={"url": "https://corrected.example"},
                rationale="Official URL is obsolete.",
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["alpha"])

    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["url"] == "https://corrected.example"
    evidence = payload["provenance"]["url"]
    assert [item["source"] for item in evidence] == ["official_toolhub", "evolved_curation"]
    assert [item["effective"] for item in evidence] == [False, True]


def test_discovered_toolinfo_must_match_the_declared_tool_origin():
    with db.session_scope() as s:
        s.add(_canonical("alpha", technology_used=["Python"]))
        s.add(
            ToolinfoDiscovery(
                tool_name="alpha",
                tool_url="https://different.example",
                toolinfo_url="https://alpha.example/toolinfo.json",
                status="found",
                payload={"url": "https://different.example", "technology_used": ["Injected"]},
                checked_at=utcnow(),
            )
        )

    catalog_projection.refresh_tool_names(["alpha"])

    payload = catalog_projection.projection_payload("alpha")
    assert payload["record"]["technology_used"] == ["Python"]
    assert "self_hosted_toolinfo" not in payload["sourceTimestamps"]


def test_validate_curation_patch_bounds_fields_and_urls():
    patch, errors = catalog_projection.validate_curation_patch(
        {"name": "renamed", "url": "javascript:alert(1)", "keywords": ["one", "one", "two"]}
    )

    assert patch == {"keywords": ["one", "two"]}
    assert {item["field"] for item in errors} == {"name", "url"}


def test_candidate_repair_is_versioned_and_idempotent():
    with db.session_scope() as s:
        s.add(_canonical("alpha"))

    first = catalog_projection.refresh_candidates()
    second = catalog_projection.refresh_candidates()

    assert first["candidates"] == 1
    assert first["refreshed"] == 1
    assert second == {"candidates": 0, "requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    with db.session_scope() as s:
        assert s.get(CatalogToolProjection, "alpha").status == catalog_projection.STATUS_READY


def test_background_url_validation_survives_unchanged_projection_refresh(monkeypatch):
    with db.session_scope() as s:
        s.add(_canonical("alpha", url="https://alpha.example", repository="https://code.example/alpha"))
    catalog_projection.refresh_tool_names(["alpha"])
    monkeypatch.setattr(
        outbound,
        "probe_reachable",
        lambda _session, url, *, caller: outbound.ProbeResponse(url=url, status_code=200, content_type="text/html"),
    )

    summary = catalog_validation.refresh_candidates()
    catalog_projection.refresh_tool_names(["alpha"])

    assert summary == {"candidates": 2, "processed": 2, "reachable": 2, "errors": 0}
    payload = catalog_projection.projection_payload("alpha")
    assert payload["validation"]["url"]["reachable"] is True
    assert payload["validation"]["url"]["checkedValue"] == "https://alpha.example"


def test_analyzer_facets_dependency_row_emitted_with_preserved_label():
    """Analyzer dependencies should be emitted as facet rows."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("beta", technology_used=["Python"]))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="beta",
                source_label="https://code.example/beta",
                report={
                    "dependencies": [
                        {
                            "value": "pypi:pywikibot",
                            "label": "PyWikiBot",
                            "confidence": 0.95,
                        }
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["beta"])

    with db.session_scope() as s:
        facets = {(row.field, row.value, row.label, row.confidence_basis_points)
                  for row in s.query(CatalogFacetValue).filter_by(tool_name="beta").all()}
    assert ("dependency", "pypi:pywikibot", "PyWikiBot", 9500) in facets


def test_analyzer_facets_wikimedia_api_row_emitted():
    """Analyzer APIs should be emitted as wikimedia_api facet rows."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("gamma"))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="gamma",
                source_label="https://code.example/gamma",
                report={
                    "apis": [
                        {
                            "value": "wikidata-query-service",
                            "label": "Wikidata Query Service",
                            "confidence": 0.85,
                        }
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["gamma"])

    with db.session_scope() as s:
        facets = {(row.field, row.value, row.label, row.confidence_basis_points)
                  for row in s.query(CatalogFacetValue).filter_by(tool_name="gamma").all()}
    assert ("wikimedia_api", "wikidata-query-service", "Wikidata Query Service", 8500) in facets


def test_analyzer_facets_detected_technology_casefolded():
    """Analyzer technology should be casefolded, label preserved."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("delta"))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="delta",
                source_label="https://code.example/delta",
                report={
                    "technology": [
                        {
                            "value": "Python",
                            "label": "Python",
                            "confidence": 0.92,
                        }
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["delta"])

    with db.session_scope() as s:
        facets = {(row.field, row.value, row.label)
                  for row in s.query(CatalogFacetValue).filter_by(tool_name="delta").all()}
    assert ("detected_technology", "python", "Python") in facets


def test_analyzer_facets_provenance_identifies_repository_analysis_and_report_id():
    """Analyzer facet provenance should identify the report."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("epsilon"))
        report = SourceAnalysisReport(
            user_id=user,
            tool_name="epsilon",
            source_label="https://code.example/epsilon",
            report={
                "dependencies": [
                    {
                        "value": "npm:lodash",
                        "label": "Lodash",
                        "confidence": 0.88,
                    }
                ]
            },
            review_status=REVIEW_APPROVED,
            reviewed_at=now,
        )
        s.add(report)
        s.flush()
        report_id = report.id

    catalog_projection.refresh_tool_names(["epsilon"])

    with db.session_scope() as s:
        row = s.query(CatalogFacetValue).filter_by(tool_name="epsilon", field="dependency").first()
    assert row is not None
    assert len(row.provenance) > 0
    assert any(item.get("source") == "repository_analysis" for item in row.provenance)
    assert any(item.get("reportId") == report_id for item in row.provenance)


def test_analyzer_facets_declared_facets_unchanged():
    """Declared facets should be present alongside analyzer facets."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("zeta", technology_used=["Java", "JavaScript"]))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="zeta",
                source_label="https://code.example/zeta",
                report={
                    "technology": [
                        {
                            "value": "Go",
                            "label": "Go",
                            "confidence": 0.75,
                        }
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["zeta"])

    with db.session_scope() as s:
        facets = s.query(CatalogFacetValue).filter_by(tool_name="zeta").all()
        fields = {(row.field, row.value) for row in facets}
    # Declared facets from technology_used should be present
    assert ("technology", "java") in fields
    assert ("technology", "javascript") in fields
    # Analyzer detected_technology facet should also be present
    assert ("detected_technology", "go") in fields


def test_analyzer_facets_no_report_projects_only_declared_facets():
    """Tool with no analysis report should have only declared facets."""
    with db.session_scope() as s:
        s.add(_canonical("iota", keywords=["search", "analysis"]))

    catalog_projection.refresh_tool_names(["iota"])

    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="iota").all()}
    # Should have declared facets from keywords
    assert ("keywords", "search") in facets
    assert ("keywords", "analysis") in facets


def test_analyzer_facets_reprojecting_twice_is_idempotent():
    """Reprojecting twice should produce identical rows, no duplicates."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("kappa"))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="kappa",
                source_label="https://code.example/kappa",
                report={
                    "dependencies": [
                        {
                            "value": "cargo:serde",
                            "label": "Serde",
                            "confidence": 0.91,
                        }
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["kappa"])
    first_facets = []
    with db.session_scope() as s:
        first_facets = sorted(
            [(row.field, row.value, row.label, row.confidence_basis_points)
             for row in s.query(CatalogFacetValue).filter_by(tool_name="kappa").all()]
        )

    catalog_projection.refresh_tool_names(["kappa"])
    second_facets = []
    with db.session_scope() as s:
        second_facets = sorted(
            [(row.field, row.value, row.label, row.confidence_basis_points)
             for row in s.query(CatalogFacetValue).filter_by(tool_name="kappa").all()]
        )

    assert first_facets == second_facets


def test_analyzer_facets_malformed_report_does_not_error():
    """Malformed reports should not error or cost tool declared facets."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("lambda", technology_used=["Ruby"]))
        # Report with various malformations
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="lambda",
                source_label="https://code.example/lambda",
                report={
                    "dependencies": "not a list",  # Should be skipped
                    "apis": [{"value": "valid-api", "confidence": "not a number"}],  # Bad confidence
                    "technology": [
                        {"value": "", "label": "Empty"},  # Empty value
                        {"value": "Rust", "confidence": float('nan')},  # NaN confidence
                    ],
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    # Should not raise, should still project declared facets
    catalog_projection.refresh_tool_names(["lambda"])

    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="lambda").all()}
    # Declared facets should be present
    assert ("technology", "ruby") in facets


def test_analyzer_facets_dedupe_keeps_max_confidence():
    """Two findings with same value but different confidence should produce one row with max confidence."""
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("mu"))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="mu",
                source_label="https://code.example/mu",
                report={
                    "dependencies": [
                        {
                            "value": "npm:express",
                            "label": "Express",
                            "confidence": 0.80,
                        },
                        {
                            "value": "npm:express",
                            "label": "Express.js",
                            "confidence": 0.95,
                        },
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["mu"])

    with db.session_scope() as s:
        rows = s.query(CatalogFacetValue).filter_by(tool_name="mu", field="dependency", value="npm:express").all()
    # Should have exactly one row with the max confidence
    assert len(rows) == 1
    assert rows[0].confidence_basis_points == 9500  # max(0.80 * 10000, 0.95 * 10000)
