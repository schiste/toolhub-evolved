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
