# SPDX-License-Identifier: GPL-3.0-or-later
"""Materialize provenance-aware facets consumed by the public tool graph."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend import api_cache, db
from backend.models import (
    CanonicalToolCache,
    GraphToolEnrichment,
    SourceAnalysisReport,
    ToolinfoDiscovery,
    ToolinfoSource,
    ToolinfoSourceItem,
    utcnow,
)
from backend.sync import REVIEW_APPROVED

ENRICHMENT_VERSION = 1
# Measured 2026-08-27: this sweep costs 0.049s a tool and was capped at 500,
# so it finished in 24 seconds of its hour against a catalogue of 53,178. The cap is
# a safety rail against a runaway loop, not a throughput setting; sized here so
# the whole catalogue is reachable within one run's share of the interval.
MAX_REFRESH_TOOLS = 20_000
# Rows per fetch for the two full-table scans; see `refresh_candidates`.
STREAM_BATCH_SIZE = 500
LIST_FIELDS = ("for_wikis", "technology_used", "tasks", "audiences", "available_ui_languages")
SCALAR_FIELDS = ("tool_type",)
FACET_FIELDS = (*LIST_FIELDS, *SCALAR_FIELDS)
STATUS_ENRICHED = "enriched"
STATUS_OFFICIAL_ONLY = "official_only"
STATUS_NO_METADATA = "no_metadata"
STATUS_ERROR = "error"
SOURCE_CANONICAL = "official_toolhub"
SOURCE_CRAWLER = "official_toolinfo"
SOURCE_DISCOVERY = "self_hosted_toolinfo"
SOURCE_REPOSITORY = "repository_analysis"


def _clean_name(value: Any) -> str:  # noqa: ANN401 - job/API inputs
    return str(value or "").strip()[:255]


def _clean_value(value: Any) -> str:  # noqa: ANN401 - public metadata
    return " ".join(str(value or "").split()).strip()


def _values(value: Any) -> list[str]:  # noqa: ANN401 - public metadata
    if isinstance(value, list):
        return [clean for item in value if (clean := _clean_value(item))]
    clean = _clean_value(value)
    return [clean] if clean else []


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value is not None else ""


def _report_patch(row: SourceAnalysisReport | None) -> dict[str, Any]:
    report = row.report if row is not None and isinstance(row.report, dict) else {}
    suggestions = report.get("suggestions") if isinstance(report.get("suggestions"), dict) else {}
    return suggestions.get("toolinfoPatch") if isinstance(suggestions.get("toolinfoPatch"), dict) else {}


def _source_rows(s: Any, names: list[str]) -> dict[str, list[tuple[dict[str, Any], str, datetime | None]]]:  # noqa: ANN401
    out: dict[str, list[tuple[dict[str, Any], str, datetime | None]]] = defaultdict(list)
    rows = s.execute(
        select(ToolinfoSourceItem, ToolinfoSource)
        .join(ToolinfoSource, ToolinfoSourceItem.source_id == ToolinfoSource.id)
        .where(ToolinfoSourceItem.tool_name.in_(names), ToolinfoSource.valid.is_(True))
        .order_by(ToolinfoSource.official_id.is_(None), ToolinfoSource.official_id, ToolinfoSource.id)
    ).all()
    for item, source in rows:
        if isinstance(item.payload, dict):
            out[item.tool_name].append((item.payload, SOURCE_CRAWLER, source.last_fetched_at or item.last_seen_at))
    return out


def _latest_reports(s: Any, names: list[str]) -> dict[str, SourceAnalysisReport]:  # noqa: ANN401
    rows = list(
        s.execute(
            select(SourceAnalysisReport)
            .where(
                SourceAnalysisReport.tool_name.in_(names),
                SourceAnalysisReport.review_status == REVIEW_APPROVED,
            )
            .order_by(
                SourceAnalysisReport.tool_name,
                SourceAnalysisReport.reviewed_at.is_(None),
                SourceAnalysisReport.reviewed_at.desc(),
                SourceAnalysisReport.created_at.desc(),
                SourceAnalysisReport.id.desc(),
            )
        ).scalars()
    )
    out: dict[str, SourceAnalysisReport] = {}
    for row in rows:
        if row.tool_name:
            out.setdefault(row.tool_name, row)
    return out


def _merge_sources(  # noqa: C901 - one pass keeps value ordering and provenance in lockstep
    sources: list[tuple[dict[str, Any], str, datetime | None]],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, str], bool]:
    values: dict[str, dict[str, str]] = {field: {} for field in LIST_FIELDS}
    provenance: dict[str, dict[str, dict[str, Any]]] = {field: {} for field in FACET_FIELDS}
    scalar_values: dict[str, str] = {}
    source_timestamps: dict[str, str] = {}
    derived_seen = False
    for payload, source, observed_at in sources:
        timestamp = _iso(observed_at)
        if timestamp and timestamp > source_timestamps.get(source, ""):
            source_timestamps[source] = timestamp
        if source != SOURCE_CANONICAL and any(_values(payload.get(field)) for field in FACET_FIELDS):
            derived_seen = True
        for field in LIST_FIELDS:
            for value in _values(payload.get(field)):
                key = value.casefold()
                values[field].setdefault(key, value)
                entry = provenance[field].setdefault(key, {"value": values[field][key], "sources": []})
                evidence = {"source": source}
                if timestamp:
                    evidence["observedAt"] = timestamp
                if evidence not in entry["sources"]:
                    entry["sources"].append(evidence)
        for field in SCALAR_FIELDS:
            field_values = _values(payload.get(field))
            if not field_values:
                continue
            value = field_values[0]
            key = value.casefold()
            scalar_values.setdefault(field, value)
            entry = provenance[field].setdefault(key, {"value": value, "sources": []})
            evidence = {"source": source}
            if timestamp:
                evidence["observedAt"] = timestamp
            if evidence not in entry["sources"]:
                entry["sources"].append(evidence)
    facets: dict[str, Any] = {
        field: list(field_values.values()) for field, field_values in values.items() if field_values
    }
    facets.update({field: value for field, value in scalar_values.items() if value})
    serialized_provenance = {field: list(entries.values()) for field, entries in provenance.items() if entries}
    return facets, serialized_provenance, source_timestamps, derived_seen


def _mark_failures(names: list[str], error: BaseException) -> None:
    try:
        with db.session_scope() as s:
            for name in names:
                row = s.get(GraphToolEnrichment, name)
                if row is None:
                    row = GraphToolEnrichment(tool_name=name)
                    s.add(row)
                row.status = STATUS_ERROR
                row.attempts = (row.attempts or 0) + 1
                row.next_attempt_at = utcnow() + timedelta(hours=min(24, 2 ** min(row.attempts, 4)))
                row.last_error = _clean_value(error)[:1000]
    except SQLAlchemyError:
        pass


def _refresh_batch(names: list[str]) -> dict[str, int]:
    """Rebuild one bounded batch of exact canonical tool names."""
    if not names:
        return {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    now = utcnow()
    changed = 0
    try:
        with db.session_scope() as s:
            canonical = {
                row.tool_name: row
                for row in s.execute(
                    select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(names))
                ).scalars()
            }
            crawler = _source_rows(s, names)
            discoveries = {
                row.tool_name: row
                for row in s.execute(select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name.in_(names))).scalars()
            }
            reports = _latest_reports(s, names)
            for name in names:
                canonical_row = canonical.get(name)
                sources: list[tuple[dict[str, Any], str, datetime | None]] = []
                if canonical_row is not None and isinstance(canonical_row.record, dict):
                    sources.append((canonical_row.record, SOURCE_CANONICAL, canonical_row.fetched_at))
                sources.extend(crawler.get(name, []))
                discovery = discoveries.get(name)
                if discovery is not None and isinstance(discovery.payload, dict):
                    sources.append((discovery.payload, SOURCE_DISCOVERY, discovery.checked_at))
                report = reports.get(name)
                patch = _report_patch(report)
                if patch:
                    sources.append((patch, SOURCE_REPOSITORY, report.reviewed_at or report.created_at))
                facets, provenance, timestamps, derived_seen = _merge_sources(sources)
                row = s.get(GraphToolEnrichment, name)
                if row is None:
                    row = GraphToolEnrichment(tool_name=name)
                    s.add(row)
                next_status = (
                    STATUS_ENRICHED if derived_seen else STATUS_OFFICIAL_ONLY if facets else STATUS_NO_METADATA
                )
                if (
                    row.facets != facets
                    or row.provenance != provenance
                    or row.enrichment_version != ENRICHMENT_VERSION
                    or row.status != next_status
                ):
                    changed += 1
                row.facets = facets
                row.provenance = provenance
                row.source_timestamps = timestamps
                row.enrichment_version = ENRICHMENT_VERSION
                row.status = next_status
                row.attempts = 0
                row.refreshed_at = now
                row.next_attempt_at = None
                row.last_error = None
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        _mark_failures(names, exc)
        return {"requested": len(names), "refreshed": 0, "changed": 0, "errors": len(names)}
    if changed:
        api_cache.invalidate_graph()
    return {"requested": len(names), "refreshed": len(names), "changed": changed, "errors": 0}


def refresh_tool_names(tool_names: list[str]) -> dict[str, int]:
    """Rebuild all requested names in bounded database batches."""
    names = list(dict.fromkeys(name for value in tool_names if (name := _clean_name(value))))
    summary = {"requested": len(names), "refreshed": 0, "changed": 0, "errors": 0}
    for offset in range(0, len(names), MAX_REFRESH_TOOLS):
        batch = _refresh_batch(names[offset : offset + MAX_REFRESH_TOOLS])
        for key in ("refreshed", "changed", "errors"):
            summary[key] += batch[key]
    # Every producer already refreshes graph enrichment after changing public
    # evidence. Chaining the catalog projection here gives those producers one
    # transaction-safe integration point and keeps projection work off reads.
    from backend import catalog_projection  # noqa: PLC0415 - avoid backend startup cycles.

    catalog_projection.refresh_tool_names(names)
    return summary


def refresh_candidates(limit: int = 500) -> dict[str, int]:
    """Repair missing, failed, or old-version enrichment rows in priority order."""
    bounded = max(1, min(MAX_REFRESH_TOOLS, int(limit or 1)))
    now = utcnow()
    candidates = []
    with db.session_scope() as s:
        # Columns, not entities, and the canonical scan streams. The
        # scheduling side reads four scalars, so loading `GraphToolEnrichment`
        # whole also dragged in its `facets` blob for every tool; the canonical
        # side genuinely needs `record`, which is why it is the one that gets
        # `yield_per` -- only a batch of payloads is resident at a time, and
        # the loop keeps just the small priority tuples. Loading both tables
        # whole is what OOM-killed this job on every hourly tick for a day
        # once discovery opened up to every Wikimedia project.
        existing = {
            row.tool_name: row
            for row in s.execute(
                select(
                    GraphToolEnrichment.tool_name,
                    GraphToolEnrichment.next_attempt_at,
                    GraphToolEnrichment.enrichment_version,
                    GraphToolEnrichment.status,
                )
            )
        }
        canonical = s.execute(
            select(CanonicalToolCache.tool_name, CanonicalToolCache.record).execution_options(
                yield_per=STREAM_BATCH_SIZE
            )
        )
        for row in canonical:
            enrichment = existing.get(row.tool_name)
            if enrichment is not None and enrichment.next_attempt_at is not None and enrichment.next_attempt_at > now:
                continue
            stale = enrichment is None or enrichment.enrichment_version != ENRICHMENT_VERSION
            failed = enrichment is not None and enrichment.status == STATUS_ERROR
            if not stale and not failed:
                continue
            record = row.record if isinstance(row.record, dict) else {}
            graph_eligible = bool(_values(record.get("keywords")) or _values(record.get("tasks")))
            missing = sum(not _values(record.get(field)) for field in FACET_FIELDS)
            candidates.append((not graph_eligible, -missing, row.tool_name))
    names = [name for _eligible, _missing, name in sorted(candidates)[:bounded]]
    return {"candidates": len(candidates), **refresh_tool_names(names)}


def merge_cached_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Overlay materialized facets on canonical payload rows without writing."""
    names = [_clean_name(row.get("toolName")) for row in rows]
    names = [name for name in names if name]
    if not names:
        return rows
    with db.session_scope() as s:
        enrichments = {
            row.tool_name: row
            for row in s.execute(
                select(GraphToolEnrichment).where(
                    GraphToolEnrichment.tool_name.in_(names),
                    GraphToolEnrichment.enrichment_version == ENRICHMENT_VERSION,
                )
            ).scalars()
        }
    out = []
    for payload in rows:
        item = dict(payload)
        record = dict(item.get("record")) if isinstance(item.get("record"), dict) else {}
        enrichment = enrichments.get(_clean_name(item.get("toolName")))
        facets = enrichment.facets if enrichment is not None and isinstance(enrichment.facets, dict) else {}
        for field in LIST_FIELDS:
            merged: dict[str, str] = {}
            for value in [*_values(record.get(field)), *_values(facets.get(field))]:
                merged.setdefault(value.casefold(), value)
            if merged:
                record[field] = list(merged.values())
        for field in SCALAR_FIELDS:
            if not _values(record.get(field)) and _values(facets.get(field)):
                record[field] = _values(facets.get(field))[0]
        item["record"] = record
        out.append(item)
    return out


def status_summary() -> dict[str, int]:
    """Return compact operational counts for the repair/audit job."""
    counts: dict[str, int] = defaultdict(int)
    materialized = 0
    with db.session_scope() as s:
        canonical = s.query(CanonicalToolCache).count()
        # Two columns, streamed: this only tallies, and a `GraphToolEnrichment`
        # row carries a `facets` blob none of these counters look at.
        rows = s.execute(
            select(GraphToolEnrichment.status, GraphToolEnrichment.enrichment_version).execution_options(
                yield_per=STREAM_BATCH_SIZE
            )
        )
        for row in rows:
            materialized += 1
            counts[row.status or "pending"] += 1
            if row.enrichment_version != ENRICHMENT_VERSION:
                counts["stale_version"] += 1
    return {"canonical": canonical, "materialized": materialized, **dict(sorted(counts.items()))}
