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
from backend.models import (
    CatalogCuration,
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


def _moderation_row(s: Any, kind: str, item_id: int) -> object | None:  # noqa: ANN401
    return s.get(v1.MODERATION_MODELS[kind], item_id)


def _moderation_row_visible(kind: str, row: object | None) -> bool:
    if row is None:
        return False
    if getattr(row, "deleted_at", None) is not None:
        return False
    if kind == "tool-records":
        return getattr(row, "visibility", None) == v1.VISIBILITY_PUBLIC
    return True


@v1_moderation_bp.route("/v1/moderation/public-data/")
@login_required
def v1_moderation_public_data() -> Response:
    """Return pending Evolved-owned public data for reviewer moderation."""
    v1._require_policy_or_abort(authz.ACTION_PUBLIC_REVIEW)
    with db.session_scope() as s:
        items = [
            *[
                v1._moderation_item("catalog-curations", row)
                for row in s.execute(
                    select(CatalogCuration)
                    .where(CatalogCuration.deleted_at.is_(None), CatalogCuration.review_status == REVIEW_PENDING)
                    .order_by(CatalogCuration.modified_at.desc(), CatalogCuration.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                v1._moderation_item("tool-records", row)
                for row in s.execute(
                    select(ToolRecord)
                    .where(
                        ToolRecord.deleted_at.is_(None),
                        ToolRecord.visibility == v1.VISIBILITY_PUBLIC,
                        ToolRecord.review_status == REVIEW_PENDING,
                    )
                    .order_by(ToolRecord.modified_at.desc(), ToolRecord.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                v1._moderation_item("health-targets", row)
                for row in s.execute(
                    select(ToolHealthTarget)
                    .where(ToolHealthTarget.deleted_at.is_(None), ToolHealthTarget.review_status == REVIEW_PENDING)
                    .order_by(ToolHealthTarget.created_at.desc(), ToolHealthTarget.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                v1._moderation_item("media", row)
                for row in s.execute(
                    select(ToolMedia)
                    .where(ToolMedia.deleted_at.is_(None), ToolMedia.review_status == REVIEW_PENDING)
                    .order_by(ToolMedia.created_at.desc(), ToolMedia.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                v1._moderation_item("thanks", row)
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
            "syncLabel": v1._sync_label(SYNC_EVOLVED_REAL),
            "count": len(items),
            "results": items,
        }
    )


@v1_moderation_bp.route("/v1/moderation/public-data/<kind>/<int:item_id>/", methods=["PUT"])
@write_guard
def v1_moderation_public_data_update(kind: str, item_id: int) -> Response:
    """Apply reviewer moderation to one Evolved-owned public record."""
    if kind not in v1.MODERATION_KINDS:
        return v1._deny(v1.HTTP_NOT_FOUND, "moderation record not found")
    user = v1._require_policy_or_abort(authz.ACTION_PUBLIC_REVIEW)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return v1._bad("moderation body must be a JSON object")
    review_status = value.get("reviewStatus") or value.get("review_status")
    if review_status not in v1.PUBLIC_REVIEW_STATUSES:
        return v1._bad("reviewStatus must be pending, approved, or rejected")
    with db.session_scope() as s:
        row = _moderation_row(s, kind, item_id)
        if not _moderation_row_visible(kind, row):
            return v1._deny(v1.HTTP_NOT_FOUND, "moderation record not found")
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
                row.visibility = v1.VISIBILITY_PUBLIC
        elif isinstance(row, ToolHealthTarget):
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
        else:
            row.sync_status = SYNC_EVOLVED_REAL
        s.flush()
        item = v1._moderation_item(kind, row)
        v1._emit_structured_activity(
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
            "syncLabel": v1._sync_label(SYNC_EVOLVED_REAL),
            "item": item,
        }
    )
