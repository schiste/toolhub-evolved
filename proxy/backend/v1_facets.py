# SPDX-License-Identifier: GPL-3.0-or-later
"""Public read-only facet discovery endpoints.

Answers "which tools carry signal X" (dependencies, Wikimedia APIs,
technologies) plus declared metadata, from the catalog_facet_values index. Every response
carries coverage metadata: analyzer facets exist only for tools whose source
repository has been scanned, so an empty result must never read as "no tool
does this."
"""

from datetime import timedelta
from time import time
from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import canonical_tools, db, security, tool_facets
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
    # Toolhub's structured PURPOSE annotations — the only fields that say what
    # a tool is FOR rather than what it is built from, which is the question
    # most discovery actually starts with. Sparsely filled (~12% of a 100-tool
    # sample in Aug 2026, against ~58% for keywords), so they narrow a search
    # well but can never establish that nothing does a thing.
    "task": "tasks",
    "audience": "audiences",
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


# In-memory per-worker cache for facet value counts: (field_name, limit) -> (timestamp, values, total)
_value_cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]], int]] = {}
# Same-shaped cache for the coverage counts every discovery response carries.
_coverage_cache: dict[str, tuple[float, dict[str, int]]] = {}
VALUES_MAX_AGE = timedelta(minutes=15)


def clear_cache() -> None:
    """Clear the value-count and coverage caches (tests)."""
    _value_cache.clear()
    _coverage_cache.clear()


def cached_coverage() -> dict[str, int]:
    """Coverage counts, cached per worker for 15 minutes.

    Two COUNT(DISTINCT) aggregates that change on the same slow cadence as
    the facet values; without this the value cache built to absorb MCP
    fan-out saved one query per hit and immediately spent two here.
    """
    now = time()
    cached = _coverage_cache.get("coverage")
    if cached and now - cached[0] < VALUES_MAX_AGE.total_seconds():
        return dict(cached[1])
    with db.session_scope() as s:
        disclosed = coverage(s)
    _coverage_cache["coverage"] = (now, disclosed)
    return dict(disclosed)


def cached_facet_values(facet_type: str, *, limit: int) -> dict[str, Any]:
    """Value counts + truncation info, cached per worker for 15 minutes.

    Clamps limit to [1, MAX_VALUE_RESULTS] BEFORE the cache lookup so
    hostile ?limit= values cannot mint unbounded cache entries.
    """
    clamped = max(1, min(tool_facets.MAX_VALUE_RESULTS, int(limit or tool_facets.DEFAULT_VALUE_RESULTS)))
    key = (facet_type, clamped)
    now = time()

    # Check cache
    if key in _value_cache:
        cached_time, cached_values, cached_total = _value_cache[key]
        if now - cached_time < VALUES_MAX_AGE.total_seconds():
            return {"values": cached_values, "totalValues": cached_total}

    # Cache miss or expired: query
    with db.session_scope() as s:
        values = tool_facets.facet_value_counts(s, facet_type, limit=clamped)
        total = tool_facets.count_facet_values(s, facet_type)

    # Store in cache
    _value_cache[key] = (now, values, total)
    return {"values": values, "totalValues": total}


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
                    # Escaped: "%" must not read the whole dependency
                    # vocabulary and "my_lib" must not match "myxlib".
                    CatalogFacetValue.value.like(f"%:{canonical_tools.escape_like(clean)}", escape="\\"),
                )
                .distinct()
            ).scalars()
        )
    return expanded


def normalized_filters(
    s: Session, raw_by_param: dict[str, list[Any]]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Turn per-parameter raw values into backend filters, one rule for every surface.

    Returns (filters keyed by facet type, applied echo keyed by the caller's
    parameter name so responses round-trip into new requests). A parameter
    with no non-blank value is not a filter and is skipped. An UNKNOWN value
    is still a filter: it legitimately matches nothing, it does not
    invalidate the request. Emptiness is decided on the raw request values,
    never on the dependency-expansion result — tools_matching_facets/
    count_matching treat an asked-for-but-empty value list as matching
    nothing (they must never drop it, which would widen the AND).
    """
    filters: dict[str, list[str]] = {}
    applied: dict[str, list[str]] = {}
    for param, facet_type in FILTER_PARAMS.items():
        raw_values = raw_by_param.get(param) or []
        requested = sorted({str(v).strip().casefold() for v in raw_values if str(v).strip()})
        if not requested:
            continue
        values = dependency_values(s, requested) if facet_type == "dependency" else requested
        cleaned = sorted({str(v).strip().casefold() for v in values if str(v).strip()})
        filters[facet_type] = cleaned
        applied[param] = cleaned or requested
    return filters, applied


@v1_facets_bp.route("/v1/facets/tools/")
def v1_facets_tools() -> Response | tuple[Response, int]:
    """Tools matching every supplied facet filter (AND across types)."""
    if security.facet_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    limit = request.args.get("limit", "")
    try:
        capped = max(1, min(MAX_LIMIT, int(limit))) if limit else DEFAULT_LIMIT
    except ValueError:
        capped = DEFAULT_LIMIT
    raw_by_param: dict[str, list[Any]] = {
        param: [v for raw in request.args.getlist(param) for v in raw.split(",")] for param in FILTER_PARAMS
    }
    with db.session_scope() as s:
        filters, applied = normalized_filters(s, raw_by_param)
        if not filters:
            return jsonify({"error": "at least one facet filter is required"}), 400
        matches = tool_facets.tools_matching_facets(s, filters, limit=capped)
        # True total, not page size: 50-of-50 and 50-of-800 must differ.
        total = tool_facets.count_matching(s, filters)
    disclosed_coverage = cached_coverage()
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
    if security.facet_rate_limited(request.remote_addr):
        return jsonify({"error": "rate limited, retry later"}), 429
    facet_type = str(request.args.get("type") or "").strip().casefold()
    if facet_type not in set(FILTER_PARAMS.values()):
        return jsonify({"error": f"type must be one of {sorted(FILTER_PARAMS.values())}"}), 400
    raw_limit = request.args.get("limit", "")
    try:
        limit = int(raw_limit) if raw_limit else tool_facets.DEFAULT_VALUE_RESULTS
    except ValueError:
        limit = tool_facets.DEFAULT_VALUE_RESULTS
    listing = cached_facet_values(facet_type, limit=limit)
    disclosed_coverage = cached_coverage()
    return jsonify(
        {
            "type": facet_type,
            "values": listing["values"],
            "totalValues": listing["totalValues"],
            "coverage": disclosed_coverage,
        }
    )
