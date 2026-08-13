# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract and maintain queryable signal facets from analysis reports.

SourceAnalysisReport.report is one JSON blob per scan; this module flattens
the finding kinds discovery needs into ToolSignalFacet rows. Extraction is a
pure function so it can be exercised without a database; storage helpers are
idempotent (replace-per-tool) so re-running any producer converges.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import (
    ANALYZER_FACET_TYPES,
    FACET_DEPENDENCY,
    FACET_TECHNOLOGY,
    FACET_TOOL_TYPE,
    FACET_WIKIMEDIA_API,
    ToolSignalFacet,
    utcnow,
)

# Report top-level key -> facet_type. Finding payload shape is defined by
# source_analyzer.py finding payloads: {"value", "confidence", ...}.
_REPORT_SECTIONS = (
    ("dependencies", FACET_DEPENDENCY),
    ("apis", FACET_WIKIMEDIA_API),
    ("technology", FACET_TECHNOLOGY),
)

Facet = tuple[str, str, float]


def extract_facets(report: dict[str, Any] | None) -> list[Facet]:
    """Return normalized (facet_type, value, confidence) rows for one report.

    Values are casefolded so SQL equality never needs LOWER(); duplicate
    values keep their highest confidence, since the analyzer may emit one
    finding per evidence source.
    """
    best: dict[tuple[str, str], float] = {}
    source = report if isinstance(report, dict) else {}
    for section, facet_type in _REPORT_SECTIONS:
        entries = source.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            value = str(entry.get("value") or "").strip().casefold()[:255]
            if not value:
                continue
            try:
                confidence = float(entry.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            key = (facet_type, value)
            best[key] = max(best[key], confidence) if key in best else confidence
    return [(facet_type, value, confidence) for (facet_type, value), confidence in sorted(best.items())]


def replace_analyzer_facets(
    s: Session,
    tool_name: str,
    report: dict[str, Any] | None,
    *,
    source_report_id: int | None,
) -> int:
    """Replace one tool's analyzer-derived facets with those from `report`.

    Delete-then-insert rather than diffing: a scan is the complete current
    truth for its tool, and the row count per tool is small.
    """
    clean = str(tool_name or "").strip()
    if not clean:
        return 0
    s.execute(
        delete(ToolSignalFacet).where(
            ToolSignalFacet.tool_name == clean,
            ToolSignalFacet.facet_type.in_(ANALYZER_FACET_TYPES),
        )
    )
    now = utcnow()
    facets = extract_facets(report)
    s.add_all(
        ToolSignalFacet(
            tool_name=clean,
            facet_type=facet_type,
            value=value,
            confidence=confidence,
            source_report_id=source_report_id,
            updated_at=now,
        )
        for facet_type, value, confidence in facets
    )
    return len(facets)


def set_tool_type_facet(s: Session, tool_name: str, record: dict[str, Any] | None) -> None:
    """Sync the single tool_type facet for one canonical record.

    No-ops when the stored facet already matches: the catalog sync calls this
    for every tool every 15 minutes, and an unconditional delete+insert would
    be ~9k pointless writes per run on ToolsDB.
    """
    clean = str(tool_name or "").strip()
    if not clean:
        return
    source = record if isinstance(record, dict) else {}
    tool_type = str(source.get("tool_type") or "").strip().casefold()[:255]
    existing = list(
        s.execute(
            select(ToolSignalFacet.value).where(
                ToolSignalFacet.tool_name == clean,
                ToolSignalFacet.facet_type == FACET_TOOL_TYPE,
            )
        ).scalars()
    )
    if existing == ([tool_type] if tool_type else []):
        return
    s.execute(
        delete(ToolSignalFacet).where(
            ToolSignalFacet.tool_name == clean,
            ToolSignalFacet.facet_type == FACET_TOOL_TYPE,
        )
    )
    if tool_type:
        s.add(
            ToolSignalFacet(
                tool_name=clean,
                facet_type=FACET_TOOL_TYPE,
                value=tool_type,
                confidence=1.0,
                source_report_id=None,
                updated_at=utcnow(),
            )
        )
