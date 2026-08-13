# SPDX-License-Identifier: GPL-3.0-or-later
"""Facet extraction, storage, and query behavior for tool signal facets."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db  # noqa: E402
from backend.models import ToolSignalFacet, utcnow  # noqa: E402


@pytest.fixture(autouse=True)
def database() -> None:
    db.configure("sqlite://")
    db.init_schema()


def test_tool_signal_facet_roundtrip_and_uniqueness() -> None:
    with db.session_scope() as s:
        s.add(
            ToolSignalFacet(
                tool_name="sfedits",
                facet_type="dependency",
                value="pypi:pywikibot",
                confidence=0.9,
                source_report_id=1,
                updated_at=utcnow(),
            )
        )
    with db.session_scope() as s:
        row = s.query(ToolSignalFacet).one()
        assert row.tool_name == "sfedits"  # noqa: S101
        assert row.value == "pypi:pywikibot"  # noqa: S101
    with pytest.raises(IntegrityError), db.session_scope() as s:
        s.add(
            ToolSignalFacet(
                tool_name="sfedits",
                facet_type="dependency",
                value="pypi:pywikibot",
            )
        )


# Shape mirrors source_analyzer.py:2801-2832 finding payloads; only the keys
# extraction reads are included.
SAMPLE_REPORT = {
    "toolName": "sfedits",
    "dependencies": [
        {"value": "pypi:pywikibot", "label": "pywikibot (pypi)", "confidence": 0.95},
        {"value": "npm:vue", "label": "vue (npm)", "confidence": 0.9},
        {"value": "pypi:pywikibot", "label": "pywikibot (pypi)", "confidence": 0.5},
    ],
    "apis": [
        {"value": "wikidata-query-service", "label": "Wikidata Query Service", "confidence": 0.94},
        {"value": "", "label": "broken", "confidence": 0.9},
    ],
    "technology": [
        {"value": "Python", "label": "Python", "confidence": 0.64},
    ],
    "warnings": [{"value": "ignored-kind", "confidence": 1.0}],
}

from backend import tool_facets  # noqa: E402


def test_extract_facets_normalizes_and_dedupes() -> None:
    facets = tool_facets.extract_facets(SAMPLE_REPORT)
    assert ("dependency", "pypi:pywikibot", 0.95) in facets  # noqa: S101
    assert ("dependency", "npm:vue", 0.9) in facets  # noqa: S101
    assert ("wikimedia_api", "wikidata-query-service", 0.94) in facets  # noqa: S101
    assert ("technology", "python", 0.64) in facets  # noqa: S101
    # Duplicate value keeps the highest confidence; empty values are dropped;
    # kinds outside the facet vocabulary are ignored.
    assert len([f for f in facets if f[1] == "pypi:pywikibot"]) == 1  # noqa: S101
    assert all(value for _, value, _ in facets)  # noqa: S101
    assert not [f for f in facets if f[0] == "warnings"]  # noqa: S101


def test_extract_facets_tolerates_malformed_report() -> None:
    assert tool_facets.extract_facets({}) == []  # noqa: S101
    assert (  # noqa: S101
        tool_facets.extract_facets({"dependencies": "nope", "apis": [None, 7]}) == []
    )
    # Test bad confidence values (non-numeric)
    result = tool_facets.extract_facets({"dependencies": [{"value": "pypi:test", "confidence": "not-a-number"}]})
    assert result == [("dependency", "pypi:test", 0.0)]  # noqa: S101


def test_replace_analyzer_facets_replaces_prior_rows() -> None:
    """Verify replace_analyzer_facets replaces old rows with new ones."""
    with db.session_scope() as s:
        # Insert initial facets for sfedits
        count1 = tool_facets.replace_analyzer_facets(s, "sfedits", SAMPLE_REPORT, source_report_id=1)
        assert count1 == 4  # noqa: S101

    with db.session_scope() as s:
        rows1 = s.query(ToolSignalFacet).all()
        assert len(rows1) == 4  # noqa: S101
        values1 = {(r.facet_type, r.value) for r in rows1}
        assert ("dependency", "pypi:pywikibot") in values1  # noqa: S101
        assert ("dependency", "npm:vue") in values1  # noqa: S101

    # Replace with a new report that only has one dependency
    with db.session_scope() as s:
        count2 = tool_facets.replace_analyzer_facets(
            s,
            "sfedits",
            {"dependencies": [{"value": "pypi:mwclient", "confidence": 0.9}]},
            source_report_id=2,
        )
        assert count2 == 1  # noqa: S101

    with db.session_scope() as s:
        rows2 = s.query(ToolSignalFacet).all()
        assert len(rows2) == 1  # noqa: S101
        assert rows2[0].value == "pypi:mwclient"  # noqa: S101
        assert rows2[0].source_report_id == 2  # noqa: S101


def test_replace_analyzer_facets_empty_tool_name() -> None:
    """Verify replace_analyzer_facets returns 0 for empty tool name."""
    with db.session_scope() as s:
        count = tool_facets.replace_analyzer_facets(s, "", SAMPLE_REPORT, source_report_id=1)
        assert count == 0  # noqa: S101

    with db.session_scope() as s:
        rows = s.query(ToolSignalFacet).all()
        assert len(rows) == 0  # noqa: S101


def test_set_tool_type_facet_set_change_and_clear() -> None:
    """Verify set_tool_type_facet can set, change, and clear the facet."""
    # Set the facet
    with db.session_scope() as s:
        tool_facets.set_tool_type_facet(s, "sfedits", {"tool_type": "bot"})

    with db.session_scope() as s:
        rows = s.query(ToolSignalFacet).all()
        assert len(rows) == 1  # noqa: S101
        assert rows[0].value == "bot"  # noqa: S101

    # Change the facet
    with db.session_scope() as s:
        tool_facets.set_tool_type_facet(s, "sfedits", {"tool_type": "library"})

    with db.session_scope() as s:
        rows = s.query(ToolSignalFacet).all()
        assert len(rows) == 1  # noqa: S101
        assert rows[0].value == "library"  # noqa: S101

    # Clear the facet (no tool_type in record)
    with db.session_scope() as s:
        tool_facets.set_tool_type_facet(s, "sfedits", {})

    with db.session_scope() as s:
        rows = s.query(ToolSignalFacet).all()
        assert len(rows) == 0  # noqa: S101


def test_set_tool_type_facet_no_op_path() -> None:
    """Verify set_tool_type_facet doesn't update updated_at on no-op."""
    # Set the facet initially
    with db.session_scope() as s:
        tool_facets.set_tool_type_facet(s, "sfedits", {"tool_type": "bot"})

    # Read the updated_at value
    with db.session_scope() as s:
        row = s.query(ToolSignalFacet).one()
        first_updated_at = row.updated_at

    # Call with the same record (should be no-op)
    with db.session_scope() as s:
        tool_facets.set_tool_type_facet(s, "sfedits", {"tool_type": "bot"})

    # Verify updated_at is unchanged
    with db.session_scope() as s:
        row = s.query(ToolSignalFacet).one()
        assert row.updated_at == first_updated_at  # noqa: S101


def test_set_tool_type_facet_empty_tool_name() -> None:
    """Verify set_tool_type_facet handles empty tool name gracefully."""
    with db.session_scope() as s:
        tool_facets.set_tool_type_facet(s, "", {"tool_type": "bot"})

    with db.session_scope() as s:
        rows = s.query(ToolSignalFacet).all()
        assert len(rows) == 0  # noqa: S101


def test_tools_matching_facets_empty_filters() -> None:
    """Verify tools_matching_facets handles empty filter dict."""
    _seed_facets()
    with db.session_scope() as s:
        result = tool_facets.tools_matching_facets(s, {})
        assert result == []  # noqa: S101
        result = tool_facets.tools_matching_facets(s, {"dependency": []})
        assert result == []  # noqa: S101


def test_count_matching_empty_filters() -> None:
    """Verify count_matching handles empty filter dict."""
    _seed_facets()
    with db.session_scope() as s:
        assert tool_facets.count_matching(s, {}) == 0  # noqa: S101
        assert tool_facets.count_matching(s, {"dependency": []}) == 0  # noqa: S101


def _report_user(s: object) -> int:
    """SourceAnalysisReport.user_id is NOT NULL (models.py:1061); seed a user.

    Same pattern as tests/proxy/test_graph_enrichment.py:72-79.
    """
    from backend.models import User  # noqa: E402

    user = User(wm_sub="42", username="Seeder")
    s.add(user)  # type: ignore[attr-defined]
    s.flush()  # type: ignore[attr-defined]
    return user.id  # type: ignore[return-value]


def _seed_facets() -> None:
    from backend.models import SourceAnalysisReport  # noqa: E402

    with db.session_scope() as s:
        # Coverage is defined as "tools with at least one analysis report",
        # so the reports themselves must exist, not just derived facets.
        uid = _report_user(s)
        s.add(SourceAnalysisReport(tool_name="sfedits", report=SAMPLE_REPORT, user_id=uid))
        s.add(
            SourceAnalysisReport(
                tool_name="cite-checker",
                report={"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.8}]},
                user_id=uid,
            )
        )
        tool_facets.replace_analyzer_facets(s, "sfedits", SAMPLE_REPORT, source_report_id=1)
        tool_facets.replace_analyzer_facets(
            s,
            "cite-checker",
            {"dependencies": [{"value": "pypi:pywikibot", "confidence": 0.8}]},
            source_report_id=2,
        )
        tool_facets.set_tool_type_facet(s, "sfedits", {"tool_type": "bot"})


def test_tools_matching_facets_intersects_filters() -> None:
    _seed_facets()
    with db.session_scope() as s:
        both = tool_facets.tools_matching_facets(s, {"dependency": ["pypi:pywikibot"]}, limit=10)
        assert sorted(m.tool_name for m in both) == ["cite-checker", "sfedits"]  # noqa: S101
        narrowed = tool_facets.tools_matching_facets(
            s,
            {"dependency": ["pypi:pywikibot"], "wikimedia_api": ["wikidata-query-service"]},
            limit=10,
        )
        assert [m.tool_name for m in narrowed] == ["sfedits"]  # noqa: S101
        # Matched facet detail rides along for the API layer.
        assert {  # noqa: S101
            "facet": "dependency",
            "value": "pypi:pywikibot",
            "confidence": 0.95,
        } in narrowed[0].matched


def test_facet_value_counts_and_coverage() -> None:
    _seed_facets()
    with db.session_scope() as s:
        counts = tool_facets.facet_value_counts(s, "dependency")
        assert counts[0] == {"value": "pypi:pywikibot", "toolCount": 2}  # noqa: S101
        assert (  # noqa: S101
            tool_facets.facet_value_counts(s, "dependency", limit=1) == counts[:1]
        )
        assert tool_facets.count_facet_values(s, "dependency") == len(counts)  # noqa: S101
        assert tool_facets.scanned_tool_count(s) == 2  # noqa: S101


def test_count_matching_reports_true_total() -> None:
    _seed_facets()
    with db.session_scope() as s:
        filters = {"dependency": ["pypi:pywikibot"]}
        assert tool_facets.count_matching(s, filters) == 2  # noqa: S101
        limited = tool_facets.tools_matching_facets(s, filters, limit=1)
        assert len(limited) == 1  # noqa: S101  # page smaller than the true total
        # One tool matching TWO values of one type is still one tool:
        # sfedits carries both pypi:pywikibot and npm:vue.
        both_values = {"dependency": ["pypi:pywikibot", "npm:vue"]}
        assert tool_facets.count_matching(s, both_values) == 2  # noqa: S101
        # Two-type INTERSECT path: only sfedits has the API facet too.
        two_types = {
            "dependency": ["pypi:pywikibot"],
            "wikimedia_api": ["wikidata-query-service"],
        }
        assert tool_facets.count_matching(s, two_types) == 1  # noqa: S101
        # An asked-for-but-empty filter must empty the result, not widen it.
        widened = {"dependency": [], "wikimedia_api": ["wikidata-query-service"]}
        assert tool_facets.count_matching(s, widened) == 0  # noqa: S101
        assert tool_facets.tools_matching_facets(s, widened, limit=10) == []  # noqa: S101
        # No matches for a non-existent value
        assert tool_facets.count_matching(s, {"dependency": ["nonexistent"]}) == 0  # noqa: S101
        assert tool_facets.tools_matching_facets(s, {"dependency": ["nonexistent"]}) == []  # noqa: S101
