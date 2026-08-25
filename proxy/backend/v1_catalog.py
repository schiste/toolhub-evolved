# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/catalog/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify, request

from backend import (
    activity_privacy,
    authz,
    catalog_projection,
    catalog_read,
    db,
    tool_assets,
)
from backend import v1_common as common
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
UPSTREAM = "https://toolhub.wikimedia.org"
RESOURCE_PATH_PARTS = 2


def _local_json(payload: dict, *, status: int = 200) -> Response:
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "public, max-age=30, stale-if-error=86400"
    response.headers["X-Toolhub-Evolved-Source"] = "local-replica"
    return response


@v1_catalog_bp.route("/v1/catalog/health/")
def v1_catalog_health() -> Response:
    """Expose the generation and freshness of the request-safe replica."""
    return _local_json(catalog_read.replica_status())


@v1_catalog_bp.route("/v1/catalog/", defaults={"path": ""})
@v1_catalog_bp.route("/v1/catalog/<path:path>")
def v1_catalog_read(path: str) -> Response:  # noqa: PLR0911 - explicit compatibility route dispatch
    """Serve Toolhub-compatible reads without network I/O on the request path."""
    normalized = path.strip("/")
    if normalized == "search/tools":
        return _local_json(catalog_read.search_payload(request.args))
    if normalized == "search/facets":
        return _local_json(catalog_read.facet_search_payload(request.args))
    if normalized == "ui/home":
        return _local_json(catalog_read.home_payload())
    if normalized == "lists":
        return _local_json(catalog_read.collection_payload("/api/lists/", request.args))
    if normalized == "recent":
        return _local_json(catalog_read.collection_payload("/api/recent/", request.args))
    parts = normalized.split("/") if normalized else []
    if len(parts) == RESOURCE_PATH_PARTS and parts[0] == "tools":
        payload = catalog_read.tool_payload(parts[1])
        return _local_json(payload) if payload is not None else common.deny(common.HTTP_NOT_FOUND, "tool not found")
    if len(parts) == RESOURCE_PATH_PARTS and parts[0] == "lists":
        payload = catalog_read.list_payload(parts[1])
        return _local_json(payload) if payload is not None else common.deny(common.HTTP_NOT_FOUND, "list not found")

    # Non-catalog compatibility surfaces (schema, crawler runs, audit history,
    # revisions) may still be rendered by the SPA. They are served only when a
    # scheduled job has persisted the exact response; a miss never reaches out.
    query = request.query_string.decode()
    url = f"{UPSTREAM}/api/{normalized + '/' if normalized else ''}{('?' + query) if query else ''}"
    cached = catalog_read.cached_payload(url)
    if cached is None:
        return _local_json(
            {"error": "local replica entry unavailable", "replica": catalog_read.replica_status()}, status=503
        )
    body, content_type, status = cached
    # The replica stores upstream verbatim, and the audit feed is one of the
    # surfaces upstream reports private rows on. app.py filters its own copies of
    # these same bytes in _cached_api_response; this branch reads the same store
    # and so has to make the same decision, or which endpoint a reader happens to
    # come through would decide whether they see a withheld row. Every other
    # compatibility surface is untouched: sanitize_public_api_payload keys off the
    # url and returns anything outside the activity paths byte for byte.
    response = Response(
        activity_privacy.sanitize_public_api_payload(url, body), status=status, content_type=content_type
    )
    response.headers["Cache-Control"] = "public, max-age=30, stale-if-error=86400"
    response.headers["X-Toolhub-Evolved-Source"] = "local-replica"
    return response


@v1_catalog_bp.route("/v1/catalog/tools/<name>/projection/")
def v1_catalog_tool_projection(name: str) -> Response:
    """Return one public Evolved projection with field-level evidence."""
    payload = catalog_projection.projection_payload(name)
    if payload is None:
        return common.deny(common.HTTP_NOT_FOUND, "catalog projection not found")
    return common.public_json_response(payload)


@v1_catalog_bp.route("/v1/catalog/tools/<name>/icon/")
def v1_catalog_tool_icon(name: str) -> Response:
    """Serve a previously validated icon; never fetch on this read path."""
    asset = tool_assets.cached_asset(name)
    if asset is None:
        return common.deny(common.HTTP_NOT_FOUND, "cached icon not found")
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
            return common.deny(common.HTTP_NOT_FOUND, "catalog curation not found")
        payload = common.moderation_item("catalog-curations", row)["data"]
        payload.pop("createdByUserId", None)
    return common.public_json_response(payload)


@v1_catalog_bp.route("/v1/catalog/tools/<name>/curations/", methods=["POST"])
@write_guard
def v1_catalog_curation_create(name: str) -> Response:
    """Create a bounded local correction proposal; canonical data is untouched."""
    clean_name = common.clean_name(name)
    if clean_name is None:
        return common.bad("tool name is required")
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return common.bad("curation body must be a JSON object")
    patch, errors = catalog_projection.validate_curation_patch(value.get("patch"))
    if errors:
        return common.bad("curation validation failed", errors)
    rationale = " ".join(str(value.get("rationale") or "").split()).strip()[:2000]
    if not rationale:
        return common.bad("rationale is required", [{"field": "rationale", "message": "Explain the correction."}])
    user = common.require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    with db.session_scope() as s:
        if s.get(CanonicalToolCache, clean_name) is None:
            return common.deny(common.HTTP_NOT_FOUND, "canonical tool not found")
        row = CatalogCuration(
            tool_name=clean_name,
            created_by_user_id=user.id,
            patch=patch,
            rationale=rationale,
            review_status=REVIEW_PENDING,
        )
        s.add(row)
        s.flush()
        item = common.moderation_item("catalog-curations", row)
        common.emit_structured_activity(
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
