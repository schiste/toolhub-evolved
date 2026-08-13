# SPDX-License-Identifier: GPL-3.0-or-later
"""Query behavior for faceted discovery over CatalogFacetValue."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "proxy"))

from backend import db  # noqa: E402
from backend import tool_facets  # noqa: E402
from backend.models import CatalogFacetValue, SourceAnalysisReport, User, utcnow  # noqa: E402


@pytest.fixture(autouse=True)
def database() -> None:
    db.configure("sqlite://")
    db.init_schema()


def test_tools_matching_facets_empty_filters() -> None:
    """Verify tools_matching_facets handles empty filter dict.

    Empty dicts and dicts with all-empty values match nothing.
    """
    _seed_facets()
    with db.session_scope() as s:
        result = tool_facets.tools_matching_facets(s, {})
        assert result == []
        result = tool_facets.tools_matching_facets(s, {"dependency": []})
        assert result == []
        # Multiple empty filters
        result = tool_facets.tools_matching_facets(
            s, {"dependency": [], "wikimedia_api": [], "detected_technology": []}
        )
        assert result == []
        # Mixed dict: one empty filter alongside one populated filter must empty the result
        result = tool_facets.tools_matching_facets(
            s, {"dependency": [], "wikimedia_api": ["wikidata-query-service"]}
        )
        assert result == []


def test_count_matching_empty_filters() -> None:
    """Verify count_matching handles empty filter dict.

    Empty dicts and dicts with all-empty values match nothing.
    """
    _seed_facets()
    with db.session_scope() as s:
        assert tool_facets.count_matching(s, {}) == 0
        assert tool_facets.count_matching(s, {"dependency": []}) == 0
        # Multiple empty filters
        assert (
            tool_facets.count_matching(s, {"dependency": [], "wikimedia_api": []}) == 0
        )
        # Mixed dict: one empty filter alongside one populated filter must empty the result
        assert tool_facets.count_matching(s, {"dependency": [], "wikimedia_api": ["wikidata-query-service"]}) == 0


def _report_user(s: Session) -> int:
    """SourceAnalysisReport.user_id is NOT NULL (models.py:1061); seed a user.

    Same pattern as tests/proxy/test_graph_enrichment.py:72-79.
    """
    user = User(wm_sub="42", username="Seeder")
    s.add(user)
    s.flush()
    return user.id


def _seed_facets() -> None:
    """Seed both analysis reports (for coverage) and CatalogFacetValue rows."""
    with db.session_scope() as s:
        # Coverage is defined as "tools with at least one analysis report",
        # so the reports themselves must exist, not just derived facets.
        uid = _report_user(s)
        s.add(SourceAnalysisReport(tool_name="sfedits", report={}, user_id=uid))
        s.add(SourceAnalysisReport(tool_name="cite-checker", report={}, user_id=uid))

        # Seed CatalogFacetValue rows directly (simulating projection output)
        # sfedits: pywikibot (0.95), npm:vue (0.90), wikidata-query-service (0.94), python (0.64)
        s.add(
            CatalogFacetValue(
                tool_name="sfedits",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot (pypi)",
                confidence_basis_points=9500,
                provenance=[{"source": "repository_analysis"}],
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="sfedits",
                field="dependency",
                value="npm:vue",
                label="vue (npm)",
                confidence_basis_points=9000,
                provenance=[{"source": "repository_analysis"}],
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="sfedits",
                field="wikimedia_api",
                value="wikidata-query-service",
                label="Wikidata Query Service",
                confidence_basis_points=9400,
                provenance=[{"source": "repository_analysis"}],
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="sfedits",
                field="detected_technology",
                value="python",
                label="Python",
                confidence_basis_points=6400,
                provenance=[{"source": "repository_analysis"}],
            )
        )

        # cite-checker: pywikibot (0.80)
        s.add(
            CatalogFacetValue(
                tool_name="cite-checker",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot (pypi)",
                confidence_basis_points=8000,
                provenance=[{"source": "repository_analysis"}],
            )
        )


def test_tools_matching_facets_intersects_filters() -> None:
    _seed_facets()
    with db.session_scope() as s:
        both = tool_facets.tools_matching_facets(s, {"dependency": ["pypi:pywikibot"]}, limit=10)
        assert sorted(m.tool_name for m in both) == ["cite-checker", "sfedits"]
        narrowed = tool_facets.tools_matching_facets(
            s,
            {"dependency": ["pypi:pywikibot"], "wikimedia_api": ["wikidata-query-service"]},
            limit=10,
        )
        assert [m.tool_name for m in narrowed] == ["sfedits"]
        # Matched facet detail rides along for the API layer.
        assert {
            "facet": "dependency",
            "value": "pypi:pywikibot",
            "confidence": 0.95,
        } in narrowed[0].matched


def test_facet_value_counts_and_coverage() -> None:
    _seed_facets()
    with db.session_scope() as s:
        counts = tool_facets.facet_value_counts(s, "dependency")
        assert counts[0] == {"value": "pypi:pywikibot", "toolCount": 2}
        assert (
            tool_facets.facet_value_counts(s, "dependency", limit=1) == counts[:1]
        )
        # Assert full list equality, not just membership
        assert counts == [{"value": "pypi:pywikibot", "toolCount": 2}, {"value": "npm:vue", "toolCount": 1}]
        assert tool_facets.count_facet_values(s, "dependency") == len(counts)
        assert tool_facets.scanned_tool_count(s) == 2
        # Test pagination: when distinct total exceeds limit, count exceeds returned list
        with_limit = tool_facets.facet_value_counts(s, "dependency", limit=1)
        total = tool_facets.count_facet_values(s, "dependency")
        assert len(with_limit) == 1
        assert total == 2  # More values exist than returned


def test_count_matching_reports_true_total() -> None:
    _seed_facets()
    with db.session_scope() as s:
        filters = {"dependency": ["pypi:pywikibot"]}
        assert tool_facets.count_matching(s, filters) == 2
        limited = tool_facets.tools_matching_facets(s, filters, limit=1)
        assert len(limited) == 1  # page smaller than the true total
        # One tool matching TWO values of one type is still one tool:
        # sfedits carries both pypi:pywikibot and npm:vue.
        both_values = {"dependency": ["pypi:pywikibot", "npm:vue"]}
        assert tool_facets.count_matching(s, both_values) == 2
        # Two-type INTERSECT path: only sfedits has the API facet too.
        two_types = {
            "dependency": ["pypi:pywikibot"],
            "wikimedia_api": ["wikidata-query-service"],
        }
        assert tool_facets.count_matching(s, two_types) == 1
        # An asked-for-but-empty filter must empty the result, not widen it.
        widened = {"dependency": [], "wikimedia_api": ["wikidata-query-service"]}
        assert tool_facets.count_matching(s, widened) == 0
        assert tool_facets.tools_matching_facets(s, widened, limit=10) == []
        # No matches for a non-existent value
        assert tool_facets.count_matching(s, {"dependency": ["nonexistent"]}) == 0
        assert tool_facets.tools_matching_facets(s, {"dependency": ["nonexistent"]}) == []


def test_tools_matching_facets_ranking_by_matched_confidence() -> None:
    """Test that tools are ranked by confidence of matched facets, not all facets.

    This is CRITICAL 1: ranking must use matched_condition in the WHERE clause
    to rank only by facets that match the query, not by unrelated high-confidence
    facets. Tools with different confidence in the same dependency must sort
    by that confidence.
    """
    _seed_facets()
    with db.session_scope() as s:
        # Add two tools where they disagree on confidence for the same dependency
        # but have other unrelated high-confidence facets that would skew ranking
        # if matched_condition were removed.
        user1 = User(wm_sub="ranking-user-1", username="User1")
        s.add(user1)
        s.flush()
        uid = user1.id

        s.add(
            CatalogFacetValue(
                tool_name="high-match",
                field="dependency",
                value="pypi:shared",
                label="shared",
                confidence_basis_points=9000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="low-match",
                field="dependency",
                value="pypi:shared",
                label="shared",
                confidence_basis_points=1000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="low-match",
                field="detected_technology",
                value="python",
                label="Python",
                confidence_basis_points=9900,  # High but unrelated
            )
        )
        s.add(SourceAnalysisReport(tool_name="high-match", report={}, user_id=uid))
        s.add(SourceAnalysisReport(tool_name="low-match", report={}, user_id=uid))

        # Query for shared dependency should rank by matched confidence, not by all facets
        result = tool_facets.tools_matching_facets(s, {"dependency": ["pypi:shared"]})
        names = [m.tool_name for m in result]
        assert names == ["high-match", "low-match"], f"Expected high-match first due to higher matched confidence, got {names}"


def test_facet_match_detail_full_equality() -> None:
    """Test that FacetMatch.matched contains exactly the matched facets, not extras.

    This is CRITICAL 2: matched must list ONLY the facets that match the query,
    not all facets of the tool. Membership checks won't catch extra unrelated
    facets being included; only full equality does.
    """
    _seed_facets()
    with db.session_scope() as s:
        user2 = User(wm_sub="equality-user-2", username="User2")
        s.add(user2)
        s.flush()
        uid = user2.id

        # Tool with multiple unrelated facets
        s.add(
            CatalogFacetValue(
                tool_name="multi-facet",
                field="dependency",
                value="pypi:target",
                label="target",
                confidence_basis_points=9500,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="multi-facet",
                field="dependency",
                value="pypi:other",
                label="other",
                confidence_basis_points=8500,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="multi-facet",
                field="detected_technology",
                value="python",
                label="Python",
                confidence_basis_points=9000,
            )
        )
        s.add(SourceAnalysisReport(tool_name="multi-facet", report={}, user_id=uid))

        # Query for just one dependency
        result = tool_facets.tools_matching_facets(s, {"dependency": ["pypi:target"]})
        assert len(result) == 1
        match = result[0]
        # matched should contain ONLY the facet that matched the query
        assert match.matched == [{"facet": "dependency", "value": "pypi:target", "confidence": 0.95}], \
            f"matched should only contain the queried facet, got {match.matched}"


def test_tools_matching_facets_result_caps() -> None:
    """Test that result caps (MAX_FACET_RESULTS) are enforced.

    This is IMPORTANT 7: removing the min() clamp on result caps would not
    fail if tests don't seed more rows than the cap.
    """
    with db.session_scope() as s:
        user3 = User(wm_sub="caps-user-3", username="User3")
        s.add(user3)
        s.flush()
        uid = user3.id

        # Create more tools than MAX_FACET_RESULTS
        for i in range(tool_facets.MAX_FACET_RESULTS + 10):
            s.add(
                CatalogFacetValue(
                    tool_name=f"tool-{i}",
                    field="dependency",
                    value="pypi:common",
                    label="common",
                    confidence_basis_points=5000 + (i % 10) * 100,
                )
            )
            s.add(SourceAnalysisReport(tool_name=f"tool-{i}", report={}, user_id=uid))
        s.flush()

        result = tool_facets.tools_matching_facets(s, {"dependency": ["pypi:common"]})
        assert len(result) == tool_facets.MAX_FACET_RESULTS, \
            f"Expected cap at MAX_FACET_RESULTS ({tool_facets.MAX_FACET_RESULTS}), got {len(result)}"
        # But total count should reflect all matches
        total = tool_facets.count_matching(s, {"dependency": ["pypi:common"]})
        assert total > tool_facets.MAX_FACET_RESULTS, \
            f"Total count should exceed cap, got {total}"


def test_facet_value_counts_result_caps() -> None:
    """Test that facet_value_counts respects MAX_VALUE_RESULTS cap.

    This is IMPORTANT 7: removing the min() clamp on result caps would not
    fail if tests don't seed more rows than the cap.
    """
    with db.session_scope() as s:
        user4 = User(wm_sub="valuecaps-user-4", username="User4")
        s.add(user4)
        s.flush()
        uid = user4.id

        # Create more distinct dependency values than MAX_VALUE_RESULTS
        for i in range(tool_facets.MAX_VALUE_RESULTS + 10):
            s.add(
                CatalogFacetValue(
                    tool_name=f"tool-deps-{i}",
                    field="dependency",
                    value=f"pypi:pkg-{i}",
                    label=f"pkg-{i}",
                    confidence_basis_points=5000,
                )
            )
            s.add(SourceAnalysisReport(tool_name=f"tool-deps-{i}", report={}, user_id=uid))
        s.flush()

        # Test that default limit is bounded by MAX_VALUE_RESULTS
        result = tool_facets.facet_value_counts(s, "dependency", limit=tool_facets.MAX_VALUE_RESULTS)
        assert len(result) == tool_facets.MAX_VALUE_RESULTS, \
            f"Expected cap at MAX_VALUE_RESULTS ({tool_facets.MAX_VALUE_RESULTS}), got {len(result)}"
        # But total count should reflect all values
        total = tool_facets.count_facet_values(s, "dependency")
        assert total > tool_facets.MAX_VALUE_RESULTS, \
            f"Total count should exceed cap, got {total}"


def test_unknown_facet_type_consistency() -> None:
    """Test that unknown facet types are handled consistently across all functions.

    This is IMPORTANT 5: facet_type validation must be consistent across
    tools_matching_facets, facet_value_counts, count_matching, and count_facet_values.
    All should reject unknown types and return no matches.
    """
    _seed_facets()
    with db.session_scope() as s:
        unknown_type = "UNKNOWN_TYPE"
        # All four helpers should handle unknown type the same way
        assert tool_facets.tools_matching_facets(s, {unknown_type: ["value"]}) == []
        assert tool_facets.count_matching(s, {unknown_type: ["value"]}) == 0
        assert tool_facets.facet_value_counts(s, unknown_type) == []
        assert tool_facets.count_facet_values(s, unknown_type) == 0


def test_tools_matching_facets_declared_only_filter() -> None:
    """Test filtering by declared facets alone, without analyzer filters.

    This is the coverage-independence guarantee: a tool with NO analysis report
    at all can still be found by a declared filter.
    """
    with db.session_scope() as s:
        # Add a tool with only declared facets (no SourceAnalysisReport)
        s.add(
            CatalogFacetValue(
                tool_name="web-tool",
                field="tool_type",
                value="web app",
                label="Web App",
                confidence_basis_points=10000,
            )
        )
        # Add another tool to ensure filtering works
        s.add(
            CatalogFacetValue(
                tool_name="bot-tool",
                field="tool_type",
                value="bot",
                label="Bot",
                confidence_basis_points=10000,
            )
        )

    with db.session_scope() as s:
        # Query for tools with tool_type="web app"
        result = tool_facets.tools_matching_facets(s, {"tool_type": ["web app"]})
        assert len(result) == 1
        assert result[0].tool_name == "web-tool"

    with db.session_scope() as s:
        # Query for tools with tool_type="bot"
        result = tool_facets.tools_matching_facets(s, {"tool_type": ["bot"]})
        assert len(result) == 1
        assert result[0].tool_name == "bot-tool"


def test_tools_matching_facets_declared_and_analyzer_combined() -> None:
    """Test that declared and analyzer filters AND together correctly.

    A tool must match BOTH filter families to be included in results.
    """
    with db.session_scope() as s:
        # seed analyzer facets
        user = User(wm_sub="combined-user", username="User")
        s.add(user)
        s.flush()
        uid = user.id

        # Tool 1: bot type (declared) + pywikibot dependency (analyzer)
        s.add(
            CatalogFacetValue(
                tool_name="bot-with-lib",
                field="tool_type",
                value="bot",
                label="Bot",
                confidence_basis_points=10000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="bot-with-lib",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot",
                confidence_basis_points=9500,
            )
        )
        s.add(SourceAnalysisReport(tool_name="bot-with-lib", report={}, user_id=uid))

        # Tool 2: library type (declared) + pywikibot dependency (analyzer)
        s.add(
            CatalogFacetValue(
                tool_name="library-with-lib",
                field="tool_type",
                value="library",
                label="Library",
                confidence_basis_points=10000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="library-with-lib",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot",
                confidence_basis_points=9500,
            )
        )
        s.add(SourceAnalysisReport(tool_name="library-with-lib", report={}, user_id=uid))

        # Tool 3: bot type but NO pywikibot dependency
        s.add(
            CatalogFacetValue(
                tool_name="bot-no-lib",
                field="tool_type",
                value="bot",
                label="Bot",
                confidence_basis_points=10000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="bot-no-lib",
                field="dependency",
                value="pypi:mwclient",
                label="mwclient",
                confidence_basis_points=9000,
            )
        )
        s.add(SourceAnalysisReport(tool_name="bot-no-lib", report={}, user_id=uid))

    with db.session_scope() as s:
        # Query: tool_type=bot AND dependency=pywikibot
        # Should match only bot-with-lib (has both)
        result = tool_facets.tools_matching_facets(
            s,
            {
                "dependency": ["pypi:pywikibot"],
                "tool_type": ["bot"],
            },
        )
        names = [m.tool_name for m in result]
        assert names == ["bot-with-lib"], f"Expected only bot-with-lib, got {names}"

        # Query: tool_type=library AND dependency=pywikibot
        # Should match only library-with-lib
        result = tool_facets.tools_matching_facets(
            s,
            {
                "dependency": ["pypi:pywikibot"],
                "tool_type": ["library"],
            },
        )
        names = [m.tool_name for m in result]
        assert names == ["library-with-lib"], f"Expected only library-with-lib, got {names}"


def test_tools_matching_facets_declared_empty_fails_closed() -> None:
    """Test that empty declared filter causes fail-closed behavior.

    When a declared filter is asked for but has no known values,
    the result must be empty, not widen the filter.
    """
    with db.session_scope() as s:
        user = User(wm_sub="empty-declared-user", username="User")
        s.add(user)
        s.flush()
        uid = user.id

        # Add a tool with analyzer facet
        s.add(
            CatalogFacetValue(
                tool_name="some-tool",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot",
                confidence_basis_points=9500,
            )
        )
        s.add(SourceAnalysisReport(tool_name="some-tool", report={}, user_id=uid))

    with db.session_scope() as s:
        # Empty declared filter alongside populated analyzer filter
        # should return empty result (fail closed)
        result = tool_facets.tools_matching_facets(
            s,
            {"dependency": ["pypi:pywikibot"], "tool_type": []},
        )
        assert result == [], f"Expected empty result due to empty filter, got {result}"

        # Same with count_matching
        count = tool_facets.count_matching(
            s,
            {"dependency": ["pypi:pywikibot"], "tool_type": []},
        )
        assert count == 0, f"Expected 0 due to empty filter, got {count}"


def test_tools_matching_facets_declared_matched_detail() -> None:
    """Test that declared matches appear in FacetMatch.matched with confidence conversion.

    Declared matches should appear as {"facet": field, "value": value, "confidence": converted}
    where confidence is confidence_basis_points / 10000.
    """
    with db.session_scope() as s:
        # Add a tool with declared facet that has non-max confidence
        s.add(
            CatalogFacetValue(
                tool_name="partial-confidence-tool",
                field="tool_type",
                value="bot",
                label="Bot",
                confidence_basis_points=8500,  # 85% confidence
            )
        )

    with db.session_scope() as s:
        result = tool_facets.tools_matching_facets(
            s,
            {"tool_type": ["bot"]},
        )
        assert len(result) == 1
        match = result[0]
        # matched should contain the declared entry with converted confidence
        assert len(match.matched) == 1
        matched_item = match.matched[0]
        assert matched_item["facet"] == "tool_type"
        assert matched_item["value"] == "bot"
        assert matched_item["confidence"] == 0.85, f"Expected 0.85, got {matched_item['confidence']}"


def test_count_matching_declared_filters() -> None:
    """Test count_matching with declared filters."""
    with db.session_scope() as s:
        user = User(wm_sub="count-declared-user", username="User")
        s.add(user)
        s.flush()
        uid = user.id

        # Tool 1: bot, has pywikibot
        s.add(
            CatalogFacetValue(
                tool_name="bot1",
                field="tool_type",
                value="bot",
                label="Bot",
                confidence_basis_points=10000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="bot1",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot",
                confidence_basis_points=9500,
            )
        )
        s.add(SourceAnalysisReport(tool_name="bot1", report={}, user_id=uid))

        # Tool 2: library, has pywikibot
        s.add(
            CatalogFacetValue(
                tool_name="lib1",
                field="tool_type",
                value="library",
                label="Library",
                confidence_basis_points=10000,
            )
        )
        s.add(
            CatalogFacetValue(
                tool_name="lib1",
                field="dependency",
                value="pypi:pywikibot",
                label="pywikibot",
                confidence_basis_points=9500,
            )
        )
        s.add(SourceAnalysisReport(tool_name="lib1", report={}, user_id=uid))

    with db.session_scope() as s:
        # Just declared filter
        assert tool_facets.count_matching(s, {"tool_type": ["bot"]}) == 1

        # Declared AND analyzer
        assert (
            tool_facets.count_matching(
                s,
                {"dependency": ["pypi:pywikibot"], "tool_type": ["bot"]},
            )
            == 1
        )

        # Declared OR within one field (bot or library)
        assert tool_facets.count_matching(s, {"tool_type": ["bot", "library"]}) == 2
