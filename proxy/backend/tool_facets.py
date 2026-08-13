# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract and maintain queryable signal facets from analysis reports.

SourceAnalysisReport.report is one JSON blob per scan; this module flattens
the finding kinds discovery needs into ToolSignalFacet rows. Extraction is a
pure function so it can be exercised without a database; storage helpers are
idempotent (replace-per-tool) so re-running any producer converges.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from backend.models import (
    ANALYZER_FACET_TYPES,
    FACET_DEPENDENCY,
    FACET_DETECTED_TECHNOLOGY,
    FACET_TYPES,
    FACET_WIKIMEDIA_API,
    CatalogFacetValue,
    SourceAnalysisReport,
    ToolSignalFacet,
    utcnow,
)

# Report top-level key -> facet_type. Finding payload shape is defined by
# source_analyzer.py finding payloads: {"value", "confidence", ...}.
_REPORT_SECTIONS = (
    ("dependencies", FACET_DEPENDENCY),
    ("apis", FACET_WIKIMEDIA_API),
    ("technology", FACET_DETECTED_TECHNOLOGY),
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


MAX_FACET_RESULTS = 100


@dataclass(frozen=True)
class FacetMatch:
    """One tool matching a facet query, with the rows that matched."""

    tool_name: str
    matched: list[dict[str, Any]] = field(default_factory=list)


def tools_matching_facets(  # noqa: C901, PLR0912 - handles both analyzer and declared tables
    s: Session,
    filters: dict[str, list[str]] | None = None,
    *,
    declared_filters: dict[str, list[str]] | None = None,
    limit: int = MAX_FACET_RESULTS,
) -> list[FacetMatch]:
    """Return tools having at least one matching value for EVERY filter type.

    Filters AND across facet types and OR within one type's value list,
    which is the "tools like mine" question: uses this library AND that API.
    Declared filters (from CatalogFacetValue) AND with analyzer filters;
    either family can be used alone.

    Facet types in `filters` must match the known vocabulary (FACET_TYPES);
    unknown types are rejected and return no matches. Declared filter keys
    are CatalogFacetValue.field names; values are compared against the
    casefolded CatalogFacetValue.value.
    """
    clean_analyzer: dict[str, list[str]] = {}
    for facet_type, values in (filters or {}).items():
        if facet_type not in FACET_TYPES:
            # Unknown facet type matches nothing
            return []
        wanted = sorted({str(v or "").strip().casefold() for v in values if str(v or "").strip()})
        if not wanted:
            # A filter the caller asked for that carries no known value
            # matches nothing; dropping it instead would silently widen
            # the AND across types to the remaining filters.
            return []
        clean_analyzer[facet_type] = wanted

    clean_declared: dict[str, list[str]] = {}
    for declared_field, values in (declared_filters or {}).items():
        wanted = sorted({str(v or "").strip().casefold() for v in values if str(v or "").strip()})
        if not wanted:
            # Mirror analyzer filter semantics: an asked-for declared filter
            # with no known values matches nothing.
            return []
        clean_declared[declared_field] = wanted

    if not clean_analyzer and not clean_declared:
        return []
    capped = max(1, min(MAX_FACET_RESULTS, int(limit or MAX_FACET_RESULTS)))

    matching = None
    # Build INTERSECT chain from analyzer filters
    for facet_type, values in clean_analyzer.items():
        names = select(ToolSignalFacet.tool_name).where(
            ToolSignalFacet.facet_type == facet_type,
            ToolSignalFacet.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # Build INTERSECT chain from declared filters
    for declared_field, values in clean_declared.items():
        names = select(CatalogFacetValue.tool_name).where(
            CatalogFacetValue.field == declared_field,
            CatalogFacetValue.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # Rank by the confidence of the facets that actually matched the filters,
    # not the tool's best unrelated signal. Combine both table conditions.
    analyzer_condition = (
        or_(
            *(
                and_(ToolSignalFacet.facet_type == facet_type, ToolSignalFacet.value.in_(values))
                for facet_type, values in clean_analyzer.items()
            )
        )
        if clean_analyzer
        else None
    )
    declared_condition = (
        or_(
            *(
                and_(CatalogFacetValue.field == declared_field, CatalogFacetValue.value.in_(values))
                for declared_field, values in clean_declared.items()
            )
        )
        if clean_declared
        else None
    )

    # Rank using analyzer table when available (has confidence); fall back to declared
    if analyzer_condition is not None:
        names_in_order = list(
            s.execute(
                select(ToolSignalFacet.tool_name)
                .where(ToolSignalFacet.tool_name.in_(matching), analyzer_condition)
                .group_by(ToolSignalFacet.tool_name)
                .order_by(func.max(ToolSignalFacet.confidence).desc(), ToolSignalFacet.tool_name)
                .limit(capped)
            ).scalars()
        )
    else:
        # Declared-only: rank by confidence_basis_points
        names_in_order = list(
            s.execute(
                select(CatalogFacetValue.tool_name)
                .where(CatalogFacetValue.tool_name.in_(matching), declared_condition)
                .group_by(CatalogFacetValue.tool_name)
                .order_by(
                    func.max(CatalogFacetValue.confidence_basis_points).desc(),
                    CatalogFacetValue.tool_name,
                )
                .limit(capped)
            ).scalars()
        )

    if not names_in_order:
        return []

    # Collect matched facets from both tables
    matched_by_tool: dict[str, list[dict[str, Any]]] = {name: [] for name in names_in_order}

    if analyzer_condition is not None:
        rows = s.execute(
            select(ToolSignalFacet).where(ToolSignalFacet.tool_name.in_(names_in_order), analyzer_condition)
        ).scalars()
        for row in rows:
            matched_by_tool[row.tool_name].append(
                {"facet": row.facet_type, "value": row.value, "confidence": row.confidence}
            )

    if declared_condition is not None:
        rows = s.execute(
            select(CatalogFacetValue).where(CatalogFacetValue.tool_name.in_(names_in_order), declared_condition)
        ).scalars()
        for row in rows:
            matched_by_tool[row.tool_name].append(
                {
                    "facet": row.field,
                    "value": row.value,
                    "confidence": row.confidence_basis_points / 10000.0,
                }
            )

    return [
        FacetMatch(
            tool_name=name,
            matched=sorted(matched_by_tool[name], key=lambda m: (m["facet"], m["value"])),
        )
        for name in names_in_order
    ]


MAX_VALUE_RESULTS = 500
DEFAULT_VALUE_RESULTS = 100


def facet_value_counts(s: Session, facet_type: str, *, limit: int = DEFAULT_VALUE_RESULTS) -> list[dict[str, Any]]:
    """Top values of one facet type by tool adoption.

    Bounded: `dependency` alone spans every package across six ecosystems,
    and this feeds unauthenticated responses and LLM context windows. Callers
    display "top N by adoption"; count_facet_values reports the true total.

    Facet types must match the known vocabulary (FACET_TYPES); unknown types
    return an empty list.
    """
    clean = str(facet_type or "").strip()
    if clean not in FACET_TYPES:
        return []
    capped = max(1, min(MAX_VALUE_RESULTS, int(limit or DEFAULT_VALUE_RESULTS)))
    rows = s.execute(
        select(ToolSignalFacet.value, func.count(func.distinct(ToolSignalFacet.tool_name)))
        .where(ToolSignalFacet.facet_type == clean)
        .group_by(ToolSignalFacet.value)
        .order_by(
            func.count(func.distinct(ToolSignalFacet.tool_name)).desc(),
            ToolSignalFacet.value,
        )
        .limit(capped)
    ).all()
    return [{"value": value, "toolCount": count} for value, count in rows]


def count_facet_values(s: Session, facet_type: str) -> int:
    """Count distinct values for one facet type, so callers can report truncation.

    Facet types must match the known vocabulary (FACET_TYPES); unknown types
    return 0.
    """
    clean = str(facet_type or "").strip()
    if clean not in FACET_TYPES:
        return 0
    return int(
        s.execute(
            select(func.count(func.distinct(ToolSignalFacet.value))).where(ToolSignalFacet.facet_type == clean)
        ).scalar()
        or 0
    )


def count_matching(
    s: Session,
    filters: dict[str, list[str]] | None = None,
    *,
    declared_filters: dict[str, list[str]] | None = None,
) -> int:
    """Count tools matching the filters, independent of any page size.

    Declared filters (from CatalogFacetValue) AND with analyzer filters;
    either family can be used alone.

    Facet types in `filters` must match the known vocabulary (FACET_TYPES);
    unknown types are rejected and return 0. Declared filter keys are
    CatalogFacetValue.field names; values are compared against the
    casefolded CatalogFacetValue.value.
    """
    clean_analyzer: dict[str, list[str]] = {}
    for facet_type, values in (filters or {}).items():
        if facet_type not in FACET_TYPES:
            # Unknown facet type matches nothing
            return 0
        wanted = sorted({str(v or "").strip().casefold() for v in values if str(v or "").strip()})
        if not wanted:
            # Mirror tools_matching_facets: an asked-for filter with no
            # known value matches nothing, it does not vanish from the AND.
            return 0
        clean_analyzer[facet_type] = wanted

    clean_declared: dict[str, list[str]] = {}
    for declared_field, values in (declared_filters or {}).items():
        wanted = sorted({str(v or "").strip().casefold() for v in values if str(v or "").strip()})
        if not wanted:
            # Mirror analyzer filter semantics: an asked-for declared filter
            # with no known values matches nothing.
            return 0
        clean_declared[declared_field] = wanted

    if not clean_analyzer and not clean_declared:
        return 0

    matching = None
    # Build INTERSECT chain from analyzer filters
    for facet_type, values in clean_analyzer.items():
        names = select(ToolSignalFacet.tool_name).where(
            ToolSignalFacet.facet_type == facet_type,
            ToolSignalFacet.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # Build INTERSECT chain from declared filters
    for declared_field, values in clean_declared.items():
        names = select(CatalogFacetValue.tool_name).where(
            CatalogFacetValue.field == declared_field,
            CatalogFacetValue.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # COUNT(DISTINCT ...): a tool matching two values of one type is one tool.
    sub = matching.subquery()
    return int(s.execute(select(func.count(func.distinct(sub.c.tool_name)))).scalar() or 0)


def scanned_tool_count(s: Session) -> int:
    """Count tools with at least one stored analysis report (coverage basis).

    Counts reports, not facets: a scanned repository that yielded zero
    findings is still scanned, and the coverage number is what discovery
    clients repeat to users — it must not silently undercount.
    """
    return int(s.execute(select(func.count(func.distinct(SourceAnalysisReport.tool_name)))).scalar() or 0)
