"""Integration tests for the Evolved-local catalog projection."""

import logging
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import catalog_projection, catalog_validation, db, graph_enrichment, outbound  # noqa: E402
from backend.catalog_projection import STATUS_READY  # noqa: E402
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


def test_case_variant_curated_keywords_do_not_break_the_refresh_batch():
    """Facet rows are unique on the casefolded value; "OCR"/"ocr" must not collide."""
    patch, errors = catalog_projection.validate_curation_patch({"keywords": ["OCR", "ocr", "maps"]})
    assert patch == {"keywords": ["OCR", "maps"]} and errors == []

    now = utcnow()
    with db.session_scope() as s:
        s.add(_canonical("alpha"))
        user = User(wm_sub="reviewer", username="Reviewer")
        s.add(user)
        s.flush()
        s.add(
            CatalogCuration(
                tool_name="alpha",
                created_by_user_id=user.id,
                reviewed_by_user_id=user.id,
                # Bypasses validate_curation_patch on purpose: rows persisted
                # before that dedup existed still project through this path.
                patch={"keywords": ["OCR", "ocr"]},
                rationale="Case variants.",
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    summary = catalog_projection.refresh_tool_names(["alpha"])
    assert summary["errors"] == 0
    with db.session_scope() as s:
        rows = s.query(CatalogFacetValue).filter_by(tool_name="alpha", field="keywords").all()
    assert [(row.value, row.label) for row in rows] == [("ocr", "OCR")]


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
    """Tool with no analysis report should have only declared facets, no analyzer facets."""
    with db.session_scope() as s:
        s.add(_canonical("iota", keywords=["search", "analysis"]))

    catalog_projection.refresh_tool_names(["iota"])

    with db.session_scope() as s:
        facets = [(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="iota").all()]
    # Should have declared facets from keywords
    assert ("keywords", "search") in facets
    assert ("keywords", "analysis") in facets
    # Should NOT have analyzer facets since there was no report
    analyzer_facets = [f for f in facets if f[0] in {"dependency", "wikimedia_api", "detected_technology"}]
    assert not analyzer_facets, "Tools without reports should not have analyzer facets"


def test_analyzer_facets_reprojecting_twice_is_idempotent():
    """Reprojecting twice should produce identical rows, no duplicates.

    This ensures the delete-then-rebuild pattern in _replace_facets works
    correctly and doesn't create duplicates on re-projection.
    """
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

    # Verify first run produced expected content
    assert len(first_facets) > 0, "First projection should produce facets"
    assert ("dependency", "cargo:serde", "Serde", 9100) in first_facets

    catalog_projection.refresh_tool_names(["kappa"])
    second_facets = []
    with db.session_scope() as s:
        second_facets = sorted(
            [(row.field, row.value, row.label, row.confidence_basis_points)
             for row in s.query(CatalogFacetValue).filter_by(tool_name="kappa").all()]
        )

    # Second run should produce identical result
    assert first_facets == second_facets
    assert len(second_facets) == len(first_facets), "No duplicates should be created"


def test_analyzer_facets_malformed_report_does_not_error():
    """Malformed reports should not error or cost tool declared facets.

    Analyzer facets (dependency, wikimedia_api, detected_technology) should not
    appear when the report is malformed, but declared facets must survive.
    """
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
                    "apis": ["not-a-dict"],  # List with non-dict entry
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
        facets = [(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="lambda").all()]
    # Declared facets should be present
    assert ("technology", "ruby") in facets
    # No analyzer facets should be produced from malformed report
    analyzer_rows = [f for f in facets if f[0] in {"dependency", "wikimedia_api", "detected_technology"}]
    assert not analyzer_rows


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


def test_graph_enrichment_refresh_produces_analyzer_facets():
    """Verify that graph_enrichment.refresh_tool_names triggers analyzer facet projection.

    This tests that when a SourceAnalysisReport exists with analyzer data,
    calling graph_enrichment.refresh_tool_names produces analyzer facets in
    catalog_facet_values. This is the integration point called by
    repository_scan.py:309 after storing a new report.
    """
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        # Create a canonical tool (as would exist from Toolhub)
        s.add(_canonical("omega"))
        # Create a SourceAnalysisReport (as would be created by repository_scan)
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="omega",
                source_label="https://code.example/omega",
                report={
                    "dependencies": [
                        {"value": "npm:lodash", "label": "Lodash", "confidence": 0.87}
                    ],
                    "technology": [
                        {"value": "JavaScript", "label": "JavaScript", "confidence": 0.95}
                    ],
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    # Call graph_enrichment.refresh_tool_names as repository_scan.py would
    graph_enrichment.refresh_tool_names(["omega"])

    # Verify analyzer facets were produced in the catalog projection
    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="omega").all()}

    # Should have analyzer facets from the report
    assert ("dependency", "npm:lodash") in facets
    assert ("detected_technology", "javascript") in facets


def test_analyzer_facets_containment_preserves_healthy_tool_in_batch(monkeypatch):
    """Malformed report in a batch must not cost healthy tools their declared facets.

    This exercises the savepoint containment in _emit_analyzer_facets: co-batch
    a poisoned tool with a healthy one and verify both behave correctly.

    The poison tool's _analyzer_facets is monkeypatched to return a DUPLICATE
    (field, value) pair (violating the unique constraint), forcing a flush-time
    SQLAlchemyError that the savepoint must contain.
    """
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        # Healthy tool with declared facets and analyzer findings
        s.add(_canonical("healthy", technology_used=["Python"]))
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="healthy",
                source_label="https://code.example/healthy",
                report={
                    "dependencies": [
                        {"value": "pypi:requests", "label": "requests", "confidence": 0.90}
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )
        # Poisoned tool - its report will be valid but we'll monkeypatch to make it fail
        s.add(_canonical("poison"))
        poison_report = SourceAnalysisReport(
            user_id=user,
            tool_name="poison",
            source_label="https://code.example/poison",
            report={
                "dependencies": [
                    {
                        "value": "pypi:bad",
                        "label": "bad",
                        "confidence": 0.50,
                    }
                ]
            },
            review_status=REVIEW_APPROVED,
            reviewed_at=now,
        )
        s.add(poison_report)
        s.flush()
        poison_report_id = poison_report.id

    # Patch the PURE EXTRACTOR, never _emit_analyzer_facets itself: the
    # savepoint under test lives inside _emit_analyzer_facets, so replacing
    # that function would exercise the test's own code instead of the
    # production containment (which is exactly how an earlier version of
    # this test passed while the savepoint was deleted).
    original_analyzer_facets = catalog_projection._analyzer_facets

    def poisoned_analyzer_facets(report):
        facets = original_analyzer_facets(report)
        # The poison tool's findings are returned twice, so production code
        # inserts two rows with the same (tool_name, field, value) and the
        # UniqueConstraint fails at FLUSH time — the failure mode the
        # savepoint exists to contain.
        if any(value == "pypi:bad" for _, value, _, _ in facets):
            return facets + facets
        return facets

    monkeypatch.setattr(catalog_projection, "_analyzer_facets", poisoned_analyzer_facets)

    # Refresh both tools in the same batch
    summary = catalog_projection.refresh_tool_names(["healthy", "poison"])
    # Both should be refreshed without batch-level errors
    assert summary["refreshed"] == 2
    assert summary["errors"] == 0

    with db.session_scope() as s:
        # Healthy tool must keep its declared facets, status, and analyzer facets
        healthy_proj = s.get(CatalogToolProjection, "healthy")
        assert healthy_proj.status == STATUS_READY
        healthy_facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="healthy").all()}
        assert ("technology", "python") in healthy_facets
        # Healthy tool should have analyzer facets from its good report
        assert ("dependency", "pypi:requests") in healthy_facets

        # Poison tool should also have status ready, declared facets intact, but no analyzer facets
        # (the savepoint rolled back the analyzer emission, keeping only declared facets)
        poison_proj = s.get(CatalogToolProjection, "poison")
        assert poison_proj.status == STATUS_READY
        poison_facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="poison").all()}
        # Check: no analyzer facets for poison (the savepoint caught the error)
        analyzer_facets = {f for f in poison_facets if f[0] in {"dependency", "wikimedia_api", "detected_technology"}}
        assert not analyzer_facets, f"Expected no analyzer facets, got {analyzer_facets}"


def test_refresh_candidates_includes_tools_with_newer_reports():
    """Verify candidate selection includes tools with newer analysis reports.

    A tool that is status=ready, at current version, but whose latest
    SourceAnalysisReport is newer than its projection's refreshed_at
    should be a candidate for re-projection (C3 fix).
    """
    now = utcnow()
    older_time = now - timedelta(hours=1)
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("outdated"))

    # First projection at older_time
    catalog_projection.refresh_tool_names(["outdated"])

    # Manually update the projection's refreshed_at to simulate older projection
    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "outdated")
        proj.refreshed_at = older_time
        s.flush()

    # Add a new report at current time (newer than the projection)
    with db.session_scope() as s:
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="outdated",
                source_label="https://code.example/outdated",
                report={"dependencies": [{"value": "npm:axios", "label": "axios", "confidence": 0.88}]},
                review_status=REVIEW_APPROVED,
                reviewed_at=now,  # Newer than projection's refreshed_at
            )
        )

    # refresh_candidates should pick up this tool because report is newer
    candidates = catalog_projection.refresh_candidates()
    assert candidates["candidates"] >= 1, "Tool with newer report should be a candidate"
    assert candidates["refreshed"] >= 1, "Tool should be refreshed"

    # Verify the new analyzer facet was projected
    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="outdated").all()}
    assert ("dependency", "npm:axios") in facets, "Analyzer facet should be present after re-projection"


def test_refresh_candidates_purges_facets_after_report_rejection():
    """Rejecting the only approved report must stop its facets being served.

    After moderation flips the report away from approved, the tool no longer
    appears in the approved-report timestamp map, so the newer-report branch
    can never fire — the analyzer-facets-without-approved-report branch must
    catch it instead.
    """
    now = utcnow()
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        s.add(_canonical("moderated"))
        s.add(
            SourceAnalysisReport(
                user_id=user_obj.id,
                tool_name="moderated",
                source_label="https://code.example/moderated",
                report={"dependencies": [{"value": "npm:leftpad", "label": "leftpad", "confidence": 0.9}]},
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    catalog_projection.refresh_tool_names(["moderated"])
    with db.session_scope() as s:
        facets = {row.field for row in s.query(CatalogFacetValue).filter_by(tool_name="moderated").all()}
        assert "dependency" in facets, "Approved report should project analyzer facets"
        report = s.query(SourceAnalysisReport).filter_by(tool_name="moderated").one()
        report.review_status = "rejected"
        report.reviewed_at = utcnow()

    result = catalog_projection.refresh_candidates()
    assert result["refreshed"] >= 1, "Tool with rejected report should be re-projected"
    with db.session_scope() as s:
        facets = {row.field for row in s.query(CatalogFacetValue).filter_by(tool_name="moderated").all()}
    assert "dependency" not in facets, "Rejected report's facets must be purged"

    # And the purge converges: a second sweep finds nothing left to redo.
    assert catalog_projection.refresh_candidates()["candidates"] == 0


def test_refresh_candidates_uses_max_report_timestamp_with_multiple_reports():
    """Verify that with multiple reports per tool, only the newest determines candidacy.

    When a tool has multiple SourceAnalysisReports, the aggregate query should
    pick the max(coalesce(reviewed_at, created_at)) and compare that to refreshed_at.
    An older report should not trigger candidacy if a newer report is not newer than
    the projection.
    """
    now = utcnow()
    older_time = now - timedelta(hours=2)
    mid_time = now - timedelta(hours=1)
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("multiversion"))

    # First projection at mid_time
    catalog_projection.refresh_tool_names(["multiversion"])

    # Manually update the projection's refreshed_at
    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "multiversion")
        proj.refreshed_at = mid_time
        s.flush()

    # Add multiple reports: older one and then a newer one
    with db.session_scope() as s:
        # Older report (should not cause candidacy)
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="multiversion",
                source_label="https://code.example/multiversion",
                report={"dependencies": []},
                review_status=REVIEW_APPROVED,
                reviewed_at=older_time,
            )
        )
        # Newer report (should cause candidacy because it's newer than refreshed_at)
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="multiversion",
                source_label="https://code.example/multiversion",
                report={"dependencies": [{"value": "npm:lodash", "label": "lodash", "confidence": 0.95}]},
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    # refresh_candidates should pick up this tool because the MAX report (now) is newer
    candidates = catalog_projection.refresh_candidates()
    assert candidates["candidates"] >= 1, "Tool with newer report should be a candidate"
    assert candidates["refreshed"] >= 1, "Tool should be refreshed"

    # Verify the new analyzer facet was projected (from the newest report)
    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="multiversion").all()}
    assert ("dependency", "npm:lodash") in facets, "Analyzer facet from newest report should be present"


def test_refresh_candidates_uses_created_at_when_reviewed_at_is_none():
    """Verify that coalesce(reviewed_at, created_at) works in the aggregate.

    When a report has reviewed_at=None, the created_at should be used for comparison.
    """
    now = utcnow()
    older_time = now - timedelta(hours=1)
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("unreviewed"))

    # First projection at older_time
    catalog_projection.refresh_tool_names(["unreviewed"])

    # Manually update the projection's refreshed_at
    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "unreviewed")
        proj.refreshed_at = older_time
        s.flush()

    # Add a report with reviewed_at=None but created_at newer than refreshed_at
    with db.session_scope() as s:
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="unreviewed",
                source_label="https://code.example/unreviewed",
                report={"dependencies": [{"value": "npm:uuid", "label": "uuid", "confidence": 0.90}]},
                review_status=REVIEW_APPROVED,
                created_at=now,  # Newer than projection's refreshed_at
                reviewed_at=None,  # Not reviewed yet
            )
        )

    # refresh_candidates should pick up this tool because created_at is newer
    candidates = catalog_projection.refresh_candidates()
    assert candidates["candidates"] >= 1, "Tool with newer created_at should be a candidate"
    assert candidates["refreshed"] >= 1, "Tool should be refreshed"

    # Verify the analyzer facet was projected
    with db.session_scope() as s:
        facets = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="unreviewed").all()}
    assert ("dependency", "npm:uuid") in facets, "Analyzer facet should be present after re-projection"


def test_refresh_candidates_excludes_tools_with_older_reports():
    """Verify that tools with reports older than refreshed_at are NOT candidates.

    This proves that the comparison works correctly: a tool with old reports
    should not trigger re-projection.
    """
    now = utcnow()
    newer_time = now + timedelta(hours=1)
    old_report_time = now - timedelta(hours=2)
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("oldreport"))

    # First projection at newer_time (future, to simulate old report)
    catalog_projection.refresh_tool_names(["oldreport"])

    # Manually update the projection's refreshed_at to a future time
    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "oldreport")
        proj.refreshed_at = newer_time
        s.flush()

    # Add a report with old timestamp (older than refreshed_at)
    with db.session_scope() as s:
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="oldreport",
                source_label="https://code.example/oldreport",
                report={"dependencies": []},
                review_status=REVIEW_APPROVED,
                reviewed_at=old_report_time,
            )
        )

    # refresh_candidates should NOT include this tool
    candidates = catalog_projection.refresh_candidates()
    # The tool is already at current version and has no retry backoff,
    # so it shouldn't be in candidates (or only from backoff logic, not report comparison)
    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "oldreport")
        # Verify refreshed_at is still the newer time and next_attempt_at is None (no backoff)
        assert proj.refreshed_at == newer_time
        assert proj.next_attempt_at is None

    # The tool should not have been re-projected due to the old report
    # (We can infer this because if it were a candidate, it would have been refreshed)


def test_analyzer_facets_report_not_dict_coverage():
    """Test that a non-dict report is skipped without error.

    This covers the guard at catalog_projection._analyzer_facets:399-400.
    """
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("notdict", technology_used=["Python"]))
        # Report is a list, not a dict
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="notdict",
                source_label="https://code.example/notdict",
                report=["not", "a", "dict"],  # This is not a dict
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    # Should not raise
    catalog_projection.refresh_tool_names(["notdict"])

    with db.session_scope() as s:
        facets = [(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="notdict").all()]
    # Declared facets should survive
    assert ("technology", "python") in facets
    # No analyzer facets from the non-dict report
    analyzer_rows = [f for f in facets if f[0] in {"dependency", "wikimedia_api", "detected_technology"}]
    assert not analyzer_rows


def test_analyzer_facets_non_numeric_confidence_dropped():
    """Findings without a usable confidence are dropped, not kept at 0.

    tool_facets.py documents analyzer confidence as detection certainty and
    promises missing values drop the finding entirely.
    """
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("badconf", technology_used=["Python"]))
        # Report with various bad confidence values
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="badconf",
                source_label="https://code.example/badconf",
                report={
                    "dependencies": [
                        {"value": "pypi:good", "label": "good", "confidence": 0.95},
                        {"value": "pypi:string", "label": "string conf", "confidence": "not-a-number"},
                        {"value": "pypi:none", "label": "none conf", "confidence": None},
                    ]
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    # Should not raise
    catalog_projection.refresh_tool_names(["badconf"])

    with db.session_scope() as s:
        facets = {(row.field, row.value, row.confidence_basis_points) for row in s.query(CatalogFacetValue).filter_by(tool_name="badconf").all()}
    # Good facet should be present with correct confidence
    assert ("dependency", "pypi:good", 9500) in facets
    # Findings without a usable confidence never become facet rows
    values = {value for _, value, _ in facets}
    assert "pypi:string" not in values
    assert "pypi:none" not in values


def test_latest_report_times_respects_review_approved_filter():
    """Test that _latest_report_times only includes REVIEW_APPROVED reports.

    This covers the where clause at catalog_projection._latest_report_times:231.
    """
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("filtered"))
        # Add a non-approved report (should be ignored)
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="filtered",
                source_label="https://code.example/filtered",
                report={"dependencies": []},
                review_status="pending",  # Not approved
                created_at=now,
            )
        )
        # Add an approved report (should be included)
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="filtered",
                source_label="https://code.example/filtered",
                report={"dependencies": []},
                review_status=REVIEW_APPROVED,
                reviewed_at=now - timedelta(hours=1),  # Older but approved
            )
        )

    with db.session_scope() as s:
        times = catalog_projection._latest_report_times(s)
    
    # Should include only the approved report, not the newer pending one
    assert "filtered" in times
    # The timestamp should be from the approved report
    assert times["filtered"] == now - timedelta(hours=1)


def test_refresh_candidates_clamps_future_dated_reports():
    """Test that future-dated reports don't make tools perpetual candidates.

    This covers the report_timestamp <= now check at
    catalog_projection.refresh_candidates:640-641.
    """
    now = utcnow()
    future_time = now + timedelta(hours=1)
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("future"))

    # First projection
    catalog_projection.refresh_tool_names(["future"])

    # Add a future-dated report
    with db.session_scope() as s:
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="future",
                source_label="https://code.example/future",
                report={"dependencies": []},
                review_status=REVIEW_APPROVED,
                reviewed_at=future_time,  # In the future!
            )
        )

    # refresh_candidates should NOT include this tool because report_timestamp > now
    result = catalog_projection.refresh_candidates()
    # The tool is already at current version, so should not be a candidate
    # (The future report doesn't make it a candidate because of the <= now clamp)
    # result["refreshed"] should be 0 because future tool was not refreshed
    assert result["refreshed"] == 0


def test_projection_version_bump_forces_refresh_and_analyzer_facets():
    """Verify C-2 fix: version bump causes re-projection with analyzer facets.

    When PROJECTION_VERSION is bumped, tools at the old version become candidates
    for re-projection. After refresh, a tool with an analyzer report should gain
    analyzer facets. This is the phase 1 headline deliverable.
    """
    now = utcnow()
    user = None
    with db.session_scope() as s:
        user_obj = User(wm_sub="scanner", username="Scanner")
        s.add(user_obj)
        s.flush()
        user = user_obj.id
        s.add(_canonical("versiontest", technology_used=["Python"]))
        # Add a report with analyzer findings
        s.add(
            SourceAnalysisReport(
                user_id=user,
                tool_name="versiontest",
                source_label="https://code.example/versiontest",
                report={
                    "dependencies": [
                        {"value": "pypi:requests", "label": "requests", "confidence": 0.92}
                    ],
                    "technology": [
                        {"value": "Python", "label": "Python", "confidence": 0.99}
                    ],
                },
                review_status=REVIEW_APPROVED,
                reviewed_at=now,
            )
        )

    # First projection at current version
    catalog_projection.refresh_tool_names(["versiontest"])

    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "versiontest")
        # Verify initial projection has analyzer facets
        facets_before = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="versiontest").all()}
        assert ("dependency", "pypi:requests") in facets_before
        assert ("detected_technology", "python") in facets_before
        # Manually downgrade the projection version to simulate old schema
        old_version = proj.projection_version
        proj.projection_version = old_version - 1

    # Now refresh_candidates should include the tool due to version mismatch
    result = catalog_projection.refresh_candidates()
    assert result["refreshed"] >= 1

    # After refresh, analyzer facets should still be present
    with db.session_scope() as s:
        proj = s.get(CatalogToolProjection, "versiontest")
        assert proj.projection_version == catalog_projection.PROJECTION_VERSION
        facets_after = {(row.field, row.value) for row in s.query(CatalogFacetValue).filter_by(tool_name="versiontest").all()}
        # Critical: analyzer facets must persist through version bump
        assert ("dependency", "pypi:requests") in facets_after
        assert ("detected_technology", "python") in facets_after
        assert ("technology", "python") in facets_after  # Declared facet also present
