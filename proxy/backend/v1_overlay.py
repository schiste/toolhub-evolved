# SPDX-License-Identifier: GPL-3.0-or-later
"""The /v1/overlay/* endpoints, split out of backend/v1.py.

URL paths are unchanged; only the Flask endpoint names move under their
own blueprint. Helpers still shared with other families are reached as
`v1.<name>` so there is exactly one binding for each and patching or
reloading backend.v1 keeps working.
"""

from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import delete, func, select

from backend import (
    authz,
    db,
    v1,
)
from backend.models import (
    ActivityRow,
    CrawlerUrl,
    Favorite,
    ToolList,
    ToolOverlay,
    ToolRecord,
    User,
    utcnow,
)
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    REVIEW_OPEN,
    REVIEW_PENDING,
    SOURCE_LOCAL,
    SOURCE_OFFICIAL,
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

v1_overlay_bp = Blueprint("v1_overlay", __name__)


def _visibility(value: Any, default: str = v1.VISIBILITY_PRIVATE) -> str:  # noqa: ANN401
    return value if value in {v1.VISIBILITY_PRIVATE, v1.VISIBILITY_PUBLIC} else default


@v1_overlay_bp.route("/v1/overlay/")
@login_required
def v1_overlay_get() -> Response:
    """Return the full overlay in the SPA's localStorage shapes (one pull at sign-in)."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    v1._require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    return jsonify(v1._assemble_overlay(uid))


def _put_favorites(uid: int, value: Any) -> Response | None:  # noqa: ANN401
    if not isinstance(value, list) or not all(isinstance(n, str) and 0 < len(n) <= v1.MAX_NAME for n in value):
        return v1._bad("favorites must be a list of tool names")
    names = list(dict.fromkeys(value))[: v1.MAX_ITEMS]
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
        return v1._bad("lists must be a list")
    for item in value[: v1.MAX_ITEMS]:
        ok = (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("title"), str)
            and isinstance(item.get("tools"), list)
        )
        if not ok:
            return v1._bad("each list needs id, title and tools")
    with db.session_scope() as s:
        s.execute(delete(ToolList).where(ToolList.user_id == uid))
        for item in value[: v1.MAX_ITEMS]:
            official_id = clean_int(v1._payload_value(item, "officialId", "official_list_id"))
            default_status = SYNC_OFFICIAL if official_id is not None else SYNC_LOCAL_DRAFT
            sync_status = clean_sync_status(v1._payload_value(item, "syncStatus", "sync_status"), default_status)
            last_synced_at = v1._parse_optional_iso(v1._payload_value(item, "lastSyncedAt", "last_synced_at"))
            if sync_status == SYNC_OFFICIAL and last_synced_at is None:
                last_synced_at = v1._parse_iso(item.get("modified"))
            response = v1._payload_value(item, "toolhubResponse", "last_toolhub_response")
            validation_errors = v1._payload_value(item, "validationErrors", "validation_errors")
            s.add(
                ToolList(
                    client_id=str(item["id"])[:64],
                    user_id=uid,
                    created_by_user_id=uid,
                    title=str(item["title"])[: v1.MAX_NAME],
                    description=str(item.get("description", "")),
                    tools=[str(t)[: v1.MAX_NAME] for t in item["tools"][: v1.MAX_ITEMS]],
                    created_at=v1._parse_iso(item.get("created")),
                    modified_at=v1._parse_iso(item.get("modified")),
                    official_list_id=official_id,
                    source=clean_source(
                        v1._payload_value(item, "source"),
                        SOURCE_OFFICIAL if official_id else SOURCE_LOCAL,
                    ),
                    sync_status=sync_status,
                    last_synced_at=last_synced_at,
                    last_error=clean_error(v1._payload_value(item, "lastError", "last_error")),
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
        return v1._bad("crawlerUrls must be a list of {url (https), added}")
    with db.session_scope() as s:
        s.execute(delete(CrawlerUrl).where(CrawlerUrl.user_id == uid))
        for u in value[: v1.MAX_ITEMS]:
            official_id = clean_int(v1._payload_value(u, "officialId") if "officialId" in u else u.get("id"))
            default_status = SYNC_OFFICIAL if official_id is not None else SYNC_LOCAL_DRAFT
            sync_status = clean_sync_status(v1._payload_value(u, "syncStatus", "sync_status"), default_status)
            last_synced_at = v1._parse_optional_iso(v1._payload_value(u, "lastSyncedAt", "last_synced_at"))
            if sync_status == SYNC_OFFICIAL and last_synced_at is None:
                last_synced_at = v1._parse_iso(u.get("added"))
            response = v1._payload_value(u, "toolhubResponse", "last_toolhub_response")
            validation_errors = v1._payload_value(u, "validationErrors", "validation_errors")
            s.add(
                CrawlerUrl(
                    user_id=uid,
                    created_by_user_id=uid,
                    url=str(u["url"])[:2000],
                    added_at=v1._parse_iso(u.get("added")),
                    official_crawler_url_id=official_id,
                    source=clean_source(
                        v1._payload_value(u, "source"), SOURCE_OFFICIAL if official_id else SOURCE_LOCAL
                    ),
                    enabled=bool(u.get("enabled", True)),
                    last_checked_at=v1._parse_optional_iso(v1._payload_value(u, "lastCheckedAt", "last_checked_at")),
                    last_status=str(v1._payload_value(u, "lastStatus", "last_status") or "")[:64] or None,
                    last_error=clean_error(v1._payload_value(u, "lastError", "last_error")),
                    last_toolhub_response=response if isinstance(response, dict) else None,
                    validation_errors=validation_errors if isinstance(validation_errors, list) else None,
                    sync_status=sync_status,
                    last_synced_at=last_synced_at,
                )
            )
    return None


def _valid_map(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, dict) and all(
        isinstance(k, str) and 0 < len(k) <= v1.MAX_NAME and isinstance(v, dict) for k, v in value.items()
    )


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
        v1._payload_value(rec, "visibility"), v1.VISIBILITY_PUBLIC if is_crawler_record else v1.VISIBILITY_PRIVATE
    )
    preserved_review = clean_review_status(existing_review_status, REVIEW_PENDING)
    if can_review:
        review_status = clean_review_status(v1._payload_value(rec, "reviewStatus", "review_status"), preserved_review)
    elif visibility == v1.VISIBILITY_PUBLIC and not record_changed:
        review_status = preserved_review
    else:
        review_status = REVIEW_PENDING
    default_status = SYNC_EVOLVED_REAL if visibility == v1.VISIBILITY_PUBLIC else SYNC_LOCAL_DRAFT
    status = clean_sync_status(v1._payload_value(rec, "syncStatus", "sync_status"), default_status)
    official_name = v1._payload_value(rec, "officialName", "official_name")
    response = v1._payload_value(rec, "toolhubResponse", "last_toolhub_response")
    validation_errors = v1._payload_value(rec, "validationErrors", "validation_errors")
    return {
        "visibility": visibility,
        "source": SOURCE_LOCAL,
        "sync_status": status,
        "review_status": review_status,
        "last_synced_at": v1._parse_optional_iso(v1._payload_value(rec, "lastSyncedAt", "last_synced_at")),
        "last_error": clean_error(v1._payload_value(rec, "lastError", "last_error")),
        "official_name": str(official_name)[: v1.MAX_NAME]
        if isinstance(official_name, str) and official_name
        else None,
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
    field_statuses = v1._payload_value(patch, "fieldStatuses", "field_statuses")
    response = v1._payload_value(patch, "toolhubResponse", "last_toolhub_response")
    validation_errors = v1._payload_value(patch, "validationErrors", "validation_errors")
    preserved_review = clean_review_status(existing_review_status, REVIEW_OPEN)
    return {
        "base_revision": str(v1._payload_value(patch, "baseRevision", "base_revision") or "")[: v1.MAX_NAME] or None,
        "field_statuses": field_statuses if isinstance(field_statuses, dict) else None,
        "source": clean_source(v1._payload_value(patch, "source"), SOURCE_LOCAL),
        "sync_status": clean_sync_status(
            v1._payload_value(patch, "syncStatus", "sync_status"),
            SYNC_LOCAL_FALLBACK if v1._payload_value(patch, "lastError", "last_error") else SYNC_LOCAL_DRAFT,
        ),
        "last_synced_at": v1._parse_optional_iso(v1._payload_value(patch, "lastSyncedAt", "last_synced_at")),
        "last_error": clean_error(v1._payload_value(patch, "lastError", "last_error")),
        "last_toolhub_response": response if isinstance(response, dict) else None,
        "validation_errors": validation_errors if isinstance(validation_errors, list) else None,
        "review_status": (
            clean_review_status(v1._payload_value(patch, "reviewStatus", "review_status"), preserved_review)
            if can_review
            else preserved_review
        ),
    }


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
        clean = v1._clean_tool_record(rec)
        if clean is None:
            return v1._bad(f"toolNew record '{name}' needs title, description and an https url")
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
        return v1._bad(f"{key} must be a map of tool name to object")
    entries = dict(list(value.items())[: v1.MAX_ITEMS])
    with db.session_scope() as s:
        can_review = authz.can(user, authz.ACTION_PUBLIC_REVIEW)
        if key == "toolNew":
            return _put_tool_new(uid, entries, s, can_review=can_review)
        kind = v1.OVERLAY_KINDS[key]
        # Echo suppression: entries identical to another user's current overlay
        # came in via the merged pull — replaying them must not create a copy
        # owned by the caller. Only genuinely new/changed patches are theirs.
        others = {
            r.tool_name: r.patch
            for r in s.execute(
                select(ToolOverlay).where(ToolOverlay.kind == kind, ToolOverlay.user_id != uid)
            ).scalars()
        }
        own = {n: patch for n, patch in entries.items() if others.get(n) != v1._data_patch(patch)}
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
                    patch=v1._data_patch(patch),
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
        return v1._bad(f"{key} must be a list of rows with string ids")
    with db.session_scope() as s:
        # Dedupe globally, not per user: pulled feeds are global, so clients
        # push other users' rows back — those must not be duplicated under the
        # caller's account.
        known = set(s.execute(select(ActivityRow.client_id).where(ActivityRow.kind == key)).scalars())
        for row in value[: v1.MAX_ITEMS]:
            if row["id"] not in known:
                known.add(row["id"])  # a payload may repeat an id — insert once
                s.add(
                    ActivityRow(
                        kind=key,
                        client_id=str(row["id"])[:64],
                        user_id=uid,
                        created_by_user_id=uid,
                        row=row,
                        created_at=v1._parse_iso(row.get("timestamp")),
                    )
                )
        total = s.execute(select(func.count()).select_from(ActivityRow).where(ActivityRow.kind == key)).scalar_one()
        if total > v1.FEED_KEEP_CAP:
            # Fetch victim ids first: MariaDB rejects LIMIT inside IN-subqueries.
            oldest_ids = list(
                s.execute(
                    select(ActivityRow.id)
                    .where(ActivityRow.kind == key)
                    .order_by(ActivityRow.created_at, ActivityRow.id)
                    .limit(total - v1.FEED_KEEP_CAP)
                ).scalars()
            )
            s.execute(delete(ActivityRow).where(ActivityRow.id.in_(oldest_ids)))
    return None


@v1_overlay_bp.route("/v1/overlay/<key>", methods=["PUT"])
@write_guard
def v1_overlay_put(key: str) -> Response:
    """Write-through target for one localStorage overlay key."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = v1._require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    value = request.get_json(silent=True)
    if value is None:
        return v1._bad("body must be JSON")
    if key == "favorites":
        err = _put_favorites(uid, value)
    elif key == "lists":
        err = _put_lists(uid, value)
    elif key == "crawlerUrls":
        err = _put_crawler_urls(uid, value)
    elif key in v1.OVERLAY_KINDS or key == "toolNew":
        err = _put_tool_map(uid, value, key=key, user=user)
    elif key in v1.FEED_KEYS:
        err = _put_feed(uid, value, key=key)
    else:
        resp = jsonify({"error": "unknown overlay key"})
        resp.status_code = v1.HTTP_NOT_FOUND
        return resp
    return err if err is not None else jsonify({"ok": True})
