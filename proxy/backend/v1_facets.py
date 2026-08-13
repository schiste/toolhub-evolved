# SPDX-License-Identifier: GPL-3.0-or-later
"""Public read-only facet discovery endpoints.

Answers "which tools carry signal X" (dependencies, Wikimedia APIs,
technologies) plus declared metadata, from the catalog_facet_values index. Every response
carries coverage metadata: analyzer facets exist only for tools whose source
repository has been scanned, so an empty result must never read as "no tool
does this."
"""

from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import canonical_tools, db, tool_facets
from backend.models import CanonicalToolCache, CatalogFacetValue

v1_facets_bp = Blueprint("v1_facets", __name__)

# Query parameter name -> CatalogFacetValue.field. Kept explicit so URL surface and DB
# vocabulary can evolve independently.
# Query parameter -> CatalogFacetValue.field. One table, but two families
# with different coverage: every tool has declared metadata, only scanned
# tools have detected signals. DETECTED_PARAMS is the subset the coverage
# caveat applies to.
DETECTED_PARAMS = {
    "dependency": "dependency",
    "api": "wikimedia_api",
    "technology": "detected_technology",
}
DECLARED_PARAMS = {
    "tool_type": "tool_type",
    "keyword": "keywords",
    "wiki": "wiki",
    "license": "license",
}
FILTER_PARAMS = {**DETECTED_PARAMS, **DECLARED_PARAMS}
DEFAULT_LIMIT = 25
# Hard-capped by the canonical serializer: tools_by_name truncates its input
# to MAX_QUERY_NAMES (canonical_tools.py:23,294), so asking for more would
# return husk records with empty titles for everything past the cap.
MAX_LIMIT = canonical_tools.MAX_QUERY_NAMES


def coverage(s: Session) -> dict[str, int]:
    """Scanned-vs-total tool counts every facet answer must disclose."""
    total = int(s.execute(select(func.count(CanonicalToolCache.tool_name))).scalar() or 0)
    return {"scannedTools": tool_facets.scanned_tool_count(s), "totalTools": total}


def tool_summaries(names: list[str], *, matched_by_tool: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Shared discovery tool shape, derived from cached canonical records.

    One shape across search, facets, and (later) the MCP tools, so clients
    never branch on which retrieval route produced a tool.
    """
    records = canonical_tools.tools_by_name(names)
    summaries = []
    for name in names:
        payload = records.get(name)
        record = payload.get("record") if payload else None
        source = record if isinstance(record, dict) else {}
        keywords = source.get("keywords")
        summaries.append(
            {
                "name": name,
                "title": str(source.get("title") or ""),
                "description": str(source.get("description") or ""),
                "url": str(source.get("url") or ""),
                "tool_type": str(source.get("tool_type") or ""),
                # null (not "") when absent — the published tool-record
                # contract, which the future /v1/similar-tools/ also honors.
                "repository": str(source["repository"]) if source.get("repository") else None,
                "deprecated": bool(source.get("deprecated")),
                "keywords": [str(k) for k in keywords] if isinstance(keywords, list) else [],
                "matched": matched_by_tool.get(name, []),
            }
        )
    return summaries


def dependency_values(s: Session, raw: list[str]) -> list[str]:
    """Expand bare package names to every ecosystem-prefixed stored value.

    Stored dependency values are "{ecosystem}:{name}" (source_analyzer.py);
    requiring callers to know the ecosystem would make the obvious query
    ("pywikibot") silently return nothing.
    """
    expanded: list[str] = []
    for value in raw:
        clean = str(value or "").strip().casefold()
        if not clean:
            continue
        if ":" in clean:
            expanded.append(clean)
            continue
        expanded.extend(
            s.execute(
                select(CatalogFacetValue.value)
                .where(
                    CatalogFacetValue.field == "dependency",
                    CatalogFacetValue.value.like(f"%:{clean}"),
                )
                .distinct()
            ).scalars()
        )
    return expanded


@v1_facets_bp.route("/v1/facets/tools/")
def v1_facets_tools() -> Response | tuple[Response, int]:
    """Tools matching every supplied facet filter (AND across types)."""
    limit = request.args.get("limit", "")
    try:
        capped = max(1, min(MAX_LIMIT, int(limit))) if limit else DEFAULT_LIMIT
    except ValueError:
        capped = DEFAULT_LIMIT
    with db.session_scope() as s:
        filters: dict[str, list[str]] = {}
        applied: dict[str, list[str]] = {}
        for param, facet_type in FILTER_PARAMS.items():
            raw_values = [v for raw in request.args.getlist(param) for v in raw.split(",")]
            requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
            if not requested:
                # `?dependency=` (no value at all) is not a filter and must
                # not bypass the at-least-one-filter check below.
                continue
            values = dependency_values(s, requested) if facet_type == "dependency" else requested
            cleaned = sorted({str(v).strip().casefold() for v in values if str(v).strip()})
            # An UNKNOWN value is still a filter: it legitimately matches
            # nothing (200 + empty tools), it does not invalidate the request.
            # Emptiness is decided on the raw request value above, never on
            # the expansion result — tools_matching_facets/count_matching
            # treat an asked-for-but-empty value list as matching nothing
            # (they must never drop it, which would widen the AND).
            filters[facet_type] = cleaned
            # Echo under the caller's parameter name so responses round-trip
            # into new requests without knowing internal facet-type names.
            applied[param] = cleaned or requested
        if not filters:
            return jsonify({"error": "at least one facet filter is required"}), 400
        matches = tool_facets.tools_matching_facets(s, filters, limit=capped)
        # True total, not page size: 50-of-50 and 50-of-800 must differ.
        total = tool_facets.count_matching(s, filters)
        disclosed_coverage = coverage(s)
    matched_by_tool = {m.tool_name: m.matched for m in matches}
    return jsonify(
        {
            "tools": tool_summaries([m.tool_name for m in matches], matched_by_tool=matched_by_tool),
            "total": total,
            "appliedFilters": applied,
            "coverage": disclosed_coverage,
        }
    )


@v1_facets_bp.route("/v1/facets/values/")
def v1_facets_values() -> Response | tuple[Response, int]:
    """Top distinct values for one facet type, ranked by tool adoption."""
    facet_type = str(request.args.get("type") or "").strip().casefold()
    if facet_type not in set(FILTER_PARAMS.values()):
        return jsonify({"error": f"type must be one of {sorted(FILTER_PARAMS.values())}"}), 400
    raw_limit = request.args.get("limit", "")
    try:
        limit = int(raw_limit) if raw_limit else tool_facets.DEFAULT_VALUE_RESULTS
    except ValueError:
        limit = tool_facets.DEFAULT_VALUE_RESULTS
    with db.session_scope() as s:
        values = tool_facets.facet_value_counts(s, facet_type, limit=limit)
        total = tool_facets.count_facet_values(s, facet_type)
        disclosed_coverage = coverage(s)
    return jsonify(
        {
            "type": facet_type,
            "values": [{"value": v["value"], "toolCount": v["toolCount"]} for v in values],
            "totalValues": total,
            "coverage": disclosed_coverage,
        }
    )
