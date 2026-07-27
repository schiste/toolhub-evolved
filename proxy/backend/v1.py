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
from uuid import uuid4

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
    REVIEW_REJECTED,
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
MODERATION_MODELS = {
    "tool-records": ToolRecord,
    "health-targets": ToolHealthTarget,
    "media": ToolMedia,
    "thanks": ToolThanks,
}
PUBLIC_REVIEW_STATUSES = {REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED}
MODERATION_KINDS = set(MODERATION_MODELS)
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
TOOL_FALLBACK_KINDS = {"new", "edit", "annotations"}
TOOL_OVERLAY_KIND_BY_FALLBACK = {"edit": "edits", "annotations": "annos"}
OFFICIAL_STATUS_DISCARDED = "discarded"


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
        "reviewStatus": clean_review_status(row.review_status, REVIEW_PENDING),
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": _sync_label(row.sync_status or SYNC_EVOLVED_REAL),
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
    if getattr(row, "last_toolhub_response", None):
        out["toolhubResponse"] = row.last_toolhub_response
    if getattr(row, "validation_errors", None):
        out["validationErrors"] = row.validation_errors
    return out


def _list_payload(row: ToolList) -> dict:
    return _with_common_meta(
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


def _crawler_url_payload(row: CrawlerUrl) -> dict:
    return _with_common_meta(
        {
            "url": row.url,
            "added": _iso(row.added_at),
            "localId": row.id,
            "enabled": row.enabled,
            "lastCheckedAt": _iso(row.last_checked_at),
            "lastStatus": row.last_status or "",
        },
        row,
        include_official_id=True,
    )


def _local_tool_is_public(row: ToolRecord) -> bool:
    """Public Evolved records are searchable/feedable; private drafts are not."""
    record = row.record if isinstance(row.record, dict) else {}
    is_public = row.visibility == VISIBILITY_PUBLIC or record.get("origin") == "crawler"
    return is_public and clean_review_status(getattr(row, "review_status", None), REVIEW_PENDING) == REVIEW_APPROVED


def _tool_record_payload(row: ToolRecord) -> dict:
    record = row.record if isinstance(row.record, dict) else {}
    out = _with_common_meta(record, row)
    out["visibility"] = row.visibility or VISIBILITY_PRIVATE
    out["reviewStatus"] = clean_review_status(getattr(row, "review_status", None), REVIEW_PENDING)
    if row.official_name:
        out["officialName"] = row.official_name
    if row.last_toolhub_response:
        out["toolhubResponse"] = row.last_toolhub_response
    if row.validation_errors:
        out["validationErrors"] = row.validation_errors
    return out


def _health_target_payload(row: ToolHealthTarget) -> dict:
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "targetUrl": row.target_url,
        "enabled": row.enabled,
        "reviewStatus": clean_review_status(row.review_status, REVIEW_PENDING),
        "lastCheckedAt": _iso(row.last_checked_at),
        "lastStatus": row.last_status or "",
        "lastError": row.last_error or "",
        "source": SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": _sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "createdAt": _iso(row.created_at),
    }


def _thanks_payload(row: ToolThanks) -> dict:
    return {
        "id": row.id,
        "toolName": row.tool_name,
        "active": row.active,
        "reviewStatus": clean_review_status(row.review_status, REVIEW_APPROVED),
        "source": SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": _sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def _moderation_item(kind: str, row: object) -> dict:
    payload_builders = {
        "tool-records": _tool_record_payload,
        "health-targets": _health_target_payload,
        "media": _media_payload,
        "thanks": _thanks_payload,
    }
    return {"kind": kind, "id": row.id, "data": payload_builders[kind](row)}


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


def _json_object_body() -> tuple[dict | None, Response | None]:
    """Return the request JSON object or a normalized 400 response."""
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None, _bad("body must be a JSON object")
    return value, None


def _string_list(value: Any) -> list[str]:  # noqa: ANN401
    """Normalize official/list-like array fields into bounded strings."""
    if not isinstance(value, list):
        return []
    return [str(item)[:MAX_NAME] for item in value[:50] if isinstance(item, str | int | float)]


def _message_from_payload(payload: object, default: str) -> str:
    """Extract the clearest user-facing message from a Toolhub error payload."""
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:MAX_DESCRIPTION]
    return default


def _validation_errors(payload: object) -> list:
    """Turn common Toolhub validation payload shapes into a UI-consumable list."""
    if isinstance(payload, list):
        return [item if isinstance(item, dict) else {"message": str(item)} for item in payload]
    if not isinstance(payload, dict):
        return []
    direct = payload.get("validationErrors") or payload.get("validation_errors") or payload.get("errors")
    if isinstance(direct, list):
        return [item if isinstance(item, dict) else {"message": str(item)} for item in direct]
    skipped = {"message", "detail", "error", "non_field_errors"}
    field_lists = [
        {"field": key, "messages": [str(message) for message in value]}
        for key, value in payload.items()
        if key not in skipped and isinstance(value, list)
    ]
    field_strings = [
        {"field": key, "messages": [value.strip()]}
        for key, value in payload.items()
        if key not in skipped and isinstance(value, str) and value.strip()
    ]
    return field_lists + field_strings


def _failure_payload(status: int, payload: object, default_message: str) -> dict:
    details = payload if isinstance(payload, dict) else {"message": str(payload)}
    return {
        "ok": False,
        "status": status,
        "details": details,
        "lastError": _message_from_payload(details, default_message),
        "validationErrors": _validation_errors(details),
    }


def _attempt_official_write(user: User, method: str, path: str, payload: object | None) -> tuple[dict, Response | None]:
    """Call Toolhub with the user's grant; auth failures remain non-fallback."""
    try:
        body, status = toolhub.api_request(user.id, method, path, json=payload)
    except toolhub.ToolhubAuthError as exc:
        resp = jsonify({"error": str(exc), "reauth": True})
        resp.status_code = HTTP_UNAUTHORIZED
        return {}, resp
    except toolhub.ToolhubAPIError as exc:
        return _failure_payload(exc.status_code, exc.payload, "official Toolhub rejected the write"), None
    except toolhub.requests.RequestException:
        return (
            _failure_payload(502, {"message": "official Toolhub is unavailable"}, "official Toolhub is unavailable"),
            None,
        )
    return {
        "ok": True,
        "status": status,
        "toolhub": body if status != HTTP_NO_CONTENT else {"ok": True},
        "lastSyncedAt": _iso(utcnow()),
    }, None


def _official_success_response(attempt: dict, local: dict | None = None) -> Response:
    payload = {
        "ok": True,
        "result": "official",
        "syncStatus": SYNC_OFFICIAL,
        "lastSyncedAt": attempt["lastSyncedAt"],
        "toolhub": attempt["toolhub"],
    }
    if local is not None:
        payload["local"] = local
    resp = jsonify(payload)
    resp.status_code = 200 if attempt["status"] == HTTP_NO_CONTENT else int(attempt["status"])
    return resp


def _official_failure_response(failure: dict) -> Response:
    resp = jsonify(
        {
            "error": "official Toolhub rejected the write",
            "status": failure["status"],
            "details": failure["details"],
            "lastError": failure["lastError"],
            "validationErrors": failure["validationErrors"],
        }
    )
    resp.status_code = int(failure["status"])
    return resp


def _local_fallback_response(failure: dict, local: dict) -> Response:
    resp = jsonify(
        {
            "ok": True,
            "result": SYNC_LOCAL_FALLBACK,
            "syncStatus": SYNC_LOCAL_FALLBACK,
            "lastError": failure["lastError"],
            "validationErrors": failure["validationErrors"],
            "toolhubResponse": failure["details"],
            "local": local,
        }
    )
    resp.status_code = 202
    return resp


def _emit_structured_activity(  # noqa: PLR0913 - activity rows need explicit queryable fields
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    *,
    action: str,
    object_type: str,
    object_key: str,
    official_status: str,
    payload: dict,
    title: str | None = None,
) -> None:
    """Add Evolved activity in both legacy feed shapes plus structured columns."""
    now = utcnow()
    client_id = f"w{uuid4().hex}"
    label = title or object_key
    common_row = {
        "id": client_id,
        "timestamp": _iso(now),
        "user": {"username": user.username},
        "_evolved": True,
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
        "officialStatus": official_status,
    }
    rows = {
        "revisions": {
            **common_row,
            "comment": f"Evolved: {action}",
            "content_type": object_type,
            "content_id": object_key,
            "content_title": label,
        },
        "auditlogs": {
            **common_row,
            "action": action,
            "target": {"type": object_type, "id": object_key, "label": label},
        },
    }
    for kind, row in rows.items():
        s.add(
            ActivityRow(
                kind=kind,
                client_id=client_id,
                user_id=user.id,
                created_by_user_id=user.id,
                row=row,
                created_at=now,
                object_type=object_type,
                object_key=object_key,
                action=action,
                official_status=official_status,
                payload=payload,
                source=SOURCE_LOCAL,
                sync_status=SYNC_EVOLVED_REAL,
                last_synced_at=now if official_status == SYNC_OFFICIAL else None,
                last_error=clean_error(payload.get("lastError")),
            )
        )


def _compact_tool_payload(payload: dict, route_name: str | None = None) -> tuple[str | None, dict | None]:
    """Convert official Toolhub tool payloads into Evolved's compact tool shape."""
    name = _clean_name(route_name or str(payload.get("name") or ""))
    compact = {
        "title": payload.get("title"),
        "description": payload.get("description"),
        "url": payload.get("url"),
        "repository": payload.get("repository"),
        "license": payload.get("license"),
        "toolType": _payload_value(payload, "toolType", "tool_type"),
        "keywords": _string_list(payload.get("keywords")),
        "forWikis": _string_list(_payload_value(payload, "forWikis", "for_wikis")),
        "uiLanguages": _string_list(_payload_value(payload, "uiLanguages", "available_ui_languages")),
        "deprecated": bool(payload.get("deprecated")),
        "experimental": bool(payload.get("experimental")),
    }
    clean = _clean_tool_record(compact)
    return name, clean if name and clean is not None else None


def _official_tool_payload(name: str, fields: dict, *, include_name: bool) -> dict:
    payload = {
        "title": fields["title"],
        "description": fields["description"],
        "url": fields["url"],
        "repository": fields.get("repository"),
        "license": fields.get("license"),
        "tool_type": fields.get("toolType"),
        "keywords": fields.get("keywords", []),
        "for_wikis": fields.get("forWikis", []),
        "available_ui_languages": fields.get("uiLanguages", []),
        "deprecated": bool(fields.get("deprecated")),
        "experimental": bool(fields.get("experimental")),
        "comment": "Published from Toolhub Evolved",
    }
    if include_name:
        payload["name"] = name
    if not payload["repository"]:
        del payload["repository"]
    if not payload["license"]:
        del payload["license"]
    if not payload["tool_type"]:
        del payload["tool_type"]
    return payload


def _compact_annotation_payload(payload: dict) -> dict:
    tool_type = _payload_value(payload, "toolType", "tool_type")
    icon = payload.get("icon")
    return {
        "audiences": _string_list(payload.get("audiences")),
        "tasks": _string_list(payload.get("tasks")),
        "toolType": str(tool_type)[:MAX_NAME] if isinstance(tool_type, str) and tool_type else None,
        "icon": str(icon)[:MAX_URL] if isinstance(icon, str) and icon else None,
    }


def _official_annotation_payload(fields: dict) -> dict:
    payload = {
        "audiences": fields.get("audiences", []),
        "tasks": fields.get("tasks", []),
        "tool_type": fields.get("toolType"),
        "icon": fields.get("icon"),
        "comment": "Annotated from Toolhub Evolved",
    }
    if not payload["tool_type"]:
        del payload["tool_type"]
    if not payload["icon"]:
        del payload["icon"]
    return payload


def _list_client_id(uid: int, payload: dict, route_id: str | None) -> str:
    raw = payload.get("clientId") or payload.get("client_id") or payload.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:64]
    if route_id is not None:
        return f"demo-official-{route_id}-{uid}"[:64]
    return f"demo-{uuid4().hex[:24]}"


def _clean_list_write_payload(uid: int, payload: dict, route_id: str | None = None) -> dict | None:
    title = payload.get("title")
    tools = payload.get("tools")
    if not isinstance(title, str) or not title.strip() or not isinstance(tools, list):
        return None
    return {
        "client_id": _list_client_id(uid, payload, route_id),
        "title": title.strip()[:MAX_NAME],
        "description": str(payload.get("description") or "")[:MAX_DESCRIPTION],
        "tools": [str(tool)[:MAX_NAME] for tool in tools[:MAX_ITEMS] if isinstance(tool, str | int | float)],
    }


def _official_list_payload(fields: dict) -> dict:
    return {
        "title": fields["title"],
        "description": fields["description"] or None,
        "published": True,
        "tools": fields["tools"],
        "comment": "Published from Toolhub Evolved",
    }


def _official_id(body: object, fallback: int | None = None) -> int | None:
    if isinstance(body, dict):
        return clean_int(body.get("id")) or fallback
    return fallback


def _store_tool_record_fallback(s: Any, user: User, name: str, fields: dict, failure: dict) -> dict:  # noqa: ANN401
    row = s.execute(
        select(ToolRecord).where(ToolRecord.tool_name == name, ToolRecord.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        row = ToolRecord(tool_name=name, user_id=user.id, created_by_user_id=user.id)
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.record = fields
    row.modified_at = utcnow()
    row.visibility = VISIBILITY_PRIVATE
    row.source = SOURCE_LOCAL
    row.sync_status = SYNC_LOCAL_FALLBACK
    row.review_status = clean_review_status(row.review_status, REVIEW_PENDING)
    row.last_synced_at = None
    row.last_error = clean_error(failure["lastError"])
    row.last_toolhub_response = failure["details"]
    row.validation_errors = failure["validationErrors"]
    row.deleted_at = None
    return _tool_record_payload(row)


def _store_tool_overlay_fallback(  # noqa: PLR0913 - fallback persistence keeps route semantics explicit
    s: Any,  # noqa: ANN401
    user: User,
    name: str,
    kind: str,
    patch: dict,
    failure: dict,
) -> dict:
    row = s.execute(
        select(ToolOverlay).where(
            ToolOverlay.kind == kind,
            ToolOverlay.tool_name == name,
            ToolOverlay.user_id == user.id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ToolOverlay(kind=kind, tool_name=name, user_id=user.id, created_by_user_id=user.id)
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.patch = _data_patch(patch)
    row.modified_at = utcnow()
    row.source = SOURCE_LOCAL
    row.sync_status = SYNC_LOCAL_FALLBACK
    row.last_synced_at = None
    row.last_error = clean_error(failure["lastError"])
    row.last_toolhub_response = failure["details"]
    row.validation_errors = failure["validationErrors"]
    row.review_status = clean_review_status(row.review_status, REVIEW_OPEN)
    row.deleted_at = None
    return _with_common_meta(row.patch, row)


def _store_list_row(  # noqa: PLR0913 - list lifecycle writes official and fallback metadata together
    s: Any,  # noqa: ANN401
    user: User,
    fields: dict,
    *,
    sync_status: str,
    official_id: int | None = None,
    failure: dict | None = None,
    toolhub_body: object | None = None,
) -> ToolList:
    row = s.get(ToolList, fields["client_id"])
    if row is None:
        row = ToolList(
            client_id=fields["client_id"],
            user_id=user.id,
            created_by_user_id=user.id,
            title=fields["title"],
        )
        s.add(row)
    row.user_id = user.id
    row.created_by_user_id = row.created_by_user_id or user.id
    row.title = fields["title"]
    row.description = fields["description"]
    row.tools = fields["tools"]
    row.modified_at = utcnow()
    row.official_list_id = official_id
    row.source = SOURCE_OFFICIAL if sync_status == SYNC_OFFICIAL else SOURCE_LOCAL
    row.sync_status = sync_status
    row.last_synced_at = utcnow() if sync_status == SYNC_OFFICIAL else None
    row.last_error = clean_error(failure["lastError"]) if failure else None
    row.last_toolhub_response = (
        failure["details"] if failure else toolhub_body if isinstance(toolhub_body, dict) else None
    )
    row.validation_errors = failure["validationErrors"] if failure else None
    row.deleted_at = None
    return row


def _store_crawler_url_row(  # noqa: PLR0913 - crawler URL lifecycle writes official and fallback metadata
    s: Any,  # noqa: ANN401
    user: User,
    url: str,
    *,
    sync_status: str,
    official_id: int | None = None,
    failure: dict | None = None,
    toolhub_body: object | None = None,
) -> CrawlerUrl:
    row = s.execute(select(CrawlerUrl).where(CrawlerUrl.user_id == user.id, CrawlerUrl.url == url)).scalar_one_or_none()
    if row is None:
        row = CrawlerUrl(user_id=user.id, created_by_user_id=user.id, url=url[:MAX_URL])
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.url = url[:MAX_URL]
    row.official_crawler_url_id = official_id
    row.source = SOURCE_OFFICIAL if sync_status == SYNC_OFFICIAL else SOURCE_LOCAL
    row.sync_status = sync_status
    row.enabled = True
    row.last_synced_at = utcnow() if sync_status == SYNC_OFFICIAL else None
    row.last_error = clean_error(failure["lastError"]) if failure else None
    row.last_toolhub_response = (
        failure["details"] if failure else toolhub_body if isinstance(toolhub_body, dict) else None
    )
    row.validation_errors = failure["validationErrors"] if failure else None
    return row


def _upsert_favorite(
    s: Any,  # noqa: ANN401
    user: User,
    name: str,
    *,
    sync_status: str,
    failure: dict | None = None,
) -> Favorite:
    row = s.execute(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name)
    ).scalar_one_or_none()
    if row is None:
        position = int(
            s.execute(select(func.count()).select_from(Favorite).where(Favorite.user_id == user.id)).scalar_one()
        )
        row = Favorite(user_id=user.id, created_by_user_id=user.id, tool_name=name, position=position)
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.source = SOURCE_OFFICIAL if sync_status == SYNC_OFFICIAL else SOURCE_LOCAL
    row.sync_status = sync_status
    row.last_synced_at = utcnow() if sync_status == SYNC_OFFICIAL else None
    row.last_error = clean_error(failure["lastError"]) if failure else None
    return row


def _local_write_allowed(user: User) -> bool:
    return authz.can(user, authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=user.id))


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


def _write_tool_core(route_name: str | None = None) -> Response:
    value, err = _json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    name, fields = _compact_tool_payload(value, route_name)
    if name is None or fields is None:
        return _bad("tool write needs name, title, description and an https url")
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        local_new = (
            route_name is not None
            and s.execute(
                select(ToolRecord.id).where(
                    ToolRecord.tool_name == name,
                    ToolRecord.user_id == user.id,
                    ToolRecord.deleted_at.is_(None),
                )
            ).first()
            is not None
        )
    create_like = route_name is None or local_new
    method = "POST" if create_like else "PUT"
    path = "/api/tools/" if create_like else _upstream_path(f"tools/{name}/")
    attempt, denied = _attempt_official_write(
        user,
        method,
        path,
        _official_tool_payload(name, fields, include_name=create_like),
    )
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            s.execute(delete(ToolRecord).where(ToolRecord.tool_name == name, ToolRecord.user_id == user.id))
            s.execute(
                delete(ToolOverlay).where(
                    ToolOverlay.tool_name == name,
                    ToolOverlay.user_id == user.id,
                    ToolOverlay.kind == "edits",
                )
            )
            _emit_structured_activity(
                s,
                user,
                action="created" if create_like else "edited",
                object_type="tool",
                object_key=name,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
                title=fields["title"],
            )
        return _official_success_response(attempt)
    if not _local_write_allowed(user):
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        if create_like:
            local = _store_tool_record_fallback(s, user, name, fields, attempt)
            action = "created"
        else:
            local = _store_tool_overlay_fallback(s, user, name, "edits", fields, attempt)
            action = "edited"
        _emit_structured_activity(
            s,
            user,
            action=action,
            object_type="tool",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
            title=fields["title"],
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/tools/", methods=["POST"])
@write_guard
def write_tool_create() -> Response:
    """Official-first lifecycle for creating a Toolhub tool."""
    return _write_tool_core()


@v1_bp.route("/v1/write/tools/<name>/", methods=["PUT", "DELETE"])
@write_guard
def write_tool_update(name: str) -> Response:
    """Official-first lifecycle for updating or deleting a Toolhub tool."""
    clean_name = _clean_name(name)
    if clean_name is None:
        return _bad("tool name is required")
    if request.method == "PUT":
        return _write_tool_core(clean_name)
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", _upstream_path(f"tools/{clean_name}/"), None)
    if denied is not None:
        return denied
    if not attempt["ok"]:
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        s.execute(delete(ToolRecord).where(ToolRecord.tool_name == clean_name, ToolRecord.user_id == user.id))
        s.execute(delete(ToolOverlay).where(ToolOverlay.tool_name == clean_name, ToolOverlay.user_id == user.id))
        _emit_structured_activity(
            s,
            user,
            action="deleted",
            object_type="tool",
            object_key=clean_name,
            official_status=SYNC_OFFICIAL,
            payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
        )
    return _official_success_response(attempt)


@v1_bp.route("/v1/write/tools/<name>/annotations/", methods=["PUT"])
@write_guard
def write_annotations_update(name: str) -> Response:
    """Official-first lifecycle for tool annotations."""
    clean_name = _clean_name(name)
    value, err = _json_object_body()
    if clean_name is None:
        return _bad("tool name is required")
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    fields = _compact_annotation_payload(value)
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(
        user,
        "PUT",
        _upstream_path(f"tools/{clean_name}/annotations/"),
        _official_annotation_payload(fields),
    )
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            s.execute(
                delete(ToolOverlay).where(
                    ToolOverlay.kind == "annos",
                    ToolOverlay.tool_name == clean_name,
                    ToolOverlay.user_id == user.id,
                )
            )
            _emit_structured_activity(
                s,
                user,
                action="annotated",
                object_type="tool",
                object_key=clean_name,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
            )
        return _official_success_response(attempt)
    if not _local_write_allowed(user):
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        local = _store_tool_overlay_fallback(s, user, clean_name, "annos", fields, attempt)
        _emit_structured_activity(
            s,
            user,
            action="annotated",
            object_type="tool",
            object_key=clean_name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


def _write_list_core(route_id: str | None = None) -> Response:
    value, err = _json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    official_route_id = clean_int(route_id)
    fields = _clean_list_write_payload(user.id, value, route_id)
    if fields is None:
        return _bad("list write needs title and tools")
    method = "POST" if route_id is None else "PUT"
    path = "/api/lists/" if route_id is None else _upstream_path(f"lists/{official_route_id}/")
    attempt, denied = _attempt_official_write(user, method, path, _official_list_payload(fields))
    if denied is not None:
        return denied
    if attempt["ok"]:
        official_id = _official_id(attempt["toolhub"], official_route_id)
        with db.session_scope() as s:
            row = _store_list_row(
                s,
                user,
                fields,
                sync_status=SYNC_OFFICIAL,
                official_id=official_id,
                toolhub_body=attempt["toolhub"],
            )
            local = _list_payload(row)
            _emit_structured_activity(
                s,
                user,
                action="list-created" if route_id is None else "list-edited",
                object_type="list",
                object_key=row.client_id,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "local": local, "syncStatus": SYNC_OFFICIAL},
                title=row.title,
            )
        return _official_success_response(attempt, local)
    if not _local_write_allowed(user):
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        row = _store_list_row(
            s,
            user,
            fields,
            sync_status=SYNC_LOCAL_FALLBACK,
            official_id=official_route_id,
            failure=attempt,
        )
        local = _list_payload(row)
        _emit_structured_activity(
            s,
            user,
            action="list-created" if route_id is None else "list-edited",
            object_type="list",
            object_key=row.client_id,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
            title=row.title,
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/lists/", methods=["POST"])
@write_guard
def write_list_create() -> Response:
    """Official-first lifecycle for creating a list."""
    return _write_list_core()


@v1_bp.route("/v1/write/lists/<list_id>/", methods=["PUT", "DELETE"])
@write_guard
def write_list_update(list_id: str) -> Response:
    """Official-first lifecycle for updating or deleting a list."""
    official_id = clean_int(list_id)
    if official_id is None:
        return _bad("official list id must be numeric")
    if request.method == "PUT":
        return _write_list_core(list_id)
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", _upstream_path(f"lists/{official_id}/"), None)
    if denied is not None:
        return denied
    if not attempt["ok"]:
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        rows = s.execute(
            select(ToolList).where(
                ToolList.user_id == user.id,
                or_(ToolList.client_id == str(list_id), ToolList.official_list_id == official_id),
            )
        ).scalars()
        now = utcnow()
        for row in rows:
            row.deleted_at = now
            row.sync_status = SYNC_OFFICIAL
            row.last_synced_at = now
            row.last_error = None
        _emit_structured_activity(
            s,
            user,
            action="list-deleted",
            object_type="list",
            object_key=str(official_id),
            official_status=SYNC_OFFICIAL,
            payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
        )
    return _official_success_response(attempt)


@v1_bp.route("/v1/write/user/favorites/", methods=["POST"])
@write_guard
def write_favorite_add() -> Response:
    """Official-first lifecycle for adding a favorite."""
    value, err = _json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    name = _clean_name(str(value.get("name") or ""))
    if name is None:
        return _bad("favorite needs a tool name")
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "POST", "/api/user/favorites/", {"name": name})
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            _upsert_favorite(s, user, name, sync_status=SYNC_OFFICIAL)
            _emit_structured_activity(
                s,
                user,
                action="favorited",
                object_type="favorite",
                object_key=name,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
            )
        return _official_success_response(attempt, {"name": name, "syncStatus": SYNC_OFFICIAL})
    if not _local_write_allowed(user):
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        _upsert_favorite(s, user, name, sync_status=SYNC_LOCAL_FALLBACK, failure=attempt)
        local = {
            "name": name,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_LOCAL_FALLBACK,
            "lastError": attempt["lastError"],
            "toolhubResponse": attempt["details"],
            "validationErrors": attempt["validationErrors"],
        }
        _emit_structured_activity(
            s,
            user,
            action="favorited",
            object_type="favorite",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/user/favorites/<tool_name>/", methods=["DELETE"])
@write_guard
def write_favorite_delete(tool_name: str) -> Response:
    """Official-first lifecycle for removing a favorite."""
    name = _clean_name(tool_name)
    if name is None:
        return _bad("favorite needs a tool name")
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", _upstream_path(f"user/favorites/{name}/"), None)
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            s.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name))
            _emit_structured_activity(
                s,
                user,
                action="favorite-removed",
                object_type="favorite",
                object_key=name,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
            )
        return _official_success_response(attempt, {"name": name, "deleted": True, "syncStatus": SYNC_OFFICIAL})
    if not _local_write_allowed(user):
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        s.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name))
        local = {
            "name": name,
            "deleted": True,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_LOCAL_FALLBACK,
            "lastError": attempt["lastError"],
            "toolhubResponse": attempt["details"],
            "validationErrors": attempt["validationErrors"],
        }
        _emit_structured_activity(
            s,
            user,
            action="favorite-removed",
            object_type="favorite",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/crawler/urls/", methods=["POST"])
@write_guard
def write_crawler_url_add() -> Response:
    """Official-first lifecycle for crawler URL registration."""
    value, err = _json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    url = value.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > MAX_URL:
        return _bad("crawler URL must be an https URL")
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "POST", "/api/crawler/urls/", {"url": url})
    if denied is not None:
        return denied
    if attempt["ok"]:
        official_id = _official_id(attempt["toolhub"])
        with db.session_scope() as s:
            row = _store_crawler_url_row(
                s,
                user,
                url,
                sync_status=SYNC_OFFICIAL,
                official_id=official_id,
                toolhub_body=attempt["toolhub"],
            )
            local = _crawler_url_payload(row)
            _emit_structured_activity(
                s,
                user,
                action="crawler-url-added",
                object_type="crawler_url",
                object_key=url,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "local": local, "syncStatus": SYNC_OFFICIAL},
            )
        return _official_success_response(attempt, local)
    if not _local_write_allowed(user):
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        row = _store_crawler_url_row(s, user, url, sync_status=SYNC_LOCAL_FALLBACK, failure=attempt)
        local = _crawler_url_payload(row)
        _emit_structured_activity(
            s,
            user,
            action="crawler-url-added",
            object_type="crawler_url",
            object_key=url,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/crawler/urls/<int:url_id>/", methods=["DELETE"])
@write_guard
def write_crawler_url_delete(url_id: int) -> Response:
    """Official-first lifecycle for crawler URL removal."""
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", _upstream_path(f"crawler/urls/{url_id}/"), None)
    if denied is not None:
        return denied
    if not attempt["ok"]:
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        rows = s.execute(
            select(CrawlerUrl).where(
                CrawlerUrl.user_id == user.id,
                CrawlerUrl.official_crawler_url_id == url_id,
            )
        ).scalars()
        now = utcnow()
        for row in rows:
            row.enabled = False
            row.sync_status = SYNC_OFFICIAL
            row.last_synced_at = now
            row.last_error = None
        _emit_structured_activity(
            s,
            user,
            action="crawler-url-deleted",
            object_type="crawler_url",
            object_key=str(url_id),
            official_status=SYNC_OFFICIAL,
            payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
        )
    return _official_success_response(attempt)


def _tool_fallback_kind() -> tuple[str | None, Response | None]:
    value = request.get_json(silent=True) or {}
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind not in TOOL_FALLBACK_KINDS:
        return None, _bad("kind must be new, edit, or annotations")
    return str(kind), None


def _discard_response() -> Response:
    return jsonify({"ok": True, "result": OFFICIAL_STATUS_DISCARDED})


@v1_bp.route("/v1/write/tools/<name>/retry/", methods=["POST"])
@write_guard
def write_tool_retry(name: str) -> Response:  # noqa: PLR0911 - retry exits mirror validation/not found/sync outcomes
    """Retry publishing one Evolved-local tool fallback."""
    clean_name = _clean_name(name)
    kind, err = _tool_fallback_kind()
    if clean_name is None:
        return _bad("tool name is required")
    if err is not None:
        return err
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    assert kind is not None  # noqa: S101 - err covers invalid kinds
    with db.session_scope() as s:
        if kind == "new":
            row = s.execute(
                select(ToolRecord).where(
                    ToolRecord.tool_name == clean_name,
                    ToolRecord.user_id == user.id,
                    ToolRecord.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                return _deny(HTTP_NOT_FOUND, "fallback record not found")
            fields = row.record if isinstance(row.record, dict) else {}
            method, path, official_payload = (
                "POST",
                "/api/tools/",
                _official_tool_payload(clean_name, fields, include_name=True),
            )
        else:
            overlay_kind = TOOL_OVERLAY_KIND_BY_FALLBACK[kind]
            row = s.execute(
                select(ToolOverlay).where(
                    ToolOverlay.kind == overlay_kind,
                    ToolOverlay.tool_name == clean_name,
                    ToolOverlay.user_id == user.id,
                    ToolOverlay.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                return _deny(HTTP_NOT_FOUND, "fallback record not found")
            fields = row.patch if isinstance(row.patch, dict) else {}
            method = "PUT"
            fragment = f"tools/{clean_name}/annotations/" if kind == "annotations" else f"tools/{clean_name}/"
            path = _upstream_path(fragment)
            official_payload = (
                _official_annotation_payload(fields)
                if kind == "annotations"
                else _official_tool_payload(clean_name, fields, include_name=False)
            )
    attempt, denied = _attempt_official_write(user, method, path, official_payload)
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            if kind == "new":
                s.execute(delete(ToolRecord).where(ToolRecord.tool_name == clean_name, ToolRecord.user_id == user.id))
            else:
                s.execute(
                    delete(ToolOverlay).where(
                        ToolOverlay.kind == TOOL_OVERLAY_KIND_BY_FALLBACK[kind],
                        ToolOverlay.tool_name == clean_name,
                        ToolOverlay.user_id == user.id,
                    )
                )
            _emit_structured_activity(
                s,
                user,
                action="retried",
                object_type="tool",
                object_key=clean_name,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
            )
        return _official_success_response(attempt)
    with db.session_scope() as s:
        if kind == "new":
            local = _store_tool_record_fallback(s, user, clean_name, fields, attempt)
        else:
            local = _store_tool_overlay_fallback(
                s,
                user,
                clean_name,
                TOOL_OVERLAY_KIND_BY_FALLBACK[kind],
                fields,
                attempt,
            )
        _emit_structured_activity(
            s,
            user,
            action="retry-failed",
            object_type="tool",
            object_key=clean_name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/tools/<name>/fallback/", methods=["DELETE"])
@write_guard
def write_tool_fallback_discard(name: str) -> Response:
    """Discard one Evolved-local tool fallback."""
    clean_name = _clean_name(name)
    kind, err = _tool_fallback_kind()
    if clean_name is None:
        return _bad("tool name is required")
    if err is not None:
        return err
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    assert kind is not None  # noqa: S101 - err covers invalid kinds
    with db.session_scope() as s:
        if kind == "new":
            result = s.execute(
                delete(ToolRecord).where(ToolRecord.tool_name == clean_name, ToolRecord.user_id == user.id)
            )
        else:
            result = s.execute(
                delete(ToolOverlay).where(
                    ToolOverlay.kind == TOOL_OVERLAY_KIND_BY_FALLBACK[kind],
                    ToolOverlay.tool_name == clean_name,
                    ToolOverlay.user_id == user.id,
                )
            )
        if result.rowcount == 0:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        _emit_structured_activity(
            s,
            user,
            action="discarded",
            object_type="tool",
            object_key=clean_name,
            official_status=OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": OFFICIAL_STATUS_DISCARDED},
        )
    return _discard_response()


@v1_bp.route("/v1/write/lists/<client_id>/retry/", methods=["POST"])
@write_guard
def write_list_retry(client_id: str) -> Response:
    """Retry publishing one local list fallback."""
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        row = s.execute(
            select(ToolList).where(
                ToolList.client_id == client_id,
                ToolList.user_id == user.id,
                ToolList.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        if not authz.can(user, authz.ACTION_PRIVATE_WRITE, row):
            return _deny(HTTP_FORBIDDEN, "not allowed")
        fields = {
            "client_id": row.client_id,
            "title": row.title,
            "description": row.description,
            "tools": row.tools if isinstance(row.tools, list) else [],
        }
        official_id = row.official_list_id
    method = "PUT" if official_id is not None else "POST"
    path = _upstream_path(f"lists/{official_id}/") if official_id is not None else "/api/lists/"
    attempt, denied = _attempt_official_write(user, method, path, _official_list_payload(fields))
    if denied is not None:
        return denied
    with db.session_scope() as s:
        if attempt["ok"]:
            row = _store_list_row(
                s,
                user,
                fields,
                sync_status=SYNC_OFFICIAL,
                official_id=_official_id(attempt["toolhub"], official_id),
                toolhub_body=attempt["toolhub"],
            )
            local = _list_payload(row)
            _emit_structured_activity(
                s,
                user,
                action="list-retried",
                object_type="list",
                object_key=row.client_id,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "local": local, "syncStatus": SYNC_OFFICIAL},
                title=row.title,
            )
            return _official_success_response(attempt, local)
        row = _store_list_row(
            s,
            user,
            fields,
            sync_status=SYNC_LOCAL_FALLBACK,
            official_id=official_id,
            failure=attempt,
        )
        local = _list_payload(row)
        _emit_structured_activity(
            s,
            user,
            action="list-retry-failed",
            object_type="list",
            object_key=row.client_id,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
            title=row.title,
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/lists/<client_id>/fallback/", methods=["DELETE"])
@write_guard
def write_list_fallback_discard(client_id: str) -> Response:
    """Discard one local list fallback."""
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    with db.session_scope() as s:
        row = s.execute(
            select(ToolList).where(
                ToolList.client_id == client_id,
                ToolList.user_id == user.id,
                ToolList.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        row.deleted_at = utcnow()
        _emit_structured_activity(
            s,
            user,
            action="list-discarded",
            object_type="list",
            object_key=client_id,
            official_status=OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": OFFICIAL_STATUS_DISCARDED},
            title=row.title,
        )
    return _discard_response()


@v1_bp.route("/v1/write/crawler/urls/<int:local_id>/retry/", methods=["POST"])
@write_guard
def write_crawler_url_retry(local_id: int) -> Response:
    """Retry publishing one crawler URL fallback."""
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        row = s.execute(
            select(CrawlerUrl).where(
                CrawlerUrl.id == local_id,
                CrawlerUrl.user_id == user.id,
                CrawlerUrl.enabled.is_(True),
            )
        ).scalar_one_or_none()
        if row is None:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        if not authz.can(user, authz.ACTION_PRIVATE_WRITE, row):
            return _deny(HTTP_FORBIDDEN, "not allowed")
        url = row.url
    attempt, denied = _attempt_official_write(user, "POST", "/api/crawler/urls/", {"url": url})
    if denied is not None:
        return denied
    with db.session_scope() as s:
        if attempt["ok"]:
            row = _store_crawler_url_row(
                s,
                user,
                url,
                sync_status=SYNC_OFFICIAL,
                official_id=_official_id(attempt["toolhub"]),
                toolhub_body=attempt["toolhub"],
            )
            local = _crawler_url_payload(row)
            _emit_structured_activity(
                s,
                user,
                action="crawler-url-retried",
                object_type="crawler_url",
                object_key=url,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "local": local, "syncStatus": SYNC_OFFICIAL},
            )
            return _official_success_response(attempt, local)
        row = _store_crawler_url_row(s, user, url, sync_status=SYNC_LOCAL_FALLBACK, failure=attempt)
        local = _crawler_url_payload(row)
        _emit_structured_activity(
            s,
            user,
            action="crawler-url-retry-failed",
            object_type="crawler_url",
            object_key=url,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/crawler/urls/<int:local_id>/fallback/", methods=["DELETE"])
@write_guard
def write_crawler_url_fallback_discard(local_id: int) -> Response:
    """Discard one local crawler URL fallback."""
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    with db.session_scope() as s:
        result = s.execute(delete(CrawlerUrl).where(CrawlerUrl.id == local_id, CrawlerUrl.user_id == user.id))
        if result.rowcount == 0:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        _emit_structured_activity(
            s,
            user,
            action="crawler-url-discarded",
            object_type="crawler_url",
            object_key=str(local_id),
            official_status=OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": OFFICIAL_STATUS_DISCARDED},
        )
    return _discard_response()


@v1_bp.route("/v1/write/user/favorites/<tool_name>/retry/", methods=["POST"])
@write_guard
def write_favorite_retry(tool_name: str) -> Response:
    """Retry publishing one favorite fallback."""
    name = _clean_name(tool_name)
    if name is None:
        return _bad("favorite needs a tool name")
    user = _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        row = s.execute(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name)
        ).scalar_one_or_none()
        if row is None:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        if not authz.can(user, authz.ACTION_PRIVATE_WRITE, row):
            return _deny(HTTP_FORBIDDEN, "not allowed")
    attempt, denied = _attempt_official_write(user, "POST", "/api/user/favorites/", {"name": name})
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            _upsert_favorite(s, user, name, sync_status=SYNC_OFFICIAL)
            _emit_structured_activity(
                s,
                user,
                action="favorite-retried",
                object_type="favorite",
                object_key=name,
                official_status=SYNC_OFFICIAL,
                payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
            )
        return _official_success_response(attempt, {"name": name, "syncStatus": SYNC_OFFICIAL})
    with db.session_scope() as s:
        _upsert_favorite(s, user, name, sync_status=SYNC_LOCAL_FALLBACK, failure=attempt)
        local = {
            "name": name,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_LOCAL_FALLBACK,
            "lastError": attempt["lastError"],
            "toolhubResponse": attempt["details"],
            "validationErrors": attempt["validationErrors"],
        }
        _emit_structured_activity(
            s,
            user,
            action="favorite-retry-failed",
            object_type="favorite",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_bp.route("/v1/write/user/favorites/<tool_name>/fallback/", methods=["DELETE"])
@write_guard
def write_favorite_fallback_discard(tool_name: str) -> Response:
    """Discard one favorite fallback."""
    name = _clean_name(tool_name)
    if name is None:
        return _bad("favorite needs a tool name")
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    with db.session_scope() as s:
        result = s.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name))
        if result.rowcount == 0:
            return _deny(HTTP_NOT_FOUND, "fallback record not found")
        _emit_structured_activity(
            s,
            user,
            action="favorite-discarded",
            object_type="favorite",
            object_key=name,
            official_status=OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": OFFICIAL_STATUS_DISCARDED},
        )
    return _discard_response()


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
            _list_payload(row)
            for row in s.execute(
                select(ToolList)
                .where(ToolList.user_id == uid, ToolList.deleted_at.is_(None))
                .order_by(ToolList.created_at.desc())
            ).scalars()
        ]
        crawler_urls = [
            _crawler_url_payload(c)
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
            response = _payload_value(item, "toolhubResponse", "last_toolhub_response")
            validation_errors = _payload_value(item, "validationErrors", "validation_errors")
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
                    last_toolhub_response=response if isinstance(response, dict) else None,
                    validation_errors=validation_errors if isinstance(validation_errors, list) else None,
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
            response = _payload_value(u, "toolhubResponse", "last_toolhub_response")
            validation_errors = _payload_value(u, "validationErrors", "validation_errors")
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
                    last_toolhub_response=response if isinstance(response, dict) else None,
                    validation_errors=validation_errors if isinstance(validation_errors, list) else None,
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
    record_changed: bool = True,
) -> dict[str, Any]:
    """Extract lifecycle metadata from a toolNew payload."""
    is_crawler_record = rec.get("origin") == "crawler"
    visibility = _visibility(
        _payload_value(rec, "visibility"), VISIBILITY_PUBLIC if is_crawler_record else VISIBILITY_PRIVATE
    )
    preserved_review = clean_review_status(existing_review_status, REVIEW_PENDING)
    if can_review:
        review_status = clean_review_status(_payload_value(rec, "reviewStatus", "review_status"), preserved_review)
    elif visibility == VISIBILITY_PUBLIC and not record_changed:
        review_status = preserved_review
    else:
        review_status = REVIEW_PENDING
    default_status = SYNC_EVOLVED_REAL if visibility == VISIBILITY_PUBLIC else SYNC_LOCAL_DRAFT
    status = clean_sync_status(_payload_value(rec, "syncStatus", "sync_status"), default_status)
    official_name = _payload_value(rec, "officialName", "official_name")
    response = _payload_value(rec, "toolhubResponse", "last_toolhub_response")
    validation_errors = _payload_value(rec, "validationErrors", "validation_errors")
    return {
        "visibility": visibility,
        "source": SOURCE_LOCAL,
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
    response = _payload_value(patch, "toolhubResponse", "last_toolhub_response")
    validation_errors = _payload_value(patch, "validationErrors", "validation_errors")
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
        "last_toolhub_response": response if isinstance(response, dict) else None,
        "validation_errors": validation_errors if isinstance(validation_errors, list) else None,
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
        existing = existing_own.get(name)
        cleaned[name] = (
            clean,
            _tool_record_meta(
                rec,
                can_review=can_review,
                existing_review_status=getattr(existing, "review_status", None),
                record_changed=existing is None
                or (existing.record if isinstance(existing.record, dict) else {}) != clean,
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
            .where(
                ToolThanks.tool_name == clean_name,
                ToolThanks.active.is_(True),
                ToolThanks.review_status == REVIEW_APPROVED,
            )
        ).scalar_one()
        user_thanked = (
            bool(
                s.execute(
                    select(ToolThanks.id).where(
                        ToolThanks.tool_name == clean_name,
                        ToolThanks.user_id == uid,
                        ToolThanks.active.is_(True),
                        ToolThanks.review_status == REVIEW_APPROVED,
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
            .where(ToolHealthTarget.review_status == REVIEW_APPROVED)
            .order_by(ToolHealthTarget.last_checked_at.desc(), ToolHealthTarget.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    return jsonify(
        {
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
            "thanks": {
                "count": int(thanks_count),
                "userThanked": user_thanked,
                "syncStatus": SYNC_EVOLVED_REAL,
                "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
            },
            "usage30d": {
                "count": int(events_30d),
                "label": "30-day Evolved usage",
                "syncStatus": SYNC_EVOLVED_REAL,
                "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
            },
            "health": {
                "status": health.last_status if health and health.last_status else "unknown",
                "checkedAt": _iso(health.last_checked_at) if health else "",
                "targetUrl": health.target_url if health else "",
                "lastError": health.last_error if health else "",
                "reviewStatus": clean_review_status(health.review_status, REVIEW_APPROVED) if health else "",
                "syncStatus": SYNC_EVOLVED_REAL,
                "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
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
    if request.method == "POST":
        _require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
    else:
        _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
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
                review_status=REVIEW_APPROVED,
            )
            s.add(row)
        else:
            if row.created_by_user_id is None:
                row.created_by_user_id = uid
            row.review_status = clean_review_status(row.review_status, REVIEW_APPROVED)
            row.active = request.method == "POST"
            row.updated_at = utcnow()
    return jsonify(
        {
            "ok": True,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
        }
    )


@v1_bp.route("/v1/tools/<name>/health-target/", methods=["PUT"])
@write_guard
def v1_tool_health_target(name: str) -> Response:
    """Store the caller's Evolved health target URL for a tool."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    _require_policy_or_abort(authz.ACTION_PUBLIC_WRITE)
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
            row = ToolHealthTarget(
                tool_name=clean_name,
                created_by_user_id=uid,
                target_url=target_url[:MAX_URL],
                source=SOURCE_LOCAL,
                sync_status=SYNC_EVOLVED_REAL,
                review_status=REVIEW_PENDING,
            )
            s.add(row)
        else:
            if row.target_url != target_url[:MAX_URL]:
                row.review_status = REVIEW_PENDING
            row.target_url = target_url[:MAX_URL]
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
            row.enabled = True
            row.deleted_at = None
            row.last_error = None
        s.flush()
        payload = _health_target_payload(row)
    return jsonify({"ok": True, "healthTarget": payload})


def _tool_media_get(clean_name: str) -> Response:
    """Return approved public media for a tool."""
    with db.session_scope() as s:
        rows = list(
            s.execute(
                select(ToolMedia)
                .where(
                    ToolMedia.tool_name == clean_name,
                    ToolMedia.deleted_at.is_(None),
                    ToolMedia.review_status == REVIEW_APPROVED,
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
            review_status=REVIEW_PENDING,
            sync_status=SYNC_EVOLVED_REAL,
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


def _moderation_row(s: Any, kind: str, item_id: int) -> object | None:  # noqa: ANN401
    return s.get(MODERATION_MODELS[kind], item_id)


def _moderation_row_visible(kind: str, row: object | None) -> bool:
    if row is None:
        return False
    if getattr(row, "deleted_at", None) is not None:
        return False
    if kind == "tool-records":
        return getattr(row, "visibility", None) == VISIBILITY_PUBLIC
    return True


@v1_bp.route("/v1/moderation/public-data/")
@login_required
def v1_moderation_public_data() -> Response:
    """Return pending Evolved-owned public data for reviewer moderation."""
    _require_policy_or_abort(authz.ACTION_PUBLIC_REVIEW)
    with db.session_scope() as s:
        items = [
            *[
                _moderation_item("tool-records", row)
                for row in s.execute(
                    select(ToolRecord)
                    .where(
                        ToolRecord.deleted_at.is_(None),
                        ToolRecord.visibility == VISIBILITY_PUBLIC,
                        ToolRecord.review_status == REVIEW_PENDING,
                    )
                    .order_by(ToolRecord.modified_at.desc(), ToolRecord.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                _moderation_item("health-targets", row)
                for row in s.execute(
                    select(ToolHealthTarget)
                    .where(ToolHealthTarget.deleted_at.is_(None), ToolHealthTarget.review_status == REVIEW_PENDING)
                    .order_by(ToolHealthTarget.created_at.desc(), ToolHealthTarget.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                _moderation_item("media", row)
                for row in s.execute(
                    select(ToolMedia)
                    .where(ToolMedia.deleted_at.is_(None), ToolMedia.review_status == REVIEW_PENDING)
                    .order_by(ToolMedia.created_at.desc(), ToolMedia.id.desc())
                    .limit(50)
                ).scalars()
            ],
            *[
                _moderation_item("thanks", row)
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
            "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
            "count": len(items),
            "results": items,
        }
    )


@v1_bp.route("/v1/moderation/public-data/<kind>/<int:item_id>/", methods=["PUT"])
@write_guard
def v1_moderation_public_data_update(kind: str, item_id: int) -> Response:
    """Apply reviewer moderation to one Evolved-owned public record."""
    if kind not in MODERATION_KINDS:
        return _deny(HTTP_NOT_FOUND, "moderation record not found")
    user = _require_policy_or_abort(authz.ACTION_PUBLIC_REVIEW)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return _bad("moderation body must be a JSON object")
    review_status = value.get("reviewStatus") or value.get("review_status")
    if review_status not in PUBLIC_REVIEW_STATUSES:
        return _bad("reviewStatus must be pending, approved, or rejected")
    with db.session_scope() as s:
        row = _moderation_row(s, kind, item_id)
        if not _moderation_row_visible(kind, row):
            return _deny(HTTP_NOT_FOUND, "moderation record not found")
        assert row is not None  # noqa: S101 - visible check excludes None
        row.review_status = str(review_status)
        if isinstance(row, ToolRecord):
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
            if review_status == REVIEW_APPROVED:
                row.visibility = VISIBILITY_PUBLIC
        elif isinstance(row, ToolHealthTarget):
            row.source = SOURCE_LOCAL
            row.sync_status = SYNC_EVOLVED_REAL
        else:
            row.sync_status = SYNC_EVOLVED_REAL
        s.flush()
        item = _moderation_item(kind, row)
        _emit_structured_activity(
            s,
            user,
            action="public-data-reviewed",
            object_type=kind,
            object_key=str(item_id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"kind": kind, "reviewStatus": review_status, "item": item},
        )
    return jsonify(
        {
            "ok": True,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "syncLabel": _sync_label(SYNC_EVOLVED_REAL),
            "item": item,
        }
    )


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
