# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/source-analysis/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import select

from backend import (
    authz,
    db,
    maintainer_index,
    people_index,
    source_analyzer,
    v1,
)
from backend import v1_common as common
from backend.models import (
    SourceAnalysisReport,
    ToolPersonRelationship,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    REVIEW_OPEN,
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
    clean_error,
    clean_int,
)

v1_source_analysis_bp = Blueprint("v1_source_analysis", __name__)


def _maintainer_context_from_summary(summary: dict) -> dict:
    """Translate normalized people relationships into source-analyzer context."""
    counts = summary.get("healthCounts") if isinstance(summary.get("healthCounts"), dict) else {}
    people = summary.get("people") if isinstance(summary.get("people"), list) else []
    if not people:
        return {}
    ages: list[int] = []
    recent_activity_count = 0
    for row in people:
        activity = row.get("activity") if isinstance(row, dict) else {}
        if not isinstance(activity, dict):
            continue
        age = clean_int(activity.get("lastContributionAgeDays"))
        if age is not None:
            ages.append(max(0, age))
        recent_activity_count += clean_int(activity.get("recentContributionCount")) or 0
    context: dict[str, Any] = {
        "maintainerCount": clean_int(counts.get("maintainers")) or 0,
        "activeMaintainerCount": clean_int(counts.get("activePeople")) or 0,
        "recentActivityCount": recent_activity_count,
        "source": "evolved-people-index",
        "analyzedAt": common.iso(utcnow()),
    }
    if ages:
        context["lastActivityAgeDays"] = min(ages)
    return context


def _source_repository_context(tool_name: str | None, repository_context: object) -> object:
    """Add Evolved maintainer context to source analysis when no caller context exists."""
    if tool_name is None or (repository_context is not None and not isinstance(repository_context, dict)):
        return repository_context
    if (
        isinstance(repository_context, dict)
        and isinstance(repository_context.get("maintainers"), dict)
        and repository_context["maintainers"]
    ):
        return repository_context
    with db.session_scope() as s:
        maintainer_index.sync_author_claim_edges(s, tool_names=[tool_name])
        person_ids = {
            row[0]
            for row in s.execute(
                select(ToolPersonRelationship.person_id).where(ToolPersonRelationship.tool_name == tool_name).distinct()
            ).all()
        }
        people_index.refresh_activity_summaries(s, person_ids=person_ids)
        summary = maintainer_index.public_tool_summary(s, tool_name)
    maintainer_context = _maintainer_context_from_summary(summary)
    if not maintainer_context:
        return repository_context
    merged = dict(repository_context or {})
    merged["maintainers"] = maintainer_context
    return merged


@v1_source_analysis_bp.route("/v1/source-analysis/")
@login_required
def v1_source_analysis_list() -> Response:
    """List source-analysis reports owned by the signed-in user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    limit = min(
        max(clean_int(request.args.get("limit")) or v1.SOURCE_ANALYSIS_DEFAULT_LIMIT, 1),
        v1.SOURCE_ANALYSIS_MAX_LIMIT,
    )
    tool_name = common.clean_name(request.args.get("tool", ""))
    stmt = select(SourceAnalysisReport).where(SourceAnalysisReport.user_id == uid)
    if tool_name is not None:
        stmt = stmt.where(SourceAnalysisReport.tool_name == tool_name)
    with db.session_scope() as s:
        reports = list(
            s.execute(
                stmt.order_by(SourceAnalysisReport.created_at.desc(), SourceAnalysisReport.id.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
    return jsonify({"count": len(reports), "results": [common.source_analysis_payload(row) for row in reports]})


@v1_source_analysis_bp.route("/v1/source-analysis/", methods=["POST"])
@write_guard
def v1_source_analysis_create() -> Response:
    """Analyze submitted source files and store the derived report."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = common.json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — common.json_object_body returned no error
    tool_name = common.clean_name(common.payload_value(body, "toolName", "tool_name"))
    source_label = str(common.payload_value(body, "sourceLabel", "source_label") or "").strip()[: common.MAX_NAME]
    repository_context = _source_repository_context(
        tool_name,
        common.payload_value(body, "repositoryContext", "repository_context"),
    )
    try:
        report = source_analyzer.analyze_source_files(
            common.payload_value(body, "files"),
            tool_name=tool_name,
            source_label=source_label,
            repository_context=repository_context,
        )
    except source_analyzer.SourceAnalysisError as exc:
        return common.bad(str(exc))
    with db.session_scope() as s:
        row = SourceAnalysisReport(
            user_id=uid,
            created_by_user_id=uid,
            tool_name=tool_name,
            source_label=source_label,
            report=report,
            review_status=REVIEW_OPEN,
            source=SOURCE_LOCAL,
            sync_status=SYNC_EVOLVED_REAL,
        )
        s.add(row)
        s.flush()
        payload = common.source_analysis_payload(row)
        common.emit_structured_activity(
            s,
            user,
            action="source-analysis-created",
            object_type="source_analysis",
            object_key=str(row.id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"toolName": tool_name, "sourceLabel": source_label},
            title=tool_name or source_label or f"Source analysis #{row.id}",
        )
    resp = jsonify({"ok": True, "sourceAnalysis": payload})
    resp.status_code = 201
    return resp


@v1_source_analysis_bp.route("/v1/source-analysis/<int:report_id>/")
@login_required
def v1_source_analysis_detail(report_id: int) -> Response:
    """Return one source-analysis report owned by the signed-in user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    common.require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        row = s.get(SourceAnalysisReport, report_id)
        if row is None or row.user_id != uid:
            return common.deny(common.HTTP_NOT_FOUND, v1.SOURCE_ANALYSIS_NOT_FOUND)
        payload = common.source_analysis_payload(row)
    return jsonify({"sourceAnalysis": payload})


@v1_source_analysis_bp.route("/v1/source-analysis/<int:report_id>/review/", methods=["POST"])
@write_guard
def v1_source_analysis_review(report_id: int) -> Response:
    """Mark one source-analysis report as open, approved, or rejected."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = common.json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — common.json_object_body returned no error
    review_status = str(common.payload_value(body, "reviewStatus", "review_status") or "").strip()
    if review_status not in v1.SOURCE_ANALYSIS_REVIEW_STATUSES:
        return common.bad("reviewStatus must be open, approved, or rejected")
    review_notes = clean_error(common.payload_value(body, "reviewNotes", "review_notes"))
    with db.session_scope() as s:
        row = s.get(SourceAnalysisReport, report_id)
        if row is None or row.user_id != uid:
            return common.deny(common.HTTP_NOT_FOUND, v1.SOURCE_ANALYSIS_NOT_FOUND)
        row.review_status = review_status
        row.review_notes = review_notes
        row.reviewed_at = None if review_status == REVIEW_OPEN else utcnow()
        payload = common.source_analysis_payload(row)
        common.emit_structured_activity(
            s,
            user,
            action=f"source-analysis-{review_status}",
            object_type="source_analysis",
            object_key=str(row.id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"toolName": row.tool_name, "reviewStatus": review_status},
            title=row.tool_name or row.source_label or f"Source analysis #{row.id}",
        )
    return jsonify({"ok": True, "sourceAnalysis": payload})
