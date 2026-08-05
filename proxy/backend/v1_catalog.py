# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/catalog/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify, request

from backend import (
    authz,
    catalog_projection,
    db,
    tool_assets,
    v1,
)
from backend.models import (
    CanonicalToolCache,
    CatalogCuration,
)
from backend.security import write_guard
from backend.sync import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SYNC_EVOLVED_REAL,
)

v1_catalog_bp = Blueprint("v1_catalog", __name__)


@v1_catalog_bp.route("/v1/catalog/tools/<name>/projection/")
def v1_catalog_tool_projection(name: str) -> Response:
    """Return one public Evolved projection with field-level evidence."""
    payload = catalog_projection.projection_payload(name)
    if payload is None:
        return v1._deny(v1.HTTP_NOT_FOUND, "catalog projection not found")
    return v1._public_json_response(payload)


@v1_catalog_bp.route("/v1/catalog/tools/<name>/icon/")
def v1_catalog_tool_icon(name: str) -> Response:
    """Serve a previously validated icon; never fetch on this read path."""
    asset = tool_assets.cached_asset(name)
    if asset is None:
        return v1._deny(v1.HTTP_NOT_FOUND, "cached icon not found")
    body, content_type, digest = asset
    etag = f'"{digest}"'
    headers = {
        "Cache-Control": "public, max-age=86400, stale-if-error=604800",
        "Content-Security-Policy": "sandbox; default-src 'none'",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers=headers)
    return Response(body, headers=headers, content_type=content_type)


@v1_catalog_bp.route("/v1/catalog/curations/<int:curation_id>/")
def v1_catalog_curation(curation_id: int) -> Response:
    """Return one approved public correction referenced by provenance."""
    with db.session_scope() as s:
        row = s.get(CatalogCuration, curation_id)
        if row is None or row.deleted_at is not None or row.review_status != REVIEW_APPROVED:
            return v1._deny(v1.HTTP_NOT_FOUND, "catalog curation not found")
        payload = v1._moderation_item("catalog-curations", row)["data"]
        payload.pop("createdByUserId", None)
    return v1._public_json_response(payload)


@v1_catalog_bp.route("/v1/catalog/tools/<name>/curations/", methods=["POST"])
@write_guard
def v1_catalog_curation_create(name: str) -> Response:
    """Create a bounded local correction proposal; canonical data is untouched."""
    clean_name = v1._clean_name(name)
    if clean_name is None:
        return v1._bad("tool name is required")
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return v1._bad("curation body must be a JSON object")
    patch, errors = catalog_projection.validate_curation_patch(value.get("patch"))
    if errors:
        return v1._bad("curation validation failed", errors)
    rationale = " ".join(str(value.get("rationale") or "").split()).strip()[:2000]
    if not rationale:
        return v1._bad("rationale is required", [{"field": "rationale", "message": "Explain the correction."}])
    user = v1._require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    with db.session_scope() as s:
        if s.get(CanonicalToolCache, clean_name) is None:
            return v1._deny(v1.HTTP_NOT_FOUND, "canonical tool not found")
        row = CatalogCuration(
            tool_name=clean_name,
            created_by_user_id=user.id,
            patch=patch,
            rationale=rationale,
            review_status=REVIEW_PENDING,
        )
        s.add(row)
        s.flush()
        item = v1._moderation_item("catalog-curations", row)
        v1._emit_structured_activity(
            s,
            user,
            action="catalog-curation-proposed",
            object_type="catalog-curations",
            object_key=str(row.id),
            official_status=SYNC_EVOLVED_REAL,
            payload=item,
        )
    response = jsonify({"ok": True, "source": SOURCE_LOCAL, "syncStatus": SYNC_EVOLVED_REAL, "item": item})
    response.status_code = 201
    return response
