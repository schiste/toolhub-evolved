# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Evolved-local catalog projection without mutating Toolhub data."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from backend import catalog_facets, db, facet_names, wikimedia_urls
from backend.models import (
    CanonicalToolCache,
    CatalogCuration,
    CatalogFacetValue,
    CatalogToolProjection,
    RepositoryAnalysisState,
    SourceAnalysisReport,
    ToolAssetCache,
    ToolinfoDiscovery,
    ToolinfoSource,
    ToolinfoSourceItem,
    utcnow,
)
from backend.sync import REVIEW_APPROVED, SOURCE_WIKI_GADGET

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# 4: purpose annotations (tasks, audiences) are lifted out of `annotations`.
# Version 3 was already used for Wikimedia user-script maintainership, so
# existing version-3 rows must all re-project.
PROJECTION_VERSION = 4
MAX_REFRESH_TOOLS = 500
STATUS_READY = "ready"
STATUS_ERROR = "error"

SOURCE_CANONICAL = "official_toolhub"
SOURCE_CRAWLER = "official_toolinfo"
SOURCE_DISCOVERY = "self_hosted_toolinfo"
SOURCE_REPOSITORY = "repository_analysis"
SOURCE_WIKIMEDIA_USER_SCRIPT = "wikimedia_user_script"
SOURCE_CURATION = "evolved_curation"
SOURCE_GADGET = "wiki_gadget_definition"

# A canonical row records where it came from, and the projection must report
# that rather than assume. Labelling a synthesized gadget record
# `official_toolhub` would have every card, facet and evidence panel say
# Toolhub asserted something it has never heard of.
PROJECTION_SOURCE_BY_ROW = {SOURCE_WIKI_GADGET: SOURCE_GADGET}

LIST_FIELDS = (
    "keywords",
    "for_wikis",
    "technology_used",
    "tasks",
    "audiences",
    "available_ui_languages",
)
SCALAR_FIELDS = (
    "title",
    "description",
    "url",
    "repository",
    "icon",
    "tool_type",
    "license",
    "user_docs_url",
    "developer_docs_url",
    "feedback_url",
    "bugtracker_url",
    "translate_url",
    "toolinfo_url",
)
PROJECTED_FIELDS = (*SCALAR_FIELDS, *LIST_FIELDS)
# Toolhub serves these purpose fields only under `annotations`. Fields with a
# top-level counterpart deliberately stay out so source precedence is stable.
ANNOTATION_ONLY_FIELDS = ("tasks", "audiences")
URL_FIELDS = {
    "url",
    "repository",
    "icon",
    "user_docs_url",
    "developer_docs_url",
    "feedback_url",
    "bugtracker_url",
    "translate_url",
    "toolinfo_url",
}
FACET_FIELDS = facet_names.PROJECTED_FIELD_TO_STORAGE
SOURCE_CONFIDENCE = {
    SOURCE_CANONICAL: 100,
    SOURCE_CRAWLER: 95,
    SOURCE_DISCOVERY: 80,
    SOURCE_REPOSITORY: 75,
    SOURCE_WIKIMEDIA_USER_SCRIPT: 95,
    SOURCE_CURATION: 100,
    # A wiki is authoritative about what it deploys, so this outranks a
    # toolinfo.json found by guessing at an origin or inferred from a
    # repository. It stays under anything a person wrote about the tool: a
    # gadget definition states deployment facts and never claims to describe
    # what the tool is for.
    SOURCE_GADGET: 90,
}

# Report section -> CatalogFacetValue.field for signals detected in source.
# Named apart from the declared FACET_FIELDS vocabulary: "detected_technology"
# is what the analyzer found in the code, "technology" is what the toolinfo
# record claims. They are different assertions and must stay distinguishable.
ANALYZER_FACET_FIELDS = (
    ("dependencies", "dependency"),
    ("apis", "wikimedia_api"),
    ("technology", "detected_technology"),
)


def _clean_name(value: Any) -> str:  # noqa: ANN401 - job/API input
    return str(value or "").strip()[:255]


def _clean_text(value: Any) -> str:  # noqa: ANN401 - public metadata
    return " ".join(str(value or "").split()).strip()


def _values(value: Any) -> list[Any]:  # noqa: ANN401 - public metadata
    if isinstance(value, list):
        return [item for item in value if _clean_text(item)]
    return [value] if _clean_text(value) else []


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value is not None else ""


def _localized_text(value: Any) -> str:  # noqa: ANN401 - localized Toolhub fields
    if isinstance(value, dict):
        for key in ("en", "mul"):
            if text := _clean_text(value.get(key)):
                return text
        for candidate in value.values():
            if text := _clean_text(candidate):
                return text
    return _clean_text(value)


def _url_validation(value: Any) -> dict[str, Any]:  # noqa: ANN401 - public metadata
    text = _clean_text(value)
    if not text:
        return {"valid": True, "state": "empty"}
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"valid": False, "state": "invalid", "reason": "Use an absolute HTTP or HTTPS URL."}
    if parsed.username or parsed.password:
        return {"valid": False, "state": "invalid", "reason": "Credentials are not allowed in public URLs."}
    return {"valid": True, "state": "syntax_valid"}


def _casefold_deduped_list(raw: list[Any]) -> list[str]:
    """Bound a curated list value, deduping casefolded but keeping the first spelling.

    Facet rows are unique on the casefolded value, so "OCR" and "ocr" would
    collide at projection time.
    """
    seen: set[str] = set()
    clean: list[str] = []
    for item in raw:
        text = _clean_text(item)[:255]
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            clean.append(text)
    return clean[:50]


def validate_curation_patch(value: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:  # noqa: ANN401
    """Bound and validate a proposed public correction before persistence."""
    if not isinstance(value, dict):
        return {}, [{"field": "patch", "message": "patch must be an object"}]
    patch: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for field, raw in value.items():
        if field not in PROJECTED_FIELDS:
            errors.append({"field": str(field), "message": "field is not locally curatable"})
            continue
        if field in LIST_FIELDS:
            if not isinstance(raw, list):
                errors.append({"field": field, "message": "value must be a list"})
                continue
            patch[field] = _casefold_deduped_list(raw)
            continue
        clean_value = _clean_text(raw)[:4000]
        if field in URL_FIELDS:
            result = _url_validation(clean_value)
            if not result["valid"]:
                errors.append({"field": field, "message": str(result.get("reason") or "invalid URL")})
                continue
            clean_value = clean_value[:2000]
        patch[field] = clean_value
    if not patch and not errors:
        errors.append({"field": "patch", "message": "patch must contain at least one supported field"})
    return patch, errors


def _same_origin_toolinfo(tool_url: str, source_url: str) -> bool:
    """Require self-hosted toolinfo evidence to stay on the tool's origin."""
    if not tool_url or not source_url:
        return False
    tool = urlparse(tool_url)
    source = urlparse(source_url)
    tool_port = tool.port or (443 if tool.scheme == "https" else 80)
    source_port = source.port or (443 if source.scheme == "https" else 80)
    return (tool.scheme, tool.hostname, tool_port) == (source.scheme, source.hostname, source_port)


def _report_patch(row: SourceAnalysisReport | None) -> dict[str, Any]:
    report = row.report if row is not None and isinstance(row.report, dict) else {}
    suggestions = report.get("suggestions") if isinstance(report.get("suggestions"), dict) else {}
    patch = suggestions.get("toolinfoPatch")
    return patch if isinstance(patch, dict) else {}


def _latest_reports(s: Any, names: list[str]) -> dict[str, SourceAnalysisReport]:  # noqa: ANN401
    """Get the newest report per tool, handling NULL timestamps correctly.

    Uses NULLs-last ordering to prefer reviewed_at over created_at,
    with id tiebreak for determinism. Matches graph_enrichment._latest_reports.
    """
    rows = list(
        s.execute(
            select(SourceAnalysisReport)
            .where(SourceAnalysisReport.tool_name.in_(names), SourceAnalysisReport.review_status == REVIEW_APPROVED)
            .order_by(
                SourceAnalysisReport.tool_name,
                SourceAnalysisReport.reviewed_at.is_(None),  # NULLs last
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


def _latest_report_times(s: Session) -> dict[str, datetime]:
    """Get the newest report timestamp for each tool without loading full report rows.

    Returns a dict mapping tool_name -> timestamp of the newest report, preferring
    reviewed_at over created_at (via coalesce). Filters to REVIEW_APPROVED reports.
    Uses the same coalesce logic as _latest_reports to ensure consistency.
    """
    rows = list(
        s.execute(
            select(
                SourceAnalysisReport.tool_name,
                func.max(func.coalesce(SourceAnalysisReport.reviewed_at, SourceAnalysisReport.created_at)).label(
                    "latest_timestamp"
                ),
            )
            .where(SourceAnalysisReport.review_status == REVIEW_APPROVED)
            .group_by(SourceAnalysisReport.tool_name)
        )
    )
    return {row.tool_name: row.latest_timestamp for row in rows if row.tool_name}


def _sources_by_tool(  # noqa: C901 - source joins stay explicit and auditable.
    s: Session, names: list[str], reports: dict[str, SourceAnalysisReport] | None = None
) -> dict[str, list[dict[str, Any]]]:
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    canonical = s.execute(select(CanonicalToolCache).where(CanonicalToolCache.tool_name.in_(names))).scalars()
    for row in canonical:
        if isinstance(row.record, dict):
            source = PROJECTION_SOURCE_BY_ROW.get(row.source, SOURCE_CANONICAL)
            sources[row.tool_name].append(
                {"payload": row.record, "source": source, "url": row.source_url, "observed": row.fetched_at}
            )
            tool_url = _clean_text(row.record.get("url"))
            if wikimedia_urls.user_space_javascript_page(tool_url) is not None:
                sources[row.tool_name].append(
                    {
                        "payload": {"repository": tool_url},
                        "source": SOURCE_WIKIMEDIA_USER_SCRIPT,
                        "url": tool_url,
                        "observed": row.fetched_at,
                    }
                )

    crawler_rows = s.execute(
        select(ToolinfoSourceItem, ToolinfoSource)
        .join(ToolinfoSource, ToolinfoSourceItem.source_id == ToolinfoSource.id)
        .where(ToolinfoSourceItem.tool_name.in_(names), ToolinfoSource.valid.is_(True))
        .order_by(ToolinfoSource.official_id.is_(None), ToolinfoSource.official_id, ToolinfoSource.id)
    ).all()
    for item, source in crawler_rows:
        if isinstance(item.payload, dict):
            sources[item.tool_name].append(
                {
                    "payload": item.payload,
                    "source": SOURCE_CRAWLER,
                    "url": item.source_url,
                    "observed": source.last_fetched_at or item.last_seen_at,
                }
            )

    discoveries = s.execute(
        select(ToolinfoDiscovery).where(ToolinfoDiscovery.tool_name.in_(names), ToolinfoDiscovery.status == "found")
    ).scalars()
    for row in discoveries:
        if isinstance(row.payload, dict) and row.toolinfo_url and _same_origin_toolinfo(row.tool_url, row.toolinfo_url):
            sources[row.tool_name].append(
                {
                    "payload": row.payload,
                    "source": SOURCE_DISCOVERY,
                    "url": row.toolinfo_url,
                    "observed": row.checked_at,
                }
            )

    if reports is None:
        reports = _latest_reports(s, names)
    repository_rows = {
        row.tool_name: row
        for row in s.execute(
            select(RepositoryAnalysisState).where(RepositoryAnalysisState.tool_name.in_(names))
        ).scalars()
    }
    for name, report in reports.items():
        if patch := _report_patch(report):
            repository = repository_rows.get(name)
            sources[name].append(
                {
                    "payload": patch,
                    "source": SOURCE_REPOSITORY,
                    "url": repository.repository_url if repository is not None else report.source_label,
                    "observed": report.reviewed_at or report.created_at,
                }
            )

    curations = s.execute(
        select(CatalogCuration)
        .where(
            CatalogCuration.tool_name.in_(names),
            CatalogCuration.review_status == REVIEW_APPROVED,
            CatalogCuration.deleted_at.is_(None),
        )
        .order_by(CatalogCuration.modified_at, CatalogCuration.id)
    ).scalars()
    for row in curations:
        if isinstance(row.patch, dict):
            sources[row.tool_name].append(
                {
                    "payload": row.patch,
                    "source": SOURCE_CURATION,
                    "url": f"/v1/catalog/curations/{row.id}/",
                    "observed": row.reviewed_at or row.modified_at,
                }
            )
    return sources


def _lift_purpose_annotations(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy Toolhub's annotation-only purpose fields to the merge boundary."""
    annotations = payload.get("annotations")
    if not isinstance(annotations, dict):
        return payload
    lifted = {
        field: annotations[field]
        for field in ANNOTATION_ONLY_FIELDS
        if not payload.get(field) and annotations.get(field)
    }
    return {**payload, **lifted} if lifted else payload


def _assemble(  # noqa: C901, PLR0912 - precedence and evidence must remain in one ordered pass.
    name: str, sources: list[dict[str, Any]]
) -> tuple[dict, dict, dict, dict]:
    effective: dict[str, Any] = {"name": name}
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_timestamps: dict[str, str] = {}
    curations: dict[str, Any] = {}

    for source_row in sources:
        payload = _lift_purpose_annotations(source_row["payload"])
        source = source_row["source"]
        observed = _iso(source_row.get("observed"))
        if observed:
            source_timestamps[source] = max(observed, source_timestamps.get(source, ""))
        for field in PROJECTED_FIELDS:
            field_values = _values(payload.get(field))
            if not field_values:
                continue
            for value in field_values:
                validation = _url_validation(value) if field in URL_FIELDS else {"valid": True, "state": "accepted"}
                entry = {
                    "value": value,
                    "source": source,
                    "sourceUrl": source_row.get("url") or "",
                    "observedAt": observed,
                    "confidence": SOURCE_CONFIDENCE[source],
                    "effective": False,
                    **validation,
                }
                evidence[field].append(entry)
            if source == SOURCE_CURATION:
                curations[field] = payload.get(field)
            elif field in LIST_FIELDS:
                merged = {_clean_text(item).casefold(): item for item in _values(effective.get(field))}
                for value in field_values:
                    merged.setdefault(_clean_text(value).casefold(), value)
                effective[field] = list(merged.values())
            elif field not in effective and any(item.get("valid") for item in evidence[field][-len(field_values) :]):
                effective[field] = payload.get(field)

    # Approved local corrections are the only source allowed to replace an
    # existing canonical scalar. Invalid corrections remain evidence only.
    for field, value in curations.items():
        field_evidence = [item for item in evidence[field] if item["source"] == SOURCE_CURATION]
        if field not in URL_FIELDS or any(item.get("valid") for item in field_evidence):
            effective[field] = value

    validation: dict[str, dict[str, Any]] = {}
    for field, rows in evidence.items():
        current_values = {_clean_text(item).casefold() for item in _values(effective.get(field))}
        for item in rows:
            item["effective"] = item.get("valid", True) and _clean_text(item["value"]).casefold() in current_values
        effective_rows = [item for item in rows if item["effective"]]
        invalid_rows = [item for item in rows if not item.get("valid", True)]
        validation[field] = {
            "valid": bool(effective_rows) and not any(not item.get("valid", True) for item in effective_rows),
            "invalidEvidenceCount": len(invalid_rows),
            "state": "valid" if effective_rows else "missing",
        }
    return effective, dict(evidence), validation, source_timestamps


def _search_text(record: dict[str, Any]) -> str:
    parts = [record.get("name"), _localized_text(record.get("title")), _localized_text(record.get("description"))]
    parts.extend(_clean_text(value) for field in LIST_FIELDS for value in _values(record.get(field)))
    return "\n".join(part for part in (_clean_text(value) for value in parts) if part).casefold()[:12000]


def _analyzer_facets(report: dict | None) -> list[tuple[str, str, str, int]]:
    """Return (field, value, label, confidence_basis_points) per detected signal.

    Pure so it can be exercised without a database. Duplicate values keep the
    highest confidence: the analyzer emits one finding per evidence source.

    Confidence convention: for detected facets, confidence_basis_points means
    DETECTION CERTAINTY (finding confidence x 10000), as opposed to the
    DECLARED facets where it means SOURCE AUTHORITY.
    """
    if not isinstance(report, dict):
        return []

    # Collect all findings, indexed by (field, value) for deduplication
    findings: dict[tuple[str, str], tuple[str, int]] = {}

    for report_section, facet_field in ANALYZER_FACET_FIELDS:
        section_data = report.get(report_section)
        if not isinstance(section_data, list):
            continue

        for entry in section_data:
            if not isinstance(entry, dict):
                continue

            raw_value = _clean_text(entry.get("value"))
            if not raw_value:
                continue

            # Sanitize value and label for valid UTF-8, casefold and truncate to 255
            value = raw_value.encode("utf-8", "ignore").decode("utf-8").casefold()[:255]

            # Label from finding's label else value, sanitized and truncated to 255
            label = (
                _clean_text(entry.get("label") or entry.get("value")).encode("utf-8", "ignore").decode("utf-8")[:255]
            )

            # Missing, unparseable, or non-finite confidence drops the finding:
            # tool_facets.py documents these rows as detection certainty, and a
            # finding the analyzer would not publish must not become queryable
            # with certainty 0 attached.
            try:
                confidence_float = float(entry.get("confidence"))
                if not math.isfinite(confidence_float):
                    continue
                confidence_float = max(0.0, min(1.0, confidence_float))
            except (TypeError, ValueError):
                continue

            confidence_basis_points = round(confidence_float * 10000)

            # Keep max confidence for (field, value)
            key = (facet_field, value)
            if key not in findings or findings[key][1] < confidence_basis_points:
                findings[key] = (label, confidence_basis_points)

    # Return as list of tuples
    return [
        (field, value, label, confidence_basis_points)
        for (field, value), (label, confidence_basis_points) in findings.items()
    ]


def _emit_analyzer_facets(
    s: Any,  # noqa: ANN401
    name: str,
    report: SourceAnalysisReport,
    now: datetime,
) -> None:
    """Emit analyzer-derived facets for one tool from its latest report.

    Wraps analyzer emission in its own savepoint so malformed reports
    cannot cost a tool its declared facets or fail the batch.
    """
    try:
        with s.begin_nested():
            facet_provenance = [
                {
                    "source": SOURCE_REPOSITORY,
                    "reportId": report.id,
                    "observed": _iso(report.reviewed_at or report.created_at),
                }
            ]
            for field, value, label, confidence_basis_points in _analyzer_facets(report.report):
                s.add(
                    CatalogFacetValue(
                        tool_name=name,
                        field=field,
                        value=value,
                        label=label,
                        provenance=facet_provenance,
                        confidence_basis_points=confidence_basis_points,
                        refreshed_at=now,
                    )
                )
            s.flush()
    except (SQLAlchemyError, TypeError, ValueError, OverflowError, ArithmeticError):
        # Malformed report must not cost the tool its declared facets or fail the batch.
        # OverflowError/ArithmeticError can be raised by round(x*10000) if confidence is extreme.
        _log.warning("Failed to emit analyzer facets for %s report %s", name, report.id)


def _replace_facets(s: Any, name: str, record: dict, provenance: dict, now: datetime) -> None:  # noqa: ANN401
    """Emit declared facets for the tool from the merged effective record.

    Analyzer facets are emitted separately via _emit_analyzer_facets.
    This separation allows containment: a malformed report cannot cost the tool
    its declared facets because emission failures roll back within a savepoint.
    """
    s.execute(delete(CatalogFacetValue).where(CatalogFacetValue.tool_name == name))

    # Emit declared facets from the effective merged record. Guard the
    # (tool_name, field, value) unique constraint here too: values reach this
    # point from several sources and a single case-variant pair would fail
    # the whole refresh batch with an IntegrityError.
    seen: set[tuple[str, str]] = set()
    for record_field, facet_field in FACET_FIELDS.items():
        for value in _values(record.get(record_field)):
            label = _clean_text(value)[:255]
            if not label or (facet_field, label.casefold()) in seen:
                continue
            seen.add((facet_field, label.casefold()))
            source_rows = [
                item
                for item in provenance.get(record_field, [])
                if _clean_text(item.get("value")).casefold() == label.casefold()
            ]
            s.add(
                CatalogFacetValue(
                    tool_name=name,
                    field=facet_field,
                    value=label.casefold(),
                    label=label,
                    provenance=source_rows,
                    confidence_basis_points=max(
                        (int(item.get("confidence", 0)) * 100 for item in source_rows), default=0
                    ),
                    refreshed_at=now,
                )
            )


def _preserve_url_checks(record: dict, validation: dict, previous: Any) -> dict:  # noqa: ANN401
    """Carry a probe result forward only while its effective URL is unchanged."""
    old = previous if isinstance(previous, dict) else {}
    for field in URL_FIELDS:
        prior = old.get(field) if isinstance(old.get(field), dict) else {}
        value = _clean_text(record.get(field))
        if value and prior.get("checkedValue") == value:
            validation.setdefault(field, {}).update(
                {
                    key: prior[key]
                    for key in (
                        "checkedValue",
                        "reachable",
                        "statusCode",
                        "contentType",
                        "finalUrl",
                        "checkedAt",
                        "lastError",
                    )
                    if key in prior
                }
            )
    return validation


def _mark_failures(names: list[str], error: BaseException) -> None:
    try:
        with db.session_scope() as s:
            for name in names:
                row = s.get(CatalogToolProjection, name) or CatalogToolProjection(tool_name=name)
                s.add(row)
                row.status = STATUS_ERROR
                row.attempts = (row.attempts or 0) + 1
                row.next_attempt_at = utcnow() + timedelta(hours=min(24, 2 ** min(row.attempts, 4)))
                row.last_error = _clean_text(error)[:1000]
    except SQLAlchemyError:
        pass


def _refresh_batch(names: list[str]) -> dict[str, int]:
    """Refresh a batch of tools' catalog projections.

    Per-batch row budget: with analyzer facets, inserts per batch include both
    declared and analyzer facets. Analyzer rows cap at ~120/tool (source_analyzer's
    MAX_FINDINGS_PER_BUCKET), so a 500-tool batch can insert ~60k analyzer rows
    plus declared facets in one transaction.
    """
    if not names:
        return {"requested": 0, "refreshed": 0, "changed": 0, "errors": 0}
    now = utcnow()
    changed = 0
    try:
        with db.session_scope() as s:
            # Fetch reports once per batch before the per-tool loop
            reports = _latest_reports(s, names)
            source_map = _sources_by_tool(s, names, reports)
            for name in names:
                effective, provenance, validation, timestamps = _assemble(name, source_map.get(name, []))
                row = s.get(CatalogToolProjection, name)
                if row is None:
                    row = CatalogToolProjection(tool_name=name)
                    s.add(row)
                validation = _preserve_url_checks(effective, validation, row.validation)
                if (
                    row.effective_record != effective
                    or row.provenance != provenance
                    or row.validation != validation
                    or row.projection_version != PROJECTION_VERSION
                ):
                    changed += 1
                row.effective_record = effective
                row.provenance = provenance
                row.validation = validation
                row.source_timestamps = timestamps
                row.search_text = _search_text(effective)
                row.projection_version = PROJECTION_VERSION
                row.status = STATUS_READY
                row.refreshed_at = now
                row.next_attempt_at = None
                row.attempts = 0
                row.last_error = None
                _replace_facets(s, name, effective, provenance, now)
                if report := reports.get(name):
                    _emit_analyzer_facets(s, name, report, now)
            # One dirty marker per batch, not one metadata round trip per tool.
            # The scheduled projection pass publishes the replacement aggregate
            # after the authoritative facet rows commit.
            catalog_facets.mark_dirty(s)
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        _mark_failures(names, exc)
        return {"requested": len(names), "refreshed": 0, "changed": 0, "errors": len(names)}
    return {"requested": len(names), "refreshed": len(names), "changed": changed, "errors": 0}


def refresh_tool_names(tool_names: list[str]) -> dict[str, int]:
    names = list(dict.fromkeys(name for value in tool_names if (name := _clean_name(value))))
    summary = {"requested": len(names), "refreshed": 0, "changed": 0, "errors": 0}
    for offset in range(0, len(names), MAX_REFRESH_TOOLS):
        batch = _refresh_batch(names[offset : offset + MAX_REFRESH_TOOLS])
        for key in ("refreshed", "changed", "errors"):
            summary[key] += batch[key]
    return summary


def refresh_candidates(limit: int = MAX_REFRESH_TOOLS) -> dict[str, int]:
    bounded = max(1, min(MAX_REFRESH_TOOLS, int(limit or 1)))
    now = utcnow()
    with db.session_scope() as s:
        canonical = list(s.execute(select(CanonicalToolCache.tool_name)).scalars())
        existing = {row.tool_name: row for row in s.execute(select(CatalogToolProjection)).scalars()}
        # Fetch latest report timestamps to detect newly-analyzed tools (lightweight query)
        latest_report_times = _latest_report_times(s)
        analyzer_facet_tools = set(
            s.execute(
                select(CatalogFacetValue.tool_name)
                .where(CatalogFacetValue.field.in_(field for _, field in ANALYZER_FACET_FIELDS))
                .distinct()
            ).scalars()
        )
    candidates = []
    for name in canonical:
        row = existing.get(name)
        if row is not None and row.next_attempt_at is not None and row.next_attempt_at > now:
            continue
        if row is None or row.projection_version != PROJECTION_VERSION or row.status == STATUS_ERROR:
            candidates.append(name)
        elif (
            (report_timestamp := latest_report_times.get(name))
            and row.refreshed_at
            and report_timestamp > row.refreshed_at
            and report_timestamp <= now
        ):
            # Include tools whose latest report is newer than their projection,
            # but clamp to now() to avoid perpetual-candidate issue with future-dated reports.
            candidates.append(name)
        elif name in analyzer_facet_tools and name not in latest_report_times:
            # Serving analyzer facets with no approved report left behind them:
            # the report was rejected or reopened after projection. Re-project
            # so the moderated-away facets stop being served.
            candidates.append(name)
    names = sorted(candidates)[:bounded]
    summary = {"candidates": len(candidates), **refresh_tool_names(names)}
    catalog_facets.rebuild_global_payload()
    return summary


def projection_payload(name: str) -> dict[str, Any] | None:
    clean = _clean_name(name)
    if not clean:
        return None
    with db.session_scope() as s:
        row = s.get(CatalogToolProjection, clean)
        asset = s.get(ToolAssetCache, clean)
    if row is None or row.projection_version != PROJECTION_VERSION:
        return None
    return {
        "toolName": row.tool_name,
        "record": row.effective_record,
        "provenance": row.provenance,
        "validation": row.validation,
        "sourceTimestamps": row.source_timestamps,
        "projectionVersion": row.projection_version,
        "status": row.status,
        "refreshedAt": _iso(row.refreshed_at),
        "lastError": row.last_error or "",
        "asset": {
            "status": asset.status,
            "sourceUrl": asset.source_url,
            "source": asset.source_type,
            "contentType": asset.content_type,
            "checkedAt": _iso(asset.checked_at),
            "lastError": asset.last_error or "",
            "url": f"/v1/catalog/tools/{clean}/icon/" if asset.status == "ready" else "",
        }
        if asset is not None
        else {"status": "pending", "url": ""},
    }
