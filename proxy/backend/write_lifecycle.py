# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable official-first write transport and response policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from flask import Response, jsonify

from backend import db, toolhub
from backend import v1_common as common
from backend.models import User, utcnow
from backend.sync import SYNC_LOCAL_FALLBACK, SYNC_OFFICIAL

if TYPE_CHECKING:
    from collections.abc import Callable

HTTP_NO_CONTENT = 204


@dataclass(frozen=True)
class WriteHandlers:
    """Resource callbacks for the shared official-first lifecycle."""

    on_success: Callable[[Any, User, dict], dict | None]
    on_fallback: Callable[[Any, User, dict], dict]
    can_fallback: Callable[[User], bool]


@dataclass(frozen=True)
class WriteRequest:
    """Immutable transport request passed through the lifecycle policy."""

    user: User
    method: str
    path: str
    payload: object | None


def execute_official_first(
    request: WriteRequest,
    handlers: WriteHandlers,
    *,
    database: Any = db,  # noqa: ANN401 - injectable database facade
    attempt_writer: Callable[[User, str, str, object | None], tuple[dict, Response | None]] | None = None,
) -> Response:
    """Run one official write and delegate resource-specific persistence.

    The transport owns authentication/error normalization and this function owns
    the branch that every resource otherwise had to repeat: persist official
    success, reject when local fallback is not permitted, or persist a local
    fallback and return the shared response contract.
    """
    writer = attempt_writer or attempt_official_write
    attempt, denied = writer(request.user, request.method, request.path, request.payload)
    if denied is not None:
        return denied
    if attempt["ok"]:
        with database.session_scope() as session:
            local = handlers.on_success(session, request.user, attempt)
        return official_success_response(attempt, local)
    if not handlers.can_fallback(request.user):
        return official_failure_response(attempt)
    with database.session_scope() as session:
        local = handlers.on_fallback(session, request.user, attempt)
    return local_fallback_response(attempt, local)


def message_from_payload(payload: object, default: str) -> str:
    """Extract the clearest bounded user-facing message from an error payload."""
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[: common.MAX_DESCRIPTION]
    return default


def validation_errors(payload: object) -> list:
    """Normalize common Toolhub validation payloads for the write UI."""
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


def failure_payload(status: int, payload: object, default_message: str) -> dict:
    """Build the normalized failure contract shared by every write resource."""
    details = payload if isinstance(payload, dict) else {"message": str(payload)}
    return {
        "ok": False,
        "status": status,
        "details": details,
        "lastError": message_from_payload(details, default_message),
        "validationErrors": validation_errors(details),
    }


def attempt_official_write(
    user: User,
    method: str,
    path: str,
    payload: object | None,
) -> tuple[dict, Response | None]:
    """Call Toolhub with the user's grant; auth failures remain non-fallback."""
    try:
        body, status = toolhub.api_request(user.id, method, path, json=payload)
    except ValueError:
        # A path rejected before the request leaves the process is a denial, not
        # an upstream outage that should become a local draft.
        return {}, common.bad("invalid official Toolhub path")
    except toolhub.ToolhubAuthError as exc:
        resp = jsonify({"error": str(exc), "reauth": True})
        resp.status_code = common.HTTP_UNAUTHORIZED
        return {}, resp
    except toolhub.ToolhubAPIError as exc:
        return failure_payload(exc.status_code, exc.payload, "official Toolhub rejected the write"), None
    except toolhub.requests.RequestException:
        return (
            failure_payload(
                common.HTTP_BAD_GATEWAY,
                {"message": "official Toolhub is unavailable"},
                "official Toolhub is unavailable",
            ),
            None,
        )
    common.invalidate_official_api_cache(path, payload, body)
    common.record_successful_toolhub_write(user, method, path, payload, body)
    return {
        "ok": True,
        "status": status,
        "toolhub": body if status != HTTP_NO_CONTENT else {"ok": True},
        "lastSyncedAt": common.iso(utcnow()),
    }, None


def official_success_response(attempt: dict, local: dict | None = None) -> Response:
    """Render the stable response for a completed official write."""
    payload: dict[str, Any] = {
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
    resp.status_code = 200 if attempt["status"] == HTTP_NO_CONTENT else int(attempt["status"])
    return resp


def official_failure_response(failure: dict) -> Response:
    """Render an upstream rejection without offering a local fallback."""
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


def local_fallback_response(failure: dict, local: dict) -> Response:
    """Render the accepted local-fallback contract for an upstream failure."""
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
