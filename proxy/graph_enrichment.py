# SPDX-License-Identifier: GPL-3.0-or-later
"""Repair and audit provenance-aware graph facet materialization."""

from __future__ import annotations

import json
import os
import sys

from backend import DEFAULT_DB_URL, db, graph_payload
from backend import graph_enrichment as enrichment

DEFAULT_LIMIT = 500
MAX_LIMIT = 1000


def _limit() -> int:
    try:
        return max(1, min(MAX_LIMIT, int(os.environ.get("GRAPH_ENRICHMENT_LIMIT", DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def audit_payload(repair: dict[str, int]) -> dict:
    """Return compact job health and graph-facet coverage diagnostics."""
    graph = graph_payload.build(limit=graph_payload.DEFAULT_NODE_LIMIT, group_by="technology")
    coverage = {
        item["id"]: {
            "covered": item["covered"],
            "total": item["total"],
            "coverage": item["coverage"],
            "distinctValues": item["distinctValues"],
            "enabled": item["enabled"],
        }
        for item in graph["groupingMeta"]
    }
    technology_labels = [str(item.get("label") or "") for item in graph["groupMeta"] if item.get("id") != "other"]
    platform_labels = set(graph_payload.PLATFORM_ALIASES.values())
    return {
        "repair": repair,
        "status": enrichment.status_summary(),
        "nodeLimit": graph["nodeLimit"],
        "nodes": len(graph["nodes"]),
        "coverage": coverage,
        "technologyPlatformLeakage": sorted(platform_labels.intersection(technology_labels)),
        "compoundTechnologyGroups": sorted(label for label in technology_labels if "," in label or ";" in label),
        "enrichmentVersion": enrichment.ENRICHMENT_VERSION,
    }


def main() -> int:
    db.configure(os.environ.get("TOOLHUB_DB_URL") or DEFAULT_DB_URL)
    db.init_schema()
    repair = enrichment.refresh_candidates(limit=_limit())
    audit = audit_payload(repair)
    sys.stdout.write("graph-enrichment: " + json.dumps(audit, sort_keys=True, separators=(",", ":")) + "\n")
    return 1 if repair.get("errors") else 0


if __name__ == "__main__":  # pragma: no cover - exercised through main() tests and Toolforge Jobs
    raise SystemExit(main())
