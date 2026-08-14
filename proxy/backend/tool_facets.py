# SPDX-License-Identifier: GPL-3.0-or-later
"""Query helpers for faceted discovery over CatalogFacetValue.

CatalogFacetValue stores both declared facets (tool_type, keywords, wiki,
technology, tasks, audiences, ui_language, license) from the catalog projection
and analyzer-derived facets (dependency, wikimedia_api, detected_technology)
from analysis reports. This module provides indexed search across the union.

CONFIDENCE SEMANTICS:

confidence_basis_points (0-10000) has two distinct meanings depending on facet family:

- DECLARED facets: SOURCE AUTHORITY. Declared facets carry confidence values from
  SOURCE_CONFIDENCE in catalog_projection.py (0-10000 basis points): 10000 for
  official/curated sources (SOURCE_CANONICAL, SOURCE_CURATION), 9500 for official
  crawlers (SOURCE_CRAWLER), 8000 for self-hosted discovery (SOURCE_DISCOVERY).
  Malformed or missing provenance rows result in 0 confidence.

- ANALYZER facets: DETECTION CERTAINTY. Analyzer facets are converted from the
  analyzer report's confidence (0.0-1.0) to basis points: round(confidence * 10000).
  These represent how certain the source code analyzer is about the finding.
  Non-finite or missing confidence values drop the finding entirely.

This dual semantics means queries mixing both families will have different
confidence distributions. When ranking by confidence across both families, be aware
that SOURCE_AUTHORITY and DETECTION_CERTAINTY measure different things — a 9500
declared facet is "came from an official source" while a 9500 analyzer facet is
"90.5% detection confidence", which are not directly comparable.
If you modify the ranking algorithm in future phases, either normalize the two
families to a common confidence scale or rank them separately.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.models import (
    CatalogFacetValue,
    SourceAnalysisReport,
)
from backend.sync import REVIEW_APPROVED

# Declared facet vocabulary from catalog_projection.FACET_FIELDS (8 fields)
_DECLARED_FIELDS = frozenset(
    ("tool_type", "keywords", "wiki", "technology", "tasks", "audiences", "ui_language", "license")
)

# Analyzer-derived facet vocabulary (3 fields)
_ANALYZER_FIELDS = frozenset(("dependency", "wikimedia_api", "detected_technology"))

# Union vocabulary: all valid field names for CatalogFacetValue.field
_VALID_FIELDS = _DECLARED_FIELDS | _ANALYZER_FIELDS


MAX_FACET_RESULTS = 100


@dataclass(frozen=True)
class FacetMatch:
    """One tool matching a facet query, with the rows that matched.

    The `matched` list contains only facets from the filter query.
    Each facet's confidence is: 0.0-1.0 (confidence_basis_points / 10000).

    Confidence semantics (see module docstring for details):
    - Declared facets have confidence = SOURCE_AUTHORITY / 10000 (0.8-1.0)
    - Analyzer facets have confidence = DETECTION_CERTAINTY (0.0-1.0)
    These measure different things; see module docstring for cross-family comparison.
    """

    tool_name: str
    matched: list[dict[str, Any]] = field(default_factory=list)


def tools_matching_facets(
    s: Session,
    filters: dict[str, list[str]],
    *,
    limit: int = MAX_FACET_RESULTS,
) -> list[FacetMatch]:
    """Return tools having at least one matching value for EVERY filter field.

    Filters AND across fields and OR within one field's value list,
    which is the "tools like mine" question: uses this library AND that API.

    Field names in `filters` must match the known vocabulary (_VALID_FIELDS);
    unknown fields are rejected and return no matches. Field names are normalized
    by stripping whitespace. Values are compared against the casefolded
    CatalogFacetValue.value.
    """
    clean_filters: dict[str, list[str]] = {}
    for field_name, values in (filters or {}).items():
        clean_field = str(field_name or "").strip()
        if clean_field not in _VALID_FIELDS:
            # Unknown field matches nothing
            return []
        # Coerce non-list values (None, strings) to [] for fail-closed behavior
        value_list = values if isinstance(values, (list, tuple)) else []
        wanted = sorted({str(v or "").strip().casefold() for v in value_list if str(v or "").strip()})
        if not wanted:
            # A filter the caller asked for that carries no known value
            # matches nothing; dropping it instead would silently widen
            # the AND across fields to the remaining filters.
            return []
        clean_filters[clean_field] = wanted

    if not clean_filters:
        return []
    capped = max(1, min(MAX_FACET_RESULTS, int(limit or MAX_FACET_RESULTS)))

    # Build INTERSECT chain: each field must match at least one value
    matching = None
    for field_name, values in clean_filters.items():
        names = select(CatalogFacetValue.tool_name).where(
            CatalogFacetValue.field == field_name,
            CatalogFacetValue.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # Build condition for matched facets (only those matching the query filters)
    matched_condition = or_(
        *(
            and_(CatalogFacetValue.field == field_name, CatalogFacetValue.value.in_(values))
            for field_name, values in clean_filters.items()
        )
    )

    # Rank by max confidence among matched facets only, then tool name
    names_in_order = list(
        s.execute(
            select(CatalogFacetValue.tool_name)
            .where(CatalogFacetValue.tool_name.in_(matching), matched_condition)
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

    # Collect matched facets (only those matching the query filters)
    matched_by_tool: dict[str, list[dict[str, Any]]] = {name: [] for name in names_in_order}

    rows = s.execute(
        select(CatalogFacetValue).where(CatalogFacetValue.tool_name.in_(names_in_order), matched_condition)
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


def facet_value_counts(s: Session, field_name: str, *, limit: int = DEFAULT_VALUE_RESULTS) -> list[dict[str, Any]]:
    """Top values of one field by tool adoption.

    Bounded: `dependency` alone spans every package across six ecosystems,
    and this feeds unauthenticated responses and LLM context windows. Callers
    display "top N by adoption"; count_facet_values reports the true total.

    Field names must match the known vocabulary (_VALID_FIELDS); unknown names
    return an empty list. Field names are normalized by stripping whitespace.
    """
    clean = str(field_name or "").strip()
    if clean not in _VALID_FIELDS:
        return []
    capped = max(1, min(MAX_VALUE_RESULTS, int(limit or DEFAULT_VALUE_RESULTS)))
    rows = s.execute(
        select(CatalogFacetValue.value, func.count(func.distinct(CatalogFacetValue.tool_name)))
        .where(CatalogFacetValue.field == clean)
        .group_by(CatalogFacetValue.value)
        .order_by(
            func.count(func.distinct(CatalogFacetValue.tool_name)).desc(),
            CatalogFacetValue.value,
        )
        .limit(capped)
    ).all()
    return [{"value": value, "toolCount": count} for value, count in rows]


def count_facet_values(s: Session, field_name: str) -> int:
    """Count distinct values for one field, so callers can report truncation.

    Field names must match the known vocabulary (_VALID_FIELDS); unknown names
    return 0. Field names are normalized by stripping whitespace.
    """
    clean = str(field_name or "").strip()
    if clean not in _VALID_FIELDS:
        return 0
    return int(
        s.execute(
            select(func.count(func.distinct(CatalogFacetValue.value))).where(CatalogFacetValue.field == clean)
        ).scalar()
        or 0
    )


def count_matching(s: Session, filters: dict[str, list[str]]) -> int:
    """Count tools matching the filters, independent of any page size.

    Filters AND across fields and OR within one field's value list.

    Field names in `filters` must match the known vocabulary (_VALID_FIELDS);
    unknown fields are rejected and return 0. Field names are normalized by
    stripping whitespace. Values are compared against the casefolded
    CatalogFacetValue.value.
    """
    clean_filters: dict[str, list[str]] = {}
    for field_name, values in (filters or {}).items():
        clean_field = str(field_name or "").strip()
        if clean_field not in _VALID_FIELDS:
            # Unknown field matches nothing
            return 0
        # Coerce non-list values (None, strings) to [] for fail-closed behavior
        value_list = values if isinstance(values, (list, tuple)) else []
        wanted = sorted({str(v or "").strip().casefold() for v in value_list if str(v or "").strip()})
        if not wanted:
            # An asked-for filter with no known value matches nothing,
            # it does not vanish from the AND.
            return 0
        clean_filters[clean_field] = wanted

    if not clean_filters:
        return 0

    # Build INTERSECT chain: each field must match at least one value
    matching = None
    for field_name, values in clean_filters.items():
        names = select(CatalogFacetValue.tool_name).where(
            CatalogFacetValue.field == field_name,
            CatalogFacetValue.value.in_(values),
        )
        matching = names if matching is None else matching.intersect(names)

    # COUNT(DISTINCT ...): a tool matching two values of one field is one tool.
    sub = matching.subquery()
    return int(s.execute(select(func.count(func.distinct(sub.c.tool_name)))).scalar() or 0)


def scanned_tool_count(s: Session) -> int:
    """Count tools with at least one APPROVED analysis report (coverage basis).

    Counts reports, not facets: a scanned repository that yielded zero
    findings is still scanned, and the coverage number is what discovery
    clients repeat to users — it must not report fewer than were scanned.
    Approved only, because facets are projected from approved reports alone:
    counting open or rejected reports would let "no scanned tool matches"
    claims rest on tools whose findings are not actually queryable.
    """
    return int(
        s.execute(
            select(func.count(func.distinct(SourceAnalysisReport.tool_name))).where(
                SourceAnalysisReport.review_status == REVIEW_APPROVED
            )
        ).scalar()
        or 0
    )
