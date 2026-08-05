# SPDX-License-Identifier: GPL-3.0-or-later
"""Official Toolhub write bridge: the /v1/write/* endpoints.

Split out of backend/v1.py, which had grown to 5,707 lines holding 83 of the
application's 87 routes across 23 unrelated resource families. These 17 routes
and the 36 helpers only they use are the largest self-contained group in it.

URL paths are unchanged; only the Flask endpoint names move under a second
blueprint. Helpers still shared with other families are reached as `v1.<name>` so there
is exactly one binding for each: importing the names instead binds a second
reference, and patching backend.v1 then stops affecting this module.
"""

from typing import Any
from uuid import uuid4

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import delete, func, or_, select

from backend import (
    authz,
    db,
    toolhub,
    v1,
)
from backend import v1_common as common
from backend.models import (
    CrawlerUrl,
    Favorite,
    ToolList,
    ToolOverlay,
    ToolRecord,
    User,
    utcnow,
)
from backend.security import current_user_id, write_guard
from backend.sync import (
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
    SYNC_ERROR,
    SYNC_EVOLVED_REAL,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
    clean_error,
    clean_int,
    clean_review_status,
)

v1_write_bp = Blueprint("v1_write", __name__)


def _string_list(value: Any) -> list[str]:  # noqa: ANN401
    """Normalize official/list-like array fields into bounded strings."""
    if not isinstance(value, list):
        return []
    return [str(item)[: common.MAX_NAME] for item in value[:50] if isinstance(item, str | int | float)]


def _message_from_payload(payload: object, default: str) -> str:
    """Extract the clearest user-facing message from a Toolhub error payload."""
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[: common.MAX_DESCRIPTION]
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
    except ValueError:
        # toolhub.api_path refused the path, so nothing left the process. Return a
        # denial rather than a failure payload: a failure here would be treated as
        # "Toolhub rejected the write" and stored as a local fallback draft, which
        # would persist a draft keyed on a path that can never be valid.
        return {}, common.bad("invalid official Toolhub path")
    except toolhub.ToolhubAuthError as exc:
        resp = jsonify({"error": str(exc), "reauth": True})
        resp.status_code = common.HTTP_UNAUTHORIZED
        return {}, resp
    except toolhub.ToolhubAPIError as exc:
        return _failure_payload(exc.status_code, exc.payload, "official Toolhub rejected the write"), None
    except toolhub.requests.RequestException:
        return (
            _failure_payload(502, {"message": "official Toolhub is unavailable"}, "official Toolhub is unavailable"),
            None,
        )
    common.invalidate_official_api_cache(path, payload, body)
    common.record_successful_toolhub_write(user, method, path, payload, body)
    return {
        "ok": True,
        "status": status,
        "toolhub": body if status != v1.HTTP_NO_CONTENT else {"ok": True},
        "lastSyncedAt": common.iso(utcnow()),
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
    if attempt.get("crawlerFetch") is not None:
        payload["crawlerFetch"] = attempt["crawlerFetch"]
    resp = jsonify(payload)
    resp.status_code = 200 if attempt["status"] == v1.HTTP_NO_CONTENT else int(attempt["status"])
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
    details = failure.get("details") if isinstance(failure.get("details"), dict) else {}
    payload = {
        "ok": True,
        "result": SYNC_LOCAL_FALLBACK,
        "syncStatus": SYNC_LOCAL_FALLBACK,
        "lastError": failure["lastError"],
        "validationErrors": failure["validationErrors"],
        "toolhubResponse": failure["details"],
        "toolhubStatus": failure.get("status"),
        "toolhubCode": details.get("code"),
        "local": local,
    }
    if failure.get("crawlerFetch") is not None:
        payload["crawlerFetch"] = failure["crawlerFetch"]
    resp = jsonify(payload)
    resp.status_code = 202
    return resp


def _compact_tool_payload(payload: dict, route_name: str | None = None) -> tuple[str | None, dict | None]:
    """Convert official Toolhub tool payloads into Evolved's compact tool shape."""
    name = common.clean_name(route_name or str(payload.get("name") or ""))
    compact = {
        "title": payload.get("title"),
        "description": payload.get("description"),
        "url": payload.get("url"),
        "repository": payload.get("repository"),
        "license": payload.get("license"),
        "toolType": common.payload_value(payload, "toolType", "tool_type"),
        "keywords": _string_list(payload.get("keywords")),
        "forWikis": _string_list(common.payload_value(payload, "forWikis", "for_wikis")),
        "uiLanguages": _string_list(common.payload_value(payload, "uiLanguages", "available_ui_languages")),
        "deprecated": bool(payload.get("deprecated")),
        "experimental": bool(payload.get("experimental")),
    }
    clean = common.clean_tool_record(compact)
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


def _validated_tool_write(
    value: dict,
    route_name: str | None,
) -> tuple[str | None, dict | None, str | None, Response | None]:
    """Validate a tool write request and extract create-only crawler metadata."""
    name, fields = _compact_tool_payload(value, route_name)
    if name is None or fields is None:
        return None, None, None, common.bad("tool write needs name, title, description and an https url")
    if route_name is not None:
        return name, fields, None, None
    toolinfo_url, toolinfo_err = _create_toolinfo_url(value)
    return name, fields, toolinfo_url, toolinfo_err


def _create_toolinfo_url(payload: dict) -> tuple[str | None, Response | None]:
    """Return a valid create-time toolinfo URL, when supplied."""
    value = common.payload_value(payload, "toolinfoUrl", "toolinfo_url")
    if not isinstance(value, str) or not value.strip():
        return None, None
    url = value.strip()
    error = common.url_validation_message(url, label="toolinfo URL")
    if error is not None:
        return None, common.url_validation_bad("toolinfo_url", error)
    return url, None


def _fetch_toolinfo_json_once(url: str) -> object:
    """Reuse the scheduled crawler's hardened fetcher for create-time enrichment."""
    import crawl  # noqa: PLC0415 - local import avoids backend package startup cycles.

    return crawl._fetch_json(toolhub.requests.Session(), url)  # noqa: SLF001 - reuse the crawler's fetch


def _normalize_toolinfo_item(item: dict) -> dict | None:
    """Reuse the crawler's compact toolinfo→Evolved record mapping."""
    import crawl  # noqa: PLC0415 - local import avoids backend package startup cycles.

    return crawl.normalize_record(item)


def _matching_toolinfo_item(data: object, name: str) -> dict | None:
    """Find the item for the tool being created in one toolinfo response."""
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data[: v1.TOOLINFO_CREATE_MAX_ITEMS]
    else:
        return None
    for item in items:
        if isinstance(item, dict) and common.clean_name(item.get("name")) == name:
            return item
    return None


def _merge_toolinfo_fields(fields: dict, record: dict) -> tuple[dict, list[str]]:
    """Fill missing create fields from toolinfo while preserving explicit user input."""
    merged = dict(fields)
    enriched: list[str] = []
    for field in v1.TOOLINFO_CREATE_OPT_FIELDS:
        if not merged.get(field) and record.get(field):
            merged[field] = record[field]
            enriched.append(field)
    for field in v1.TOOLINFO_CREATE_LIST_FIELDS:
        if not merged.get(field) and record.get(field):
            merged[field] = record[field]
            enriched.append(field)
    for field in v1.TOOLINFO_CREATE_BOOL_FIELDS:
        if not merged.get(field) and record.get(field):
            merged[field] = True
            enriched.append(field)
    return merged, enriched


def _create_toolinfo_enrichment(
    fields: dict,
    name: str,
    toolinfo_url: str | None,
) -> tuple[dict, dict | None, dict | None]:
    """Fetch toolinfo once during create and return enriched fields plus evidence."""
    if toolinfo_url is None:
        return fields, None, None
    result: dict[str, object] = {"url": toolinfo_url, "ok": False, "matched": False, "enrichedFields": []}
    try:
        data = _fetch_toolinfo_json_once(toolinfo_url)
    except (toolhub.requests.RequestException, ValueError) as exc:
        result["lastError"] = clean_error(str(exc)) or "toolinfo fetch failed"
        return fields, None, result
    item = _matching_toolinfo_item(data, name)
    if item is None:
        result["lastError"] = f"{name}: no matching item found in toolinfo"
        return fields, None, result
    record = _normalize_toolinfo_item(item)
    if record is None:
        result["matched"] = True
        result["lastError"] = f"{name}: toolinfo item is missing name, title, description or url"
        return fields, item, result
    merged, enriched = _merge_toolinfo_fields(fields, record)
    result.update({"ok": True, "matched": True, "enrichedFields": enriched})
    return merged, item, result


def _record_create_toolinfo_evidence(
    s: Any,  # noqa: ANN401 - SQLAlchemy Session
    user: User,
    toolinfo_url: str | None,
    toolinfo_item: dict | None,
    crawler_fetch: dict | None,
) -> None:
    """Record create-time crawler evidence without changing Toolhub canonical data."""
    if toolinfo_url is None or crawler_fetch is None:
        return
    if crawler_fetch.get("ok"):
        _store_crawler_url_row(
            s,
            user,
            toolinfo_url,
            sync_status=SYNC_EVOLVED_REAL,
            toolhub_body={
                "source": "tool-create-fetch",
                "toolName": toolinfo_item.get("name") if toolinfo_item else None,
            },
        )
        if toolinfo_item is not None:
            try:
                owner = s.get(User, user.id) or user
                v1.SIGNED_TOOLINFO_PROVIDER.verify(s, owner, toolinfo=toolinfo_item, evidence_url=toolinfo_url)
            except Exception:  # noqa: BLE001 - evidence collection must not break an already accepted create.
                return
        return
    failure = _failure_payload(
        422,
        {"message": crawler_fetch.get("lastError"), "url": toolinfo_url},
        str(crawler_fetch.get("lastError") or "toolinfo fetch failed"),
    )
    _store_crawler_url_row(s, user, toolinfo_url, sync_status=SYNC_ERROR, failure=failure)


def _maybe_enrich_create_tool(
    fields: dict,
    name: str,
    toolinfo_url: str | None,
    *,
    create_like: bool,
) -> tuple[dict, dict | None, dict | None]:
    """Run one-shot toolinfo enrichment only for create-like writes."""
    return _create_toolinfo_enrichment(fields, name, toolinfo_url) if create_like else (fields, None, None)


def _with_crawler_fetch(payload: dict, crawler_fetch: dict | None) -> dict:
    """Attach create-time crawler fetch metadata when the request used it."""
    if crawler_fetch is not None:
        payload["crawlerFetch"] = crawler_fetch
    return payload


def _compact_annotation_payload(payload: dict) -> dict:
    tool_type = common.payload_value(payload, "toolType", "tool_type")
    icon = payload.get("icon")
    return {
        "audiences": _string_list(payload.get("audiences")),
        "tasks": _string_list(payload.get("tasks")),
        "toolType": str(tool_type)[: common.MAX_NAME] if isinstance(tool_type, str) and tool_type else None,
        "icon": str(icon)[: common.MAX_URL] if isinstance(icon, str) and icon else None,
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
        "title": title.strip()[: common.MAX_NAME],
        "description": str(payload.get("description") or "")[: common.MAX_DESCRIPTION],
        "tools": [
            str(tool)[: common.MAX_NAME] for tool in tools[: v1.MAX_ITEMS] if isinstance(tool, str | int | float)
        ],
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
    row.visibility = common.VISIBILITY_PRIVATE
    row.source = SOURCE_LOCAL
    row.sync_status = SYNC_LOCAL_FALLBACK
    row.review_status = clean_review_status(row.review_status, REVIEW_PENDING)
    row.last_synced_at = None
    row.last_error = clean_error(failure["lastError"])
    row.last_toolhub_response = failure["details"]
    row.validation_errors = failure["validationErrors"]
    row.deleted_at = None
    return common.tool_record_payload(row)


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
    row.patch = common.data_patch(patch)
    row.modified_at = utcnow()
    row.source = SOURCE_LOCAL
    row.sync_status = SYNC_LOCAL_FALLBACK
    row.last_synced_at = None
    row.last_error = clean_error(failure["lastError"])
    row.last_toolhub_response = failure["details"]
    row.validation_errors = failure["validationErrors"]
    row.review_status = clean_review_status(row.review_status, REVIEW_OPEN)
    row.deleted_at = None
    return common.with_common_meta(row.patch, row)


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
        row = CrawlerUrl(user_id=user.id, created_by_user_id=user.id, url=url[: common.MAX_URL])
        s.add(row)
    row.created_by_user_id = row.created_by_user_id or user.id
    row.url = url[: common.MAX_URL]
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


def _write_tool_core(route_name: str | None = None) -> Response:
    value, err = common.json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    name, fields, toolinfo_url, toolinfo_err = _validated_tool_write(value, route_name)
    if toolinfo_err is not None:
        return toolinfo_err
    assert name is not None  # noqa: S101 - _validated_tool_write returned no denial
    assert fields is not None  # noqa: S101 - _validated_tool_write returned no denial
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
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
    path = "/api/tools/" if create_like else common.upstream_path(f"tools/{name}/")
    fields, toolinfo_item, crawler_fetch = _maybe_enrich_create_tool(
        fields,
        name,
        toolinfo_url,
        create_like=create_like,
    )
    attempt, denied = _attempt_official_write(
        user,
        method,
        path,
        _official_tool_payload(name, fields, include_name=create_like),
    )
    if denied is not None:
        return denied
    _with_crawler_fetch(attempt, crawler_fetch)
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
            _record_create_toolinfo_evidence(s, user, toolinfo_url, toolinfo_item, crawler_fetch)
            common.emit_structured_activity(
                s,
                user,
                action="created" if create_like else "edited",
                object_type="tool",
                object_key=name,
                official_status=SYNC_OFFICIAL,
                payload=_with_crawler_fetch(
                    {"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
                    crawler_fetch,
                ),
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
        _record_create_toolinfo_evidence(s, user, toolinfo_url, toolinfo_item, crawler_fetch)
        common.emit_structured_activity(
            s,
            user,
            action=action,
            object_type="tool",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload=_with_crawler_fetch(
                {
                    "lastError": attempt["lastError"],
                    "toolhubResponse": attempt["details"],
                    "_toolhubStatus": attempt["status"],
                    "_toolhubCode": attempt["details"].get("code") if isinstance(attempt["details"], dict) else None,
                    "local": local,
                },
                crawler_fetch,
            ),
            title=fields["title"],
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/tools/", methods=["POST"])
@write_guard
def write_tool_create() -> Response:
    """Official-first lifecycle for creating a Toolhub tool."""
    return _write_tool_core()


@v1_write_bp.route("/v1/write/tools/<name>/", methods=["PUT", "DELETE"])
@write_guard
def write_tool_update(name: str) -> Response:
    """Official-first lifecycle for updating or deleting a Toolhub tool."""
    clean_name = common.clean_name(name)
    if clean_name is None:
        return common.bad("tool name is required")
    if request.method == "PUT":
        return _write_tool_core(clean_name)
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", common.upstream_path(f"tools/{clean_name}/"), None)
    if denied is not None:
        return denied
    if not attempt["ok"]:
        return _official_failure_response(attempt)
    with db.session_scope() as s:
        s.execute(delete(ToolRecord).where(ToolRecord.tool_name == clean_name, ToolRecord.user_id == user.id))
        s.execute(delete(ToolOverlay).where(ToolOverlay.tool_name == clean_name, ToolOverlay.user_id == user.id))
        common.emit_structured_activity(
            s,
            user,
            action="deleted",
            object_type="tool",
            object_key=clean_name,
            official_status=SYNC_OFFICIAL,
            payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
        )
    return _official_success_response(attempt)


@v1_write_bp.route("/v1/write/tools/<name>/annotations/", methods=["PUT"])
@write_guard
def write_annotations_update(name: str) -> Response:
    """Official-first lifecycle for tool annotations."""
    clean_name = common.clean_name(name)
    value, err = common.json_object_body()
    if clean_name is None:
        return common.bad("tool name is required")
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    fields = _compact_annotation_payload(value)
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(
        user,
        "PUT",
        common.upstream_path(f"tools/{clean_name}/annotations/"),
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
            common.emit_structured_activity(
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
        common.emit_structured_activity(
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
    value, err = common.json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    official_route_id = clean_int(route_id)
    fields = _clean_list_write_payload(user.id, value, route_id)
    if fields is None:
        return common.bad("list write needs title and tools")
    method = "POST" if route_id is None else "PUT"
    path = "/api/lists/" if route_id is None else common.upstream_path(f"lists/{official_route_id}/")
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
            local = common.list_payload(row)
            common.emit_structured_activity(
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
        local = common.list_payload(row)
        common.emit_structured_activity(
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


@v1_write_bp.route("/v1/write/lists/", methods=["POST"])
@write_guard
def write_list_create() -> Response:
    """Official-first lifecycle for creating a list."""
    return _write_list_core()


@v1_write_bp.route("/v1/write/lists/<list_id>/", methods=["PUT", "DELETE"])
@write_guard
def write_list_update(list_id: str) -> Response:
    """Official-first lifecycle for updating or deleting a list."""
    official_id = clean_int(list_id)
    if official_id is None:
        return common.bad("official list id must be numeric")
    if request.method == "PUT":
        return _write_list_core(list_id)
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", common.upstream_path(f"lists/{official_id}/"), None)
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
        common.emit_structured_activity(
            s,
            user,
            action="list-deleted",
            object_type="list",
            object_key=str(official_id),
            official_status=SYNC_OFFICIAL,
            payload={"toolhub": attempt["toolhub"], "syncStatus": SYNC_OFFICIAL},
        )
    return _official_success_response(attempt)


@v1_write_bp.route("/v1/write/user/favorites/", methods=["POST"])
@write_guard
def write_favorite_add() -> Response:
    """Official-first lifecycle for adding a favorite."""
    value, err = common.json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    name = common.clean_name(str(value.get("name") or ""))
    if name is None:
        return common.bad("favorite needs a tool name")
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "POST", "/api/user/favorites/", {"name": name})
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            _upsert_favorite(s, user, name, sync_status=SYNC_OFFICIAL)
            common.emit_structured_activity(
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
        common.emit_structured_activity(
            s,
            user,
            action="favorited",
            object_type="favorite",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/user/favorites/<tool_name>/", methods=["DELETE"])
@write_guard
def write_favorite_delete(tool_name: str) -> Response:
    """Official-first lifecycle for removing a favorite."""
    name = common.clean_name(tool_name)
    if name is None:
        return common.bad("favorite needs a tool name")
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", common.upstream_path(f"user/favorites/{name}/"), None)
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            s.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name))
            common.emit_structured_activity(
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
        common.emit_structured_activity(
            s,
            user,
            action="favorite-removed",
            object_type="favorite",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/crawler/urls/", methods=["POST"])
@write_guard
def write_crawler_url_add() -> Response:
    """Official-first lifecycle for crawler URL registration."""
    value, err = common.json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    raw_url = value.get("url")
    error = common.url_validation_message(raw_url, label="crawler URL")
    if error is not None:
        return common.url_validation_bad("url", error)
    url = str(raw_url).strip()
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
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
            local = common.crawler_url_payload(row)
            common.emit_structured_activity(
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
        local = common.crawler_url_payload(row)
        common.emit_structured_activity(
            s,
            user,
            action="crawler-url-added",
            object_type="crawler_url",
            object_key=url,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/crawler/urls/<int:url_id>/", methods=["DELETE"])
@write_guard
def write_crawler_url_delete(url_id: int) -> Response:
    """Official-first lifecycle for crawler URL removal."""
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    attempt, denied = _attempt_official_write(user, "DELETE", common.upstream_path(f"crawler/urls/{url_id}/"), None)
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
        common.emit_structured_activity(
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
    if kind not in v1.TOOL_FALLBACK_KINDS:
        return None, common.bad("kind must be new, edit, or annotations")
    return str(kind), None


def _discard_response() -> Response:
    return jsonify({"ok": True, "result": v1.OFFICIAL_STATUS_DISCARDED})


@v1_write_bp.route("/v1/write/tools/<name>/retry/", methods=["POST"])
@write_guard
def write_tool_retry(name: str) -> Response:  # noqa: PLR0911 - retry exits mirror validation/not found/sync outcomes
    """Retry publishing one Evolved-local tool fallback."""
    clean_name = common.clean_name(name)
    kind, err = _tool_fallback_kind()
    if clean_name is None:
        return common.bad("tool name is required")
    if err is not None:
        return err
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
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
                return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
            fields = row.record if isinstance(row.record, dict) else {}
            method, path, official_payload = (
                "POST",
                "/api/tools/",
                _official_tool_payload(clean_name, fields, include_name=True),
            )
        else:
            overlay_kind = v1.TOOL_OVERLAY_KIND_BY_FALLBACK[kind]
            row = s.execute(
                select(ToolOverlay).where(
                    ToolOverlay.kind == overlay_kind,
                    ToolOverlay.tool_name == clean_name,
                    ToolOverlay.user_id == user.id,
                    ToolOverlay.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
            fields = row.patch if isinstance(row.patch, dict) else {}
            method = "PUT"
            fragment = f"tools/{clean_name}/annotations/" if kind == "annotations" else f"tools/{clean_name}/"
            path = common.upstream_path(fragment)
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
                        ToolOverlay.kind == v1.TOOL_OVERLAY_KIND_BY_FALLBACK[kind],
                        ToolOverlay.tool_name == clean_name,
                        ToolOverlay.user_id == user.id,
                    )
                )
            common.emit_structured_activity(
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
                v1.TOOL_OVERLAY_KIND_BY_FALLBACK[kind],
                fields,
                attempt,
            )
        common.emit_structured_activity(
            s,
            user,
            action="retry-failed",
            object_type="tool",
            object_key=clean_name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/tools/<name>/fallback/", methods=["DELETE"])
@write_guard
def write_tool_fallback_discard(name: str) -> Response:
    """Discard one Evolved-local tool fallback."""
    clean_name = common.clean_name(name)
    kind, err = _tool_fallback_kind()
    if clean_name is None:
        return common.bad("tool name is required")
    if err is not None:
        return err
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    assert kind is not None  # noqa: S101 - err covers invalid kinds
    with db.session_scope() as s:
        if kind == "new":
            result = s.execute(
                delete(ToolRecord).where(ToolRecord.tool_name == clean_name, ToolRecord.user_id == user.id)
            )
        else:
            result = s.execute(
                delete(ToolOverlay).where(
                    ToolOverlay.kind == v1.TOOL_OVERLAY_KIND_BY_FALLBACK[kind],
                    ToolOverlay.tool_name == clean_name,
                    ToolOverlay.user_id == user.id,
                )
            )
        if result.rowcount == 0:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        common.emit_structured_activity(
            s,
            user,
            action="discarded",
            object_type="tool",
            object_key=clean_name,
            official_status=v1.OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": v1.OFFICIAL_STATUS_DISCARDED},
        )
    return _discard_response()


@v1_write_bp.route("/v1/write/lists/<client_id>/retry/", methods=["POST"])
@write_guard
def write_list_retry(client_id: str) -> Response:
    """Retry publishing one local list fallback."""
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        row = s.execute(
            select(ToolList).where(
                ToolList.client_id == client_id,
                ToolList.user_id == user.id,
                ToolList.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        if not authz.can(user, authz.ACTION_PRIVATE_WRITE, row):
            return common.deny(common.HTTP_FORBIDDEN, "not allowed")
        fields = {
            "client_id": row.client_id,
            "title": row.title,
            "description": row.description,
            "tools": row.tools if isinstance(row.tools, list) else [],
        }
        official_id = row.official_list_id
    method = "PUT" if official_id is not None else "POST"
    path = common.upstream_path(f"lists/{official_id}/") if official_id is not None else "/api/lists/"
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
            local = common.list_payload(row)
            common.emit_structured_activity(
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
        local = common.list_payload(row)
        common.emit_structured_activity(
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


@v1_write_bp.route("/v1/write/lists/<client_id>/fallback/", methods=["DELETE"])
@write_guard
def write_list_fallback_discard(client_id: str) -> Response:
    """Discard one local list fallback."""
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    with db.session_scope() as s:
        row = s.execute(
            select(ToolList).where(
                ToolList.client_id == client_id,
                ToolList.user_id == user.id,
                ToolList.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        row.deleted_at = utcnow()
        common.emit_structured_activity(
            s,
            user,
            action="list-discarded",
            object_type="list",
            object_key=client_id,
            official_status=v1.OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": v1.OFFICIAL_STATUS_DISCARDED},
            title=row.title,
        )
    return _discard_response()


@v1_write_bp.route("/v1/write/crawler/urls/<int:local_id>/retry/", methods=["POST"])
@write_guard
def write_crawler_url_retry(local_id: int) -> Response:
    """Retry publishing one crawler URL fallback."""
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        row = s.execute(
            select(CrawlerUrl).where(
                CrawlerUrl.id == local_id,
                CrawlerUrl.user_id == user.id,
                CrawlerUrl.enabled.is_(True),
            )
        ).scalar_one_or_none()
        if row is None:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        if not authz.can(user, authz.ACTION_PRIVATE_WRITE, row):
            return common.deny(common.HTTP_FORBIDDEN, "not allowed")
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
            local = common.crawler_url_payload(row)
            common.emit_structured_activity(
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
        local = common.crawler_url_payload(row)
        common.emit_structured_activity(
            s,
            user,
            action="crawler-url-retry-failed",
            object_type="crawler_url",
            object_key=url,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/crawler/urls/<int:local_id>/fallback/", methods=["DELETE"])
@write_guard
def write_crawler_url_fallback_discard(local_id: int) -> Response:
    """Discard one local crawler URL fallback."""
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    with db.session_scope() as s:
        result = s.execute(delete(CrawlerUrl).where(CrawlerUrl.id == local_id, CrawlerUrl.user_id == user.id))
        if result.rowcount == 0:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        common.emit_structured_activity(
            s,
            user,
            action="crawler-url-discarded",
            object_type="crawler_url",
            object_key=str(local_id),
            official_status=v1.OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": v1.OFFICIAL_STATUS_DISCARDED},
        )
    return _discard_response()


@v1_write_bp.route("/v1/write/user/favorites/<tool_name>/retry/", methods=["POST"])
@write_guard
def write_favorite_retry(tool_name: str) -> Response:
    """Retry publishing one favorite fallback."""
    name = common.clean_name(tool_name)
    if name is None:
        return common.bad("favorite needs a tool name")
    user = common.require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    with db.session_scope() as s:
        row = s.execute(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name)
        ).scalar_one_or_none()
        if row is None:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        if not authz.can(user, authz.ACTION_PRIVATE_WRITE, row):
            return common.deny(common.HTTP_FORBIDDEN, "not allowed")
    attempt, denied = _attempt_official_write(user, "POST", "/api/user/favorites/", {"name": name})
    if denied is not None:
        return denied
    if attempt["ok"]:
        with db.session_scope() as s:
            _upsert_favorite(s, user, name, sync_status=SYNC_OFFICIAL)
            common.emit_structured_activity(
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
        common.emit_structured_activity(
            s,
            user,
            action="favorite-retry-failed",
            object_type="favorite",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload={"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
        )
    return _local_fallback_response(attempt, local)


@v1_write_bp.route("/v1/write/user/favorites/<tool_name>/fallback/", methods=["DELETE"])
@write_guard
def write_favorite_fallback_discard(tool_name: str) -> Response:
    """Discard one favorite fallback."""
    name = common.clean_name(tool_name)
    if name is None:
        return common.bad("favorite needs a tool name")
    user = common.require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=current_user_id()))
    with db.session_scope() as s:
        result = s.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.tool_name == name))
        if result.rowcount == 0:
            return common.deny(common.HTTP_NOT_FOUND, "fallback record not found")
        common.emit_structured_activity(
            s,
            user,
            action="favorite-discarded",
            object_type="favorite",
            object_key=name,
            official_status=v1.OFFICIAL_STATUS_DISCARDED,
            payload={"syncStatus": v1.OFFICIAL_STATUS_DISCARDED},
        )
    return _discard_response()
