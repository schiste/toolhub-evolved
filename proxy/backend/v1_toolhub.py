# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/toolhub/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from flask import Blueprint, Response, jsonify, request

from backend import (
    authz,
    toolhub,
    v1,
)
from backend import v1_common as common
from backend.security import write_guard

v1_toolhub_bp = Blueprint("v1_toolhub", __name__)


def _official_response(method: str, path: str, payload: object | None = None) -> Response:
    """Call official Toolhub as the current user and normalize failures."""
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    try:
        body, status = toolhub.api_request(user.id, method, path, json=payload)
    except ValueError:
        # toolhub.api_path refused the path (outside /api/, or a dot segment that
        # urllib3 would normalize into an escape). Nothing left the process.
        return common.bad("invalid official Toolhub path")
    except toolhub.ToolhubAuthError as exc:
        resp = jsonify({"error": str(exc), "reauth": True})
        resp.status_code = 401
        return resp
    except toolhub.ToolhubAPIError as exc:
        resp = jsonify(
            {"error": "official Toolhub rejected the write", "status": exc.status_code, "details": exc.payload}
        )
        resp.status_code = exc.status_code
        return resp
    except toolhub.requests.RequestException:
        resp = jsonify({"error": "official Toolhub is unavailable"})
        resp.status_code = 502
        return resp
    common.invalidate_official_api_cache(path, payload, body)
    common.record_successful_toolhub_write(user, method, path, payload, body)
    if status == v1.HTTP_NO_CONTENT:
        return jsonify({"ok": True})
    resp = jsonify({"ok": True, "toolhub": body})
    resp.status_code = status
    return resp


def _official_json_response(method: str, path: str) -> Response:
    """Parse a JSON object body and forward it to official Toolhub."""
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return common.bad("body must be a JSON object")
    return _official_response(method, path, value)


@v1_toolhub_bp.route("/v1/toolhub/tools/", methods=["POST"])
@write_guard
def official_tool_create() -> Response:
    """Create an official Toolhub tool with the current user's grant."""
    return _official_json_response("POST", "/api/tools/")


@v1_toolhub_bp.route("/v1/toolhub/tools/<name>/", methods=["PUT", "DELETE"])
@write_guard
def official_tool_update(name: str) -> Response:
    """Update or delete an official Toolhub tool."""
    if request.method == "DELETE":
        return _official_response("DELETE", common.upstream_path(f"tools/{name}/"))
    return _official_json_response("PUT", common.upstream_path(f"tools/{name}/"))


@v1_toolhub_bp.route("/v1/toolhub/tools/<name>/annotations/", methods=["PUT"])
@write_guard
def official_annotations_update(name: str) -> Response:
    """Update official Toolhub annotations for a tool."""
    return _official_json_response("PUT", common.upstream_path(f"tools/{name}/annotations/"))


@v1_toolhub_bp.route("/v1/toolhub/lists/", methods=["POST"])
@write_guard
def official_list_create() -> Response:
    """Create an official Toolhub list."""
    return _official_json_response("POST", "/api/lists/")


@v1_toolhub_bp.route("/v1/toolhub/lists/<int:list_id>/", methods=["PUT", "DELETE"])
@write_guard
def official_list_update(list_id: int) -> Response:
    """Update or delete an official Toolhub list."""
    if request.method == "DELETE":
        return _official_response("DELETE", common.upstream_path(f"lists/{list_id}/"))
    return _official_json_response("PUT", common.upstream_path(f"lists/{list_id}/"))


@v1_toolhub_bp.route("/v1/toolhub/user/favorites/", methods=["POST"])
@write_guard
def official_favorite_add() -> Response:
    """Add an official Toolhub favorite."""
    return _official_json_response("POST", "/api/user/favorites/")


@v1_toolhub_bp.route("/v1/toolhub/user/favorites/<tool_name>/", methods=["DELETE"])
@write_guard
def official_favorite_delete(tool_name: str) -> Response:
    """Remove an official Toolhub favorite."""
    return _official_response("DELETE", common.upstream_path(f"user/favorites/{tool_name}/"))


@v1_toolhub_bp.route("/v1/toolhub/crawler/urls/", methods=["POST"])
@write_guard
def official_crawler_url_add() -> Response:
    """Register an official Toolhub crawler URL."""
    return _official_json_response("POST", "/api/crawler/urls/")


@v1_toolhub_bp.route("/v1/toolhub/crawler/urls/<int:url_id>/", methods=["DELETE"])
@write_guard
def official_crawler_url_delete(url_id: int) -> Response:
    """Unregister an official Toolhub crawler URL."""
    return _official_response("DELETE", common.upstream_path(f"crawler/urls/{url_id}/"))
