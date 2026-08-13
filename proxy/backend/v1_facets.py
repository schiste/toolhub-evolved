# SPDX-License-Identifier: GPL-3.0-or-later
"""Public read-only facet discovery endpoints.

Answers "which tools carry signal X" (dependencies, Wikimedia APIs,
technologies) plus declared metadata, from the catalog_facet_values index. Every response
carries coverage metadata: analyzer facets exist only for tools whose source
repository has been scanned, so an empty result must never read as "no tool
does this."
"""

from typing import Any

from flask import Blueprint
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import canonical_tools, tool_facets
from backend.models import CanonicalToolCache

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
