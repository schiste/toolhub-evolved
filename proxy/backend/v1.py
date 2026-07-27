# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1 JSON API: session info + the synced overlay, plus public feeds.

The SPA keeps using localStorage as its synchronous overlay cache; when a real
session exists it pulls GET /v1/overlay/ into that cache and pushes every
mutation back with PUT /v1/overlay/<key> (write-through). Payload shapes are
therefore exactly the shapes the SPA already stores (lib/core/store.js).

Per-user keys (favorites, lists, crawlerUrls) use replace semantics. Overlay
keys (toolEdits, toolAnnos, toolNew) replace only the calling user's rows; the
assembled GET merges all users' rows, newest first. Feed keys (revisions,
auditlogs) are append-only, idempotent by client id.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Blueprint, Response, abort, jsonify, request, session
from sqlalchemy import delete, func, or_, select, text

from backend import authz, db, toolhub
from backend.models import (
    ActivityRow,
    CrawlerRun,
    CrawlerUrl,
    Favorite,
    ToolEvent,
    ToolHealthTarget,
    ToolList,
    ToolMedia,
    ToolOverlay,
    ToolRecord,
    ToolThanks,
    User,
    utcnow,
)
from backend.oauth import configured as oauth_configured
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
    SYNC_ERROR,
    SYNC_EVOLVED_REAL,
    SYNC_LOCAL_DRAFT,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
    clean_error,
    clean_int,
    clean_review_status,
    clean_source,
    clean_sync_status,
)

v1_bp = Blueprint("v1", __name__)

HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_NO_CONTENT = 204
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
MAX_ITEMS = 500  # per overlay key per user
MAX_NAME = 255
FEED_READ_CAP = 100
FEED_KEEP_CAP = 500
OVERLAY_KINDS = {"toolEdits": "edits", "toolAnnos": "annos"}
FEED_KEYS = ("revisions", "auditlogs")
VISIBILITY_PRIVATE = "private"
VISIBILITY_PUBLIC = "public"
EVENT_TYPES = {"view", "launch", "save", "list_add"}
META_KEYS = {
    "source",
    "syncStatus",
    "syncLabel",
    "lastSyncedAt",
    "lastError",
    "createdByUserId",
    "created_by_user_id",
    "deletedAt",
    "deleted_at",
    "officialId",
    "officialName",
    "visibility",
    "toolhubResponse",
    "validationErrors",
    "baseRevision",
    "fieldStatuses",
    "reviewStatus",
}
CANONICAL_TOOL_KEYS = {"name", "origin"}


def _iso(dt: datetime | None) -> str:
    """Naive-UTC column value → ISO-8601 with the Z suffix the SPA emits."""
    return dt.isoformat(timespec="seconds") + "Z" if dt else ""


def _parse_iso(value: Any) -> datetime:  # noqa: ANN401 — untrusted JSON in
    """Client ISO timestamp → naive UTC datetime (now() when absent/invalid)."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return utcnow()
    return parsed if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)


def _parse_optional_iso(value: Any) -> datetime | None:  # noqa: ANN401 — untrusted JSON in
    """Client ISO timestamp → naive UTC datetime, preserving absence."""
    if value in (None, ""):
        return None
    return _parse_iso(value)


def _payload_value(payload: dict, camel: str, snake: str | None = None) -> Any:  # noqa: ANN401
    """Read either frontend camelCase or backend snake_case metadata keys."""
    if camel in payload:
        return payload.get(camel)
    return payload.get(snake or camel)


def _visibility(value: Any, default: str = VISIBILITY_PRIVATE) -> str:  # noqa: ANN401
    return value if value in {VISIBILITY_PRIVATE, VISIBILITY_PUBLIC} else default


def _clean_name(value: str) -> str | None:
    value = str(value or "").strip()
    return value[:MAX_NAME] if value else None


def _is_http_url(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, str) and value.startswith(("http://", "https://")) and len(value) <= MAX_URL


def _media_payload(row: ToolMedia) -> dict:
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "url": row.url,
        "title": row.title,
        "license": row.license,
        "source": row.source,
        "reviewStatus": row.review_status,
        "createdAt": _iso(row.created_at),
    }


def _sync_label(status: str | None) -> str:
    labels = {
        SYNC_OFFICIAL: "Official Toolhub",
        SYNC_LOCAL_DRAFT: "Local draft",
        SYNC_LOCAL_FALLBACK: "Local fallback",
        SYNC_EVOLVED_REAL: "Evolved data",
        SYNC_ERROR: "Sync error",
    }
    return labels.get(status or "", "Local draft")


def _with_common_meta(payload: dict, row: object, *, include_official_id: bool = False) -> dict:
    """Attach provenance fields without disturbing legacy payload shapes."""
    out = dict(payload)
    source = getattr(row, "source", None) or SOURCE_LOCAL
    status = getattr(row, "sync_status", None) or SYNC_LOCAL_DRAFT
    out["source"] = source
    out["syncStatus"] = status
    out["syncLabel"] = _sync_label(status)
    if getattr(row, "last_synced_at", None):
        out["lastSyncedAt"] = _iso(row.last_synced_at)
    if getattr(row, "last_error", None):
        out["lastError"] = row.last_error
    if include_official_id and getattr(row, "official_list_id", None) is not None:
        out["officialId"] = row.official_list_id
    if include_official_id and getattr(row, "official_crawler_url_id", None) is not None:
        out["officialId"] = row.official_crawler_url_id
        out["id"] = row.official_crawler_url_id
    return out


def _local_tool_is_public(row: ToolRecord) -> bool:
    """Public Evolved records are searchable/feedable; private drafts are not."""
    record = row.record if isinstance(row.record, dict) else {}
    is_public = row.visibility == VISIBILITY_PUBLIC or record.get("origin") == "crawler"
    default_review = REVIEW_APPROVED if record.get("origin") == "crawler" else REVIEW_PENDING
    return is_public and clean_review_status(getattr(row, "review_status", None), default_review) == REVIEW_APPROVED


def _tool_record_payload(row: ToolRecord) -> dict:
    record = row.record if isinstance(row.record, dict) else {}
    out = _with_common_meta(record, row)
    out["visibility"] = row.visibility or VISIBILITY_PRIVATE
    default_review = REVIEW_APPROVED if record.get("origin") == "crawler" else REVIEW_PENDING
    out["reviewStatus"] = clean_review_status(getattr(row, "review_status", None), default_review)
    if row.official_name:
        out["officialName"] = row.official_name
    if row.last_toolhub_response:
        out["toolhubResponse"] = row.last_toolhub_response
    if row.validation_errors:
        out["validationErrors"] = row.validation_errors
    return out


def _bad(error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = HTTP_BAD_REQUEST
    return resp


def _deny(status: int, error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = status
    return resp


def _current_policy_user() -> tuple[User | None, Response | None]:
    """Fetch the session user for Evolved-local policy checks."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required/write_guard guarantees this
    with db.session_scope() as s:
        user = s.get(User, uid)
    if user is None:
        session.clear()
        return None, _deny(HTTP_UNAUTHORIZED, "sign in required")
    return user, None


def _enforce(user: User, action: str, resource: object | None = None) -> Response | None:
    """Return a 403 when the Evolved-local policy rejects the action."""
    return None if authz.can(user, action, resource) else _deny(HTTP_FORBIDDEN, "not allowed")


def _require_policy(action: str, resource: object | None = None) -> tuple[User | None, Response | None]:
    """Fetch the current user and enforce one Evolved-local policy action."""
    user, denied = _current_policy_user()
    if denied is not None:
        return None, denied
    assert user is not None  # noqa: S101 — _current_policy_user returned no denial
    denied = _enforce(user, action, resource)
    if denied is not None:
        return None, denied
    return user, None


def _require_policy_or_abort(action: str, resource: object | None = None) -> User:
    """Return the current user or abort with a normalized policy response."""
    user, denied = _require_policy(action, resource)
    if denied is not None:
        abort(denied)
    assert user is not None  # noqa: S101 — _require_policy returned no denial
    return user


def _upstream_path(fragment: str) -> str:
    """Build a fixed official Toolhub API path from a route fragment."""
    return f"/api/{fragment.lstrip('/')}"


def _official_response(method: str, path: str, payload: object | None = None) -> Response:
    """Call official Toolhub as the current user and normalize failures."""
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    try:
        body, status = toolhub.api_request(user.id, method, path, json=payload)
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
    if status == HTTP_NO_CONTENT:
        return jsonify({"ok": True})
    resp = jsonify({"ok": True, "toolhub": body})
    resp.status_code = status
    return resp


def _official_json_response(method: str, path: str) -> Response:
    """Parse a JSON object body and forward it to official Toolhub."""
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return _bad("body must be a JSON object")
    return _official_response(method, path, value)


@v1_bp.route("/healthz")
def healthz() -> Response:
    """Liveness + database reachability (used by uptime monitoring)."""
    try:
        with db.session_scope() as s:
            s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — a health probe reports any failure the same way
        resp = jsonify({"ok": False})
        resp.status_code = 503
        return resp
    return jsonify({"ok": True})


@v1_bp.route("/v1/user/")
def v1_user() -> Response:
    """Who am I? Adds the CSRF token the write endpoints require."""
    uid = current_user_id()
    if uid is None:
        return jsonify({"authenticated": False})
    with db.session_scope() as s:
        user = s.get(User, uid)
        if user is None:  # stale cookie for a deleted account
            session.clear()
            return jsonify({"authenticated": False})
        role = authz.user_role(user)
        return jsonify(
            {
                "authenticated": True,
                "username": user.username,
                "csrf": session.get("csrf", ""),
                "evolvedRole": role,
                "evolvedRoleLabel": authz.role_label(role),
                "evolvedPermissions": authz.role_permissions(role),
            }
        )


@v1_bp.route("/v1/config/")
def v1_config() -> Response:
    """Report which production capabilities are configured (no secrets)."""
    return jsonify({"oauth": oauth_configured(), "officialWrites": oauth_configured()})


@v1_bp.route("/v1/toolhub/tools/", methods=["POST"])
@write_guard
def official_tool_create() -> Response:
    """Create an official Toolhub tool with the current user's grant."""
    return _official_json_response("POST", "/api/tools/")


@v1_bp.route("/v1/toolhub/tools/<name>/", methods=["PUT", "DELETE"])
@write_guard
def official_tool_update(name: str) -> Response:
    """Update or delete an official Toolhub tool."""
    if request.method == "DELETE":
        return _official_response("DELETE", _upstream_path(f"tools/{name}/"))
    return _official_json_response("PUT", _upstream_path(f"tools/{name}/"))


@v1_bp.route("/v1/toolhub/tools/<name>/annotations/", methods=["PUT"])
@write_guard
def official_annotations_update(name: str) -> Response:
    """Update official Toolhub annotations for a tool."""
    return _official_json_response("PUT", _upstream_path(f"tools/{name}/annotations/"))


@v1_bp.route("/v1/toolhub/lists/", methods=["POST"])
@write_guard
def official_list_create() -> Response:
    """Create an official Toolhub list."""
    return _official_json_response("POST", "/api/lists/")


@v1_bp.route("/v1/toolhub/lists/<int:list_id>/", methods=["PUT", "DELETE"])
@write_guard
def official_list_update(list_id: int) -> Response:
    """Update or delete an official Toolhub list."""
    if request.method == "DELETE":
        return _official_response("DELETE", _upstream_path(f"lists/{list_id}/"))
    return _official_json_response("PUT", _upstream_path(f"lists/{list_id}/"))


@v1_bp.route("/v1/toolhub/user/favorites/", methods=["POST"])
@write_guard
def official_favorite_add() -> Response:
    """Add an official Toolhub favorite."""
    return _official_json_response("POST", "/api/user/favorites/")


@v1_bp.route("/v1/toolhub/user/favorites/<tool_name>/", methods=["DELETE"])
@write_guard
def official_favorite_delete(tool_name: str) -> Response:
    """Remove an official Toolhub favorite."""
    return _official_response("DELETE", _upstream_path(f"user/favorites/{tool_name}/"))


@v1_bp.route("/v1/toolhub/crawler/urls/", methods=["POST"])
@write_guard
def official_crawler_url_add() -> Response:
    """Register an official Toolhub crawler URL."""
    return _official_json_response("POST", "/api/crawler/urls/")


@v1_bp.route("/v1/toolhub/crawler/urls/<int:url_id>/", methods=["DELETE"])
@write_guard
def official_crawler_url_delete(url_id: int) -> Response:
    """Unregister an official Toolhub crawler URL."""
    return _official_response("DELETE", _upstream_path(f"crawler/urls/{url_id}/"))


def _merged_maps(kind_rows: list[Any]) -> dict[str, dict]:
    """Merge rows (any user) into {tool_name: payload}.

    Rows arrive oldest first, so the most recently modified contribution wins
    each name.
    """
    out: dict[str, dict] = {}
    for row in kind_rows:
        if isinstance(row, ToolOverlay):
            payload = _with_common_meta(row.patch if isinstance(row.patch, dict) else {}, row)
            if row.base_revision:
                payload["baseRevision"] = row.base_revision
            if row.field_statuses:
                payload["fieldStatuses"] = row.field_statuses
            if row.review_status:
                payload["reviewStatus"] = row.review_status
            out[row.tool_name] = payload
        else:
            out[row.tool_name] = row.record
    return out


def _assemble_overlay(uid: int) -> dict[str, Any]:
    with db.session_scope() as s:
        favorites = [
            f.tool_name
            for f in s.execute(select(Favorite).where(Favorite.user_id == uid).order_by(Favorite.position)).scalars()
        ]
        lists = [
            _with_common_meta(
                {
                    "id": row.client_id,
                    "title": row.title,
                    "description": row.description,
                    "tools": row.tools,
                    "created": _iso(row.created_at),
                    "modified": _iso(row.modified_at),
                },
                row,
                include_official_id=True,
            )
            for row in s.execute(
                select(ToolList)
                .where(ToolList.user_id == uid, ToolList.deleted_at.is_(None))
                .order_by(ToolList.created_at.desc())
            ).scalars()
        ]
        crawler_urls = [
            _with_common_meta(
                {
                    "url": c.url,
                    "added": _iso(c.added_at),
                    "localId": c.id,
                    "enabled": c.enabled,
                    "lastCheckedAt": _iso(c.last_checked_at),
                    "lastStatus": c.last_status or "",
                },
                c,
                include_official_id=True,
            )
            for c in s.execute(
                select(CrawlerUrl)
                .where(CrawlerUrl.user_id == uid, CrawlerUrl.enabled.is_(True))
                .order_by(CrawlerUrl.added_at.desc())
            ).scalars()
        ]
        overlays = {
            key: _merged_maps(
                list(
                    s.execute(
                        select(ToolOverlay).where(ToolOverlay.kind == kind).order_by(ToolOverlay.modified_at)
                    ).scalars()
                ),
            )
            for key, kind in OVERLAY_KINDS.items()
        }
        tool_new = {
            row.tool_name: _tool_record_payload(row)
            for row in s.execute(
                select(ToolRecord)
                .where(
                    ToolRecord.deleted_at.is_(None),
                    or_(ToolRecord.user_id == uid, ToolRecord.visibility == VISIBILITY_PUBLIC),
                )
                .order_by(ToolRecord.modified_at)
            ).scalars()
            if row.user_id == uid or _local_tool_is_public(row)
        }
        feeds = {
            key: [
                r.row
                for r in s.execute(
                    select(ActivityRow)
                    .where(ActivityRow.kind == key)
                    .order_by(ActivityRow.created_at.desc(), ActivityRow.id.desc())
                    .limit(FEED_READ_CAP)
                ).scalars()
            ]
            for key in FEED_KEYS
        }
    return {
        "favorites": favorites,
        "lists": lists,
        "crawlerUrls": crawler_urls,
        "toolNew": tool_new,
        **overlays,
        **feeds,
    }


@v1_bp.route("/v1/overlay/")
@login_required
def v1_overlay_get() -> Response:
    """Return the full overlay in the SPA's localStorage shapes (one pull at sign-in)."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    return jsonify(_assemble_overlay(uid))


def _put_favorites(uid: int, value: Any) -> Response | None:  # noqa: ANN401
    if not isinstance(value, list) or not all(isinstance(n, str) and 0 < len(n) <= MAX_NAME for n in value):
        return _bad("favorites must be a list of tool names")
    names = list(dict.fromkeys(value))[:MAX_ITEMS]
    with db.session_scope() as s:
        s.execute(delete(Favorite).where(Favorite.user_id == uid))
        s.add_all(
            [
                Favorite(
                    user_id=uid,
                    created_by_user_id=uid,
                    tool_name=n,
                    position=i,
                    source=SOURCE_LOCAL,
                    sync_status=SYNC_LOCAL_DRAFT,
                )
                for i, n in enumerate(names)
            ]
        )
    return None


def _put_lists(uid: int, value: Any) -> Response | None:  # noqa: ANN401
    if not isinstance(value, list):
        return _bad("lists must be a list")
    for item in value[:MAX_ITEMS]:
        ok = (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("title"), str)
            and isinstance(item.get("tools"), list)
        )
        if not ok:
            return _bad("each list needs id, title and tools")
    with db.session_scope() as s:
        s.execute(delete(ToolList).where(ToolList.user_id == uid))
        for item in value[:MAX_ITEMS]:
            official_id = clean_int(_payload_value(item, "officialId", "official_list_id"))
            default_status = SYNC_OFFICIAL if official_id is not None else SYNC_LOCAL_DRAFT
            sync_status = clean_sync_status(_payload_value(item, "syncStatus", "sync_status"), default_status)
            last_synced_at = _parse_optional_iso(_payload_value(item, "lastSyncedAt", "last_synced_at"))
            if sync_status == SYNC_OFFICIAL and last_synced_at is None:
                last_synced_at = _parse_iso(item.get("modified"))
            s.add(
                ToolList(
                    client_id=str(item["id"])[:64],
                    user_id=uid,
                    created_by_user_id=uid,
                    title=str(item["title"])[:MAX_NAME],
                    description=str(item.get("description", "")),
                    tools=[str(t)[:MAX_NAME] for t in item["tools"][:MAX_ITEMS]],
                    created_at=_parse_iso(item.get("created")),
                    modified_at=_parse_iso(item.get("modified")),
                    official_list_id=official_id,
                    source=clean_source(
                        _payload_value(item, "source"),
                        SOURCE_OFFICIAL if official_id else SOURCE_LOCAL,
                    ),
                    sync_status=sync_status,
                    last_synced_at=last_synced_at,
                    last_error=clean_error(_payload_value(item, "lastError", "last_error")),
                )
            )
    return None


def _put_crawler_urls(uid: int, value: Any) -> Response | None:  # noqa: ANN401
    ok = isinstance(value, list) and all(
        isinstance(u, dict) and isinstance(u.get("url"), str) and u["url"].startswith("https://") for u in value
    )
    if not ok:
        return _bad("crawlerUrls must be a list of {url (https), added}")
    with db.session_scope() as s:
        s.execute(delete(CrawlerUrl).where(CrawlerUrl.user_id == uid))
        for u in value[:MAX_ITEMS]:
            official_id = clean_int(_payload_value(u, "officialId") if "officialId" in u else u.get("id"))
            default_status = SYNC_OFFICIAL if official_id is not None else SYNC_LOCAL_DRAFT
            sync_status = clean_sync_status(_payload_value(u, "syncStatus", "sync_status"), default_status)
            last_synced_at = _parse_optional_iso(_payload_value(u, "lastSyncedAt", "last_synced_at"))
            if sync_status == SYNC_OFFICIAL and last_synced_at is None:
                last_synced_at = _parse_iso(u.get("added"))
            s.add(
                CrawlerUrl(
                    user_id=uid,
                    created_by_user_id=uid,
                    url=str(u["url"])[:2000],
                    added_at=_parse_iso(u.get("added")),
                    official_crawler_url_id=official_id,
                    source=clean_source(_payload_value(u, "source"), SOURCE_OFFICIAL if official_id else SOURCE_LOCAL),
                    enabled=bool(u.get("enabled", True)),
                    last_checked_at=_parse_optional_iso(_payload_value(u, "lastCheckedAt", "last_checked_at")),
                    last_status=str(_payload_value(u, "lastStatus", "last_status") or "")[:64] or None,
                    last_error=clean_error(_payload_value(u, "lastError", "last_error")),
                    sync_status=sync_status,
                    last_synced_at=last_synced_at,
                )
            )
    return None


def _valid_map(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, dict) and all(
        isinstance(k, str) and 0 < len(k) <= MAX_NAME and isinstance(v, dict) for k, v in value.items()
    )


MAX_DESCRIPTION = 5000
MAX_URL = 2000
_STR_LIST_FIELDS = ("keywords", "forWikis", "uiLanguages")
_OPT_STR_FIELDS = ("repository", "license", "toolType")


def _clean_tool_record(rec: dict) -> dict | None:
    """Validate + whitelist a toolNew record; None when it can't be a tool.

    The stored shape is exactly what the public feed and search render, so a
    signed-in client must never be able to persist a record that breaks them
    (missing url, non-list keywords, …).
    """
    title, description, url = rec.get("title"), rec.get("description"), rec.get("url")
    text_ok = isinstance(title, str) and title.strip() and isinstance(description, str)
    if not (text_ok and isinstance(url, str) and url.startswith("https://")):
        return None
    clean: dict[str, Any] = {
        "title": title[:MAX_NAME],
        "description": description[:MAX_DESCRIPTION],
        "url": url[:MAX_URL],
        "deprecated": bool(rec.get("deprecated")),
        "experimental": bool(rec.get("experimental")),
        "origin": "crawler" if rec.get("origin") == "crawler" else "api",
    }
    for field in _OPT_STR_FIELDS:
        raw = rec.get(field)
        clean[field] = raw[:MAX_NAME] if isinstance(raw, str) and raw else None
    for field in _STR_LIST_FIELDS:
        raw = rec.get(field)
        items = raw if isinstance(raw, list) else []
        clean[field] = [str(item)[:MAX_NAME] for item in items[:50] if isinstance(item, str | int | float)]
    return clean


def _tool_record_meta(
    rec: dict,
    *,
    can_review: bool = False,
    existing_review_status: str | None = None,
) -> dict[str, Any]:
    """Extract lifecycle metadata from a toolNew payload."""
    is_crawler_record = rec.get("origin") == "crawler"
    visibility = _visibility(
        _payload_value(rec, "visibility"), VISIBILITY_PUBLIC if is_crawler_record else VISIBILITY_PRIVATE
    )
    default_review = REVIEW_APPROVED if is_crawler_record else REVIEW_PENDING
    preserved_review = clean_review_status(existing_review_status, default_review)
    review_status = (
        clean_review_status(_payload_value(rec, "reviewStatus", "review_status"), preserved_review)
        if can_review
        else preserved_review
    )
    default_status = SYNC_EVOLVED_REAL if visibility == VISIBILITY_PUBLIC else SYNC_LOCAL_DRAFT
    status = clean_sync_status(_payload_value(rec, "syncStatus", "sync_status"), default_status)
    source = clean_source(_payload_value(rec, "source"), SOURCE_LOCAL)
    official_name = _payload_value(rec, "officialName", "official_name")
    response = _payload_value(rec, "toolhubResponse", "last_toolhub_response")
    validation_errors = _payload_value(rec, "validationErrors", "validation_errors")
    return {
        "visibility": visibility,
        "source": source,
        "sync_status": status,
        "review_status": review_status,
        "last_synced_at": _parse_optional_iso(_payload_value(rec, "lastSyncedAt", "last_synced_at")),
        "last_error": clean_error(_payload_value(rec, "lastError", "last_error")),
        "official_name": str(official_name)[:MAX_NAME] if isinstance(official_name, str) and official_name else None,
        "last_toolhub_response": response if isinstance(response, dict) else None,
        "validation_errors": validation_errors if isinstance(validation_errors, list) else None,
    }


def _overlay_meta(
    patch: dict,
    *,
    can_review: bool = False,
    existing_review_status: str | None = None,
) -> dict[str, Any]:
    """Extract lifecycle metadata from a toolEdits/toolAnnos payload."""
    field_statuses = _payload_value(patch, "fieldStatuses", "field_statuses")
    preserved_review = clean_review_status(existing_review_status, REVIEW_OPEN)
    return {
        "base_revision": str(_payload_value(patch, "baseRevision", "base_revision") or "")[:MAX_NAME] or None,
        "field_statuses": field_statuses if isinstance(field_statuses, dict) else None,
        "source": clean_source(_payload_value(patch, "source"), SOURCE_LOCAL),
        "sync_status": clean_sync_status(
            _payload_value(patch, "syncStatus", "sync_status"),
            SYNC_LOCAL_FALLBACK if _payload_value(patch, "lastError", "last_error") else SYNC_LOCAL_DRAFT,
        ),
        "last_synced_at": _parse_optional_iso(_payload_value(patch, "lastSyncedAt", "last_synced_at")),
        "last_error": clean_error(_payload_value(patch, "lastError", "last_error")),
        "review_status": (
            clean_review_status(_payload_value(patch, "reviewStatus", "review_status"), preserved_review)
            if can_review
            else preserved_review
        ),
    }


def _data_patch(patch: dict) -> dict:
    """Remove lifecycle metadata before merging a local overlay into a tool."""
    return {k: v for k, v in patch.items() if k not in META_KEYS and k not in CANONICAL_TOOL_KEYS}


def _put_tool_new(uid: int, entries: dict[str, dict], s: Any, *, can_review: bool = False) -> Response | None:  # noqa: ANN401
    # A tool name registered by someone else is not writable here: the pulled
    # cache holds the globally merged view, so a client legitimately pushes
    # other users' records back verbatim — those must never be re-owned.
    # Edits to other people's tools flow through the toolEdits/toolAnnos
    # overlays instead.
    others = {r.tool_name for r in s.execute(select(ToolRecord).where(ToolRecord.user_id != uid)).scalars()}
    existing_own = {r.tool_name: r for r in s.execute(select(ToolRecord).where(ToolRecord.user_id == uid)).scalars()}
    cleaned: dict[str, tuple[dict, dict[str, Any]]] = {}
    for name, rec in entries.items():
        if name in others:
            continue  # echo of (or attempt on) another user's registration
        clean = _clean_tool_record(rec)
        if clean is None:
            return _bad(f"toolNew record '{name}' needs title, description and an https url")
        cleaned[name] = (
            clean,
            _tool_record_meta(
                rec,
                can_review=can_review,
                existing_review_status=getattr(existing_own.get(name), "review_status", None),
            ),
        )
    s.execute(delete(ToolRecord).where(ToolRecord.user_id == uid))
    s.add_all(
        [
            ToolRecord(tool_name=n, user_id=uid, created_by_user_id=uid, record=rec, modified_at=utcnow(), **meta)
            for n, (rec, meta) in cleaned.items()
        ]
    )
    return None


def _put_tool_map(uid: int, value: Any, *, key: str, user: User) -> Response | None:  # noqa: ANN401
    if not _valid_map(value):
        return _bad(f"{key} must be a map of tool name to object")
    entries = dict(list(value.items())[:MAX_ITEMS])
    with db.session_scope() as s:
        can_review = authz.can(user, authz.ACTION_PUBLIC_REVIEW)
        if key == "toolNew":
            return _put_tool_new(uid, entries, s, can_review=can_review)
        kind = OVERLAY_KINDS[key]
        # Echo suppression: entries identical to another user's current overlay
        # came in via the merged pull — replaying them must not create a copy
        # owned by the caller. Only genuinely new/changed patches are theirs.
        others = {
            r.tool_name: r.patch
            for r in s.execute(
                select(ToolOverlay).where(ToolOverlay.kind == kind, ToolOverlay.user_id != uid)
            ).scalars()
        }
        own = {n: patch for n, patch in entries.items() if others.get(n) != _data_patch(patch)}
        existing_own = {
            r.tool_name: r
            for r in s.execute(
                select(ToolOverlay).where(ToolOverlay.kind == kind, ToolOverlay.user_id == uid)
            ).scalars()
        }
        s.execute(delete(ToolOverlay).where(ToolOverlay.user_id == uid, ToolOverlay.kind == kind))
        s.add_all(
            [
                ToolOverlay(
                    kind=kind,
                    tool_name=n,
                    user_id=uid,
                    created_by_user_id=uid,
                    patch=_data_patch(patch),
                    modified_at=utcnow(),
                    **_overlay_meta(
                        patch,
                        can_review=can_review,
                        existing_review_status=getattr(existing_own.get(n), "review_status", None),
                    ),
                )
                for n, patch in own.items()
            ]
        )
    return None


def _put_feed(uid: int, value: Any, *, key: str) -> Response | None:  # noqa: ANN401
    ok = isinstance(value, list) and all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in value)
    if not ok:
        return _bad(f"{key} must be a list of rows with string ids")
    with db.session_scope() as s:
        # Dedupe globally, not per user: pulled feeds are global, so clients
        # push other users' rows back — those must not be duplicated under the
        # caller's account.
        known = set(s.execute(select(ActivityRow.client_id).where(ActivityRow.kind == key)).scalars())
        for row in value[:MAX_ITEMS]:
            if row["id"] not in known:
                known.add(row["id"])  # a payload may repeat an id — insert once
                s.add(
                    ActivityRow(
                        kind=key,
                        client_id=str(row["id"])[:64],
                        user_id=uid,
                        created_by_user_id=uid,
                        row=row,
                        created_at=_parse_iso(row.get("timestamp")),
                    )
                )
        total = s.execute(select(func.count()).select_from(ActivityRow).where(ActivityRow.kind == key)).scalar_one()
        if total > FEED_KEEP_CAP:
            # Fetch victim ids first: MariaDB rejects LIMIT inside IN-subqueries.
            oldest_ids = list(
                s.execute(
                    select(ActivityRow.id)
                    .where(ActivityRow.kind == key)
                    .order_by(ActivityRow.created_at, ActivityRow.id)
                    .limit(total - FEED_KEEP_CAP)
                ).scalars()
            )
            s.execute(delete(ActivityRow).where(ActivityRow.id.in_(oldest_ids)))
    return None


@v1_bp.route("/v1/overlay/<key>", methods=["PUT"])
@write_guard
def v1_overlay_put(key: str) -> Response:
    """Write-through target for one localStorage overlay key."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    value = request.get_json(silent=True)
    if value is None:
        return _bad("body must be JSON")
    if key == "favorites":
        err = _put_favorites(uid, value)
    elif key == "lists":
        err = _put_lists(uid, value)
    elif key == "crawlerUrls":
        err = _put_crawler_urls(uid, value)
    elif key in OVERLAY_KINDS or key == "toolNew":
        err = _put_tool_map(uid, value, key=key, user=user)
    elif key in FEED_KEYS:
        err = _put_feed(uid, value, key=key)
    else:
        resp = jsonify({"error": "unknown overlay key"})
        resp.status_code = HTTP_NOT_FOUND
        return resp
    return err if err is not None else jsonify({"ok": True})


@v1_bp.route("/v1/crawler/runs/")
@login_required
def v1_crawler_runs() -> Response:
    """Recent local crawler job outcomes for signed-in contributors."""
    with db.session_scope() as s:
        runs = [
            {
                "id": row.id,
                "startedAt": _iso(row.started_at),
                "endedAt": _iso(row.ended_at),
                "urlsCount": row.urls_count,
                "added": row.added,
                "updated": row.updated,
                "ok": row.ok,
                "errors": row.errors if isinstance(row.errors, list) else [],
                "source": row.source or SOURCE_LOCAL,
                "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
            }
            for row in s.execute(
                select(CrawlerRun).order_by(CrawlerRun.started_at.desc(), CrawlerRun.id.desc()).limit(20)
            ).scalars()
        ]
    return jsonify({"count": len(runs), "results": runs})


@v1_bp.route("/v1/user/export/")
@login_required
def v1_user_export() -> Response:
    """Export the caller's Evolved-owned data; official Toolhub data is not copied."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        user = s.get(User, uid)
        username = user.username if user else ""
    return jsonify({"exportedAt": _iso(utcnow()), "user": {"username": username}, "overlay": _assemble_overlay(uid)})


@v1_bp.route("/v1/user/evolved-data/", methods=["DELETE"])
@write_guard
def v1_user_delete_evolved_data() -> Response:
    """Delete the caller's local Evolved data without touching official Toolhub."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    deleted: dict[str, int] = {}
    with db.session_scope() as s:
        for key, model in {
            "favorites": Favorite,
            "lists": ToolList,
            "toolNew": ToolRecord,
            "toolOverlays": ToolOverlay,
            "activity": ActivityRow,
            "crawlerUrls": CrawlerUrl,
            "toolEvents": ToolEvent,
            "thanks": ToolThanks,
            "media": ToolMedia,
        }.items():
            count = s.execute(select(func.count()).select_from(model).where(model.user_id == uid)).scalar_one()
            deleted[key] = int(count)
            s.execute(delete(model).where(model.user_id == uid))
        health_count = s.execute(
            select(func.count()).select_from(ToolHealthTarget).where(ToolHealthTarget.created_by_user_id == uid)
        ).scalar_one()
        deleted["healthTargets"] = int(health_count)
        s.execute(delete(ToolHealthTarget).where(ToolHealthTarget.created_by_user_id == uid))
    return jsonify({"ok": True, "deleted": deleted})


@v1_bp.route("/v1/tools/<name>/signals/")
def v1_tool_signals(name: str) -> Response:
    """Real Evolved-owned signal summary for one tool."""
    clean_name = _clean_name(name)
    if clean_name is None:
        return _bad("tool name is required")
    since = (utcnow() - timedelta(days=30)).date().isoformat()
    uid = current_user_id()
    with db.session_scope() as s:
        thanks_count = s.execute(
            select(func.count())
            .select_from(ToolThanks)
            .where(ToolThanks.tool_name == clean_name, ToolThanks.active.is_(True))
        ).scalar_one()
        user_thanked = (
            bool(
                s.execute(
                    select(ToolThanks.id).where(
                        ToolThanks.tool_name == clean_name,
                        ToolThanks.user_id == uid,
                        ToolThanks.active.is_(True),
                    )
                ).first()
            )
            if uid is not None
            else False
        )
        events_30d = s.execute(
            select(func.count()).select_from(ToolEvent).where(ToolEvent.tool_name == clean_name, ToolEvent.day >= since)
        ).scalar_one()
        health = s.execute(
            select(ToolHealthTarget)
            .where(ToolHealthTarget.tool_name == clean_name, ToolHealthTarget.enabled.is_(True))
            .where(ToolHealthTarget.deleted_at.is_(None))
            .order_by(ToolHealthTarget.last_checked_at.desc(), ToolHealthTarget.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    return jsonify(
        {
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "thanks": {"count": int(thanks_count), "userThanked": user_thanked},
            "usage30d": {"count": int(events_30d), "label": "30-day Evolved usage"},
            "health": {
                "status": health.last_status if health and health.last_status else "unknown",
                "checkedAt": _iso(health.last_checked_at) if health else "",
                "targetUrl": health.target_url if health else "",
                "lastError": health.last_error if health else "",
            },
        }
    )


@v1_bp.route("/v1/tools/<name>/events/", methods=["POST"])
@write_guard
def v1_tool_event(name: str) -> Response:
    """Record one privacy-limited Evolved interaction event."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    _require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    clean_name = _clean_name(name)
    value = request.get_json(silent=True) or {}
    event_type = value.get("eventType") if isinstance(value, dict) else None
    if clean_name is None or event_type not in EVENT_TYPES:
        return _bad("eventType must be one of view, launch, save, list_add")
    now = utcnow()
    with db.session_scope() as s:
        s.add(
            ToolEvent(
                tool_name=clean_name,
                event_type=event_type,
                user_id=uid,
                created_by_user_id=uid,
                day=now.date().isoformat(),
                event_meta=value.get("meta") if isinstance(value.get("meta"), dict) else None,
                created_at=now,
            )
        )
    return jsonify({"ok": True})


@v1_bp.route("/v1/tools/<name>/thanks/", methods=["POST", "DELETE"])
@write_guard
def v1_tool_thanks(name: str) -> Response:
    """Add or remove the caller's Evolved thanks for one tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    action = authz.ACTION_PRIVATE_WRITE if request.method == "POST" else authz.ACTION_PRIVATE_DELETE
    _require_policy_or_abort(action, authz.Resource(owner_user_id=uid))
    clean_name = _clean_name(name)
    if clean_name is None:
        return _bad("tool name is required")
    with db.session_scope() as s:
        row = s.execute(
            select(ToolThanks).where(ToolThanks.tool_name == clean_name, ToolThanks.user_id == uid)
        ).scalar_one_or_none()
        if row is None:
            row = ToolThanks(
                tool_name=clean_name,
                user_id=uid,
                created_by_user_id=uid,
                active=request.method == "POST",
            )
            s.add(row)
        else:
            if row.created_by_user_id is None:
                row.created_by_user_id = uid
            row.active = request.method == "POST"
            row.updated_at = utcnow()
    return jsonify({"ok": True})


@v1_bp.route("/v1/tools/<name>/health-target/", methods=["PUT"])
@write_guard
def v1_tool_health_target(name: str) -> Response:
    """Store the caller's Evolved health target URL for a tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    _require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    clean_name = _clean_name(name)
    value = request.get_json(silent=True) or {}
    target_url = value.get("url") if isinstance(value, dict) else None
    if clean_name is None or not _is_http_url(target_url):
        return _bad("health target needs an http(s) url")
    with db.session_scope() as s:
        row = s.execute(
            select(ToolHealthTarget).where(
                ToolHealthTarget.tool_name == clean_name,
                ToolHealthTarget.created_by_user_id == uid,
            )
        ).scalar_one_or_none()
        if row is None:
            s.add(ToolHealthTarget(tool_name=clean_name, created_by_user_id=uid, target_url=target_url[:MAX_URL]))
        else:
            row.target_url = target_url[:MAX_URL]
            row.enabled = True
            row.deleted_at = None
            row.last_error = None
    return jsonify({"ok": True})


def _tool_media_get(clean_name: str) -> Response:
    """Return approved public media for a tool."""
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolMedia)
                .where(
                    ToolMedia.tool_name == clean_name,
                    ToolMedia.deleted_at.is_(None),
                    ToolMedia.review_status == "approved",
                )
                .order_by(ToolMedia.created_at.desc(), ToolMedia.id.desc())
                .limit(12)
            ).scalars()
        )
    return jsonify({"count": len(rows), "results": [_media_payload(row) for row in rows]})


def _tool_media_post(clean_name: str) -> Response:
    """Submit URL-based media metadata for Evolved moderation."""
    guard = write_guard(lambda: None)()
    if guard is not None:
        return guard
    user = _require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    uid = user.id
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return _bad("media body must be a JSON object")
    media_url = value.get("url")
    license_id = str(value.get("license") or "").strip()
    source = str(value.get("source") or "").strip()
    if not (_is_http_url(media_url) and license_id and source):
        return _bad("media needs url, license, and source")
    with db.session_scope() as s:
        row = ToolMedia(
            tool_name=clean_name,
            user_id=uid,
            created_by_user_id=uid,
            url=str(media_url)[:MAX_URL],
            title=str(value.get("title") or "")[:MAX_NAME],
            license=license_id[:MAX_NAME],
            source=source[:MAX_URL],
            review_status="pending",
        )
        s.add(row)
        s.flush()
        payload = _media_payload(row)
    return jsonify({"ok": True, "media": payload})


@v1_bp.route("/v1/tools/<name>/media/", methods=["GET", "POST"])
def v1_tool_media(name: str) -> Response:
    """List approved media, or submit URL-based media metadata for moderation."""
    clean_name = _clean_name(name)
    if clean_name is None:
        return _bad("tool name is required")
    if request.method == "GET":
        return _tool_media_get(clean_name)
    return _tool_media_post(clean_name)


@v1_bp.route("/v1/media/<int:media_id>/", methods=["DELETE"])
@write_guard
def v1_tool_media_delete(media_id: int) -> Response:
    """Soft-delete a media row owned by the caller."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        row = s.get(ToolMedia, media_id)
        if row is None or not authz.can(user, authz.ACTION_PRIVATE_DELETE, row):
            resp = jsonify({"error": "media not found"})
            resp.status_code = HTTP_NOT_FOUND
            return resp
        row.deleted_at = utcnow()
    return jsonify({"ok": True})


@v1_bp.route("/v1/search/tools/")
def v1_search() -> Response:
    """Search locally-registered tools (public).

    Federated with live search client-side; upstream results always come
    straight from the Toolhub API.
    """
    q = request.args.get("q", "").strip().lower()
    with db.session_scope() as s:
        merged = {
            row.tool_name: _tool_record_payload(row)
            for row in s.execute(
                select(ToolRecord).where(ToolRecord.deleted_at.is_(None)).order_by(ToolRecord.modified_at)
            ).scalars()
            if _local_tool_is_public(row)
        }

    def matches(name: str, rec: dict) -> bool:
        keywords = rec.get("keywords")
        return (
            not q
            or any(q in str(rec.get(f, "")).lower() for f in ("title", "description"))
            or q in name.lower()
            or any(q in str(k).lower() for k in (keywords if isinstance(keywords, list) else []))
        )

    results = [{"name": name, **rec} for name, rec in merged.items() if matches(name, rec)]
    return jsonify({"count": len(results), "results": results})


@v1_bp.route("/toolinfo.json")
def toolinfo_feed() -> Response:
    """Serve the public toolinfo feed of locally-registered tools.

    The official Toolhub crawler can ingest this feed (docs/PRODUCTION.md
    §1.3 — we feed the ecosystem instead of forking it).
    """
    with db.session_scope() as s:
        merged = {
            row.tool_name: _tool_record_payload(row)
            for row in s.execute(
                select(ToolRecord).where(ToolRecord.deleted_at.is_(None)).order_by(ToolRecord.modified_at)
            ).scalars()
            if _local_tool_is_public(row)
        }

    def entry(name: str, rec: dict) -> dict:
        # Defensive reads: writes are validated (_clean_tool_record), but a bad
        # legacy row must degrade to an empty field, never break the feed.
        keywords = rec.get("keywords")
        wikis = rec.get("forWikis")
        return {
            "name": f"toolhub-evolved-{name}",
            "title": str(rec.get("title") or name),
            "description": str(rec.get("description") or ""),
            "url": str(rec.get("url") or ""),
            "keywords": ",".join(str(k) for k in keywords) if isinstance(keywords, list) else "",
            "repository": rec.get("repository") or None,
            "license": rec.get("license") or None,
            "tool_type": rec.get("toolType") or None,
            "for_wikis": wikis if isinstance(wikis, list) else [],
            "$schema": "/toolinfo/1.2.2",
        }

    feed = [entry(name, rec) for name, rec in merged.items() if str(rec.get("url") or "").startswith("https://")]
    return jsonify(feed)
