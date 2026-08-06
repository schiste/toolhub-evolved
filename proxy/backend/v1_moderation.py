# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/moderation/* endpoints, split out of backend/v1.py.

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
    catalog_projection,
    db,
    v1,
)
from backend import v1_common as common
from backend.models import (
    CatalogCuration,
    PersonReconciliationConflict,
    ToolHealthTarget,
    ToolMedia,
    ToolRecord,
    ToolThanks,
    utcnow,
)
from backend.security import login_required, write_guard
from backend.sync import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
)

v1_moderation_bp = Blueprint("v1_moderation", __name__)
PEOPLE_CONFLICT_STATUSES = {"pending", "resolved", "dismissed"}


def _people_conflict_payload(row: PersonReconciliationConflict) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.conflict_type,
        "label": row.value,
        "status": row.status,
        "details": row.details if isinstance(row.details, dict) else {},
        "runId": row.run_id,
        "reviewedByUserId": row.reviewed_by_user_id,
        "reviewedAt": row.reviewed_at.isoformat(timespec="seconds") + "Z" if row.reviewed_at else "",
        "reviewNotes": row.review_notes or "",
        "lastSeenAt": row.last_seen_at.isoformat(timespec="seconds") + "Z" if row.last_seen_at else "",
        "createdAt": row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
    }


@v1_moderation_bp.route("/v1/moderation/people-conflicts/")
@login_required
def v1_moderation_people_conflicts() -> Response:
    """List identity ambiguities for Evolved operators without merging them."""
    common.require_policy_or_abort(authz.ACTION_OPERATOR)
    status = str(request.args.get("status") or "pending").strip()
    if status not in PEOPLE_CONFLICT_STATUSES:
        return common.bad("status must be pending, resolved, or dismissed")
    limit = min(max(common.clean_int(request.args.get("limit")) or 50, 1), 100)
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(PersonReconciliationConflict)
                .where(PersonReconciliationConflict.status == status)
                .order_by(
                    PersonReconciliationConflict.last_seen_at.desc(),
                    PersonReconciliationConflict.id.desc(),
                )
                .limit(limit)
            ).scalars()
        )
        results = [_people_conflict_payload(row) for row in rows]
    return jsonify({"count": len(results), "results": results, "status": status})


@v1_moderation_bp.route("/v1/moderation/people-conflicts/<int:conflict_id>/", methods=["PUT"])
@write_guard
def v1_moderation_people_conflict_update(conflict_id: int) -> Response:
    """Record an operator disposition; identity changes remain a separate audited action."""
    user = common.require_policy_or_abort(authz.ACTION_OPERATOR)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return common.bad("moderation body must be a JSON object")
    status = str(value.get("status") or "").strip()
    if status not in PEOPLE_CONFLICT_STATUSES:
        return common.bad("status must be pending, resolved, or dismissed")
    notes = str(value.get("reviewNotes") or "").strip()[:2000]
    with db.session_scope() as s:
        row = s.get(PersonReconciliationConflict, conflict_id)
        if row is None:
            return common.deny(common.HTTP_NOT_FOUND, "people conflict not found")
        row.status = status
        row.review_notes = notes or None
        row.reviewed_by_user_id = user.id if status != "pending" else None
        row.reviewed_at = utcnow() if status != "pending" else None
        payload = _people_conflict_payload(row)
        common.emit_structured_activity(
            s,
            user,
            action="people-conflict-reviewed",
            object_type="people-conflict",
            object_key=str(row.id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"status": status, "conflict": payload},
        )
    return jsonify({"ok": True, "conflict": payload})


def _moderation_row(s: Any, kind: str, item_id: int) -> object | None:  # noqa: ANN401
    return s.get(v1.MODERATION_MODELS[kind], item_id)


def _moderation_row_visible(kind: str, row: object | None) -> bool:
    if row is None:
        return False
    if getattr(row, "deleted_at", None) is not None:
        return False
    if kind == "tool-records":
        return getattr(row, "visibility", None) == common.VISIBILITY_PUBLIC
    return True


@v1_moderation_bp.route("/v1/moderation/public-data/")
@login_required
def v1_moderation_public_data() -> Response:
    """Return pending Evolved-owned public data for reviewer moderation."""
    common.require_policy_or_abort(authz.ACTION_PUBLIC_REVIEW)
    with db.session_scope() as s:
        items = [
            *[
                common.moderation_item("catalog-curations", row)
                for row in s.execute(
                    select(CatalogCuration)
                    .where(CatalogCuration.deleted_at.is_(None), CatalogCuration.review_status == REVIEW_PENDING)
                    .order_by(CatalogCuration.modified_at.desc(), CatalogCuration.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                common.moderation_item("tool-records", row)
                for row in s.execute(
                    select(ToolRecord)
                    .where(
                        ToolRecord.deleted_at.is_(None),
                        ToolRecord.visibility == common.VISIBILITY_PUBLIC,
                        ToolRecord.review_status == REVIEW_PENDING,
                    )
                    .order_by(ToolRecord.modified_at.desc(), ToolRecord.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                common.moderation_item("health-targets", row)
                for row in s.execute(
                    select(ToolHealthTarget)
                    .where(ToolHealthTarget.deleted_at.is_(None), ToolHealthTarget.review_status == REVIEW_PENDING)
                    .order_by(ToolHealthTarget.created_at.desc(), ToolHealthTarget.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                common.moderation_item("media", row)
                for row in s.execute(
                    select(ToolMedia)
                    .where(ToolMedia.deleted_at.is_(None), ToolMedia.review_status == REVIEW_PENDING)
                    .order_by(ToolMedia.created_at.desc(), ToolMedia.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                common.moderation_item("thanks", row)
                for row in s.execute(
                    select(ToolThanks)
                    .where(ToolThanks.review_status == REVIEW_PENDING)
                    .order_by(ToolThanks.created_at.desc(), ToolThanks.id.desc())
                    .limit(50)
                ).scalars()
            ],
        ]
    return jsonify(
        {
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
            "count": len(items),
            "results": items,
        }
    )


@v1_moderation_bp.route("/v1/moderation/public-data/<kind>/<int:item_id>/", methods=["PUT"])
@write_guard
def v1_moderation_public_data_update(kind: str, item_id: int) -> Response:
    """Apply reviewer moderation to one Evolved-owned public record."""
    if kind not in v1.MODERATION_KINDS:
        return common.deny(common.HTTP_NOT_FOUND, "moderation record not found")
    user = common.require_policy_or_abort(authz.ACTION_PUBLIC_REVIEW)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return common.bad("moderation body must be a JSON object")
    review_status = value.get("reviewStatus") or value.get("review_status")
    if review_status not in v1.PUBLIC_REVIEW_STATUSES:
        return common.bad("reviewStatus must be pending, approved, or rejected")
    with db.session_scope() as s:
        row = _moderation_row(s, kind, item_id)
        if not _moderation_row_visible(kind, row):
            return common.deny(common.HTTP_NOT_FOUND, "moderation record not found")
        assert row is not None  # noqa: S101 - visible check excludes None
        row.review_status = str(review_status)
        if isinstance(row, CatalogCuration):
            row.reviewed_by_user_id = user.id
            row.reviewed_at = utcnow()
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
        elif isinstance(row, ToolRecord):
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
            if review_status == REVIEW_APPROVED:
                row.visibility = common.VISIBILITY_PUBLIC
        elif isinstance(row, ToolHealthTarget):
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
        else:
            row.sync_status = SYNC_EVOLVED_REAL
        s.flush()
        item = common.moderation_item(kind, row)
        common.emit_structured_activity(
            s,
            user,
            action="public-data-reviewed",
            object_type=kind,
            object_key=str(item_id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"kind": kind, "reviewStatus": review_status, "item": item},
        )
        projection_name = row.tool_name if isinstance(row, CatalogCuration) else None
    if projection_name:
        catalog_projection.refresh_tool_names([projection_name])
    return jsonify(
        {
            "ok": True,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": common.sync_label(SYNC_EVOLVED_REAL),
            "item": item,
        }
    )
