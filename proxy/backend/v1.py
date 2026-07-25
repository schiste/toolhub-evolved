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

from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, Response, jsonify, request, session
from sqlalchemy import delete, func, select, text

from backend import db
from backend.models import ActivityRow, CrawlerUrl, Favorite, ToolList, ToolOverlay, ToolRecord, User, utcnow
from backend.oauth import configured as oauth_configured
from backend.security import current_user_id, login_required, write_guard

v1_bp = Blueprint("v1", __name__)

HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
MAX_ITEMS = 500  # per overlay key per user
MAX_NAME = 255
FEED_READ_CAP = 100
FEED_KEEP_CAP = 500
OVERLAY_KINDS = {"toolEdits": "edits", "toolAnnos": "annos"}
FEED_KEYS = ("revisions", "auditlogs")


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


def _bad(error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = HTTP_BAD_REQUEST
    return resp


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
        resp = jsonify({"authenticated": False})
        resp.status_code = 401
        return resp
    with db.session_scope() as s:
        user = s.get(User, uid)
        if user is None:  # stale cookie for a deleted account
            session.clear()
            resp = jsonify({"authenticated": False})
            resp.status_code = 401
            return resp
        return jsonify({"authenticated": True, "username": user.username, "csrf": session.get("csrf", "")})


@v1_bp.route("/v1/config/")
def v1_config() -> Response:
    """Report which production capabilities are configured (no secrets)."""
    return jsonify({"oauth": oauth_configured()})


def _merged_maps(kind_rows: list[Any]) -> dict[str, dict]:
    """Merge rows (any user) into {tool_name: payload}.

    Rows arrive oldest first, so the most recently modified contribution wins
    each name.
    """
    out: dict[str, dict] = {}
    for row in kind_rows:
        out[row.tool_name] = row.patch if isinstance(row, ToolOverlay) else row.record
    return out


def _assemble_overlay(uid: int) -> dict[str, Any]:
    with db.session_scope() as s:
        favorites = [
            f.tool_name
            for f in s.execute(select(Favorite).where(Favorite.user_id == uid).order_by(Favorite.position)).scalars()
        ]
        lists = [
            {
                "id": row.client_id,
                "title": row.title,
                "description": row.description,
                "tools": row.tools,
                "created": _iso(row.created_at),
                "modified": _iso(row.modified_at),
            }
            for row in s.execute(
                select(ToolList).where(ToolList.user_id == uid).order_by(ToolList.created_at.desc())
            ).scalars()
        ]
        crawler_urls = [
            {"url": c.url, "added": _iso(c.added_at)}
            for c in s.execute(
                select(CrawlerUrl).where(CrawlerUrl.user_id == uid).order_by(CrawlerUrl.added_at.desc())
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
        tool_new = _merged_maps(list(s.execute(select(ToolRecord).order_by(ToolRecord.modified_at)).scalars()))
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
    return jsonify(_assemble_overlay(uid))


def _put_favorites(uid: int, value: Any) -> Response | None:  # noqa: ANN401
    if not isinstance(value, list) or not all(isinstance(n, str) and 0 < len(n) <= MAX_NAME for n in value):
        return _bad("favorites must be a list of tool names")
    names = list(dict.fromkeys(value))[:MAX_ITEMS]
    with db.session_scope() as s:
        s.execute(delete(Favorite).where(Favorite.user_id == uid))
        s.add_all([Favorite(user_id=uid, tool_name=n, position=i) for i, n in enumerate(names)])
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
            s.add(
                ToolList(
                    client_id=str(item["id"])[:64],
                    user_id=uid,
                    title=str(item["title"])[:MAX_NAME],
                    description=str(item.get("description", "")),
                    tools=[str(t)[:MAX_NAME] for t in item["tools"][:MAX_ITEMS]],
                    created_at=_parse_iso(item.get("created")),
                    modified_at=_parse_iso(item.get("modified")),
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
        s.add_all(
            [
                CrawlerUrl(user_id=uid, url=str(u["url"])[:2000], added_at=_parse_iso(u.get("added")))
                for u in value[:MAX_ITEMS]
            ]
        )
    return None


def _valid_map(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, dict) and all(
        isinstance(k, str) and 0 < len(k) <= MAX_NAME and isinstance(v, dict) for k, v in value.items()
    )


def _put_tool_map(uid: int, value: Any, *, key: str) -> Response | None:  # noqa: ANN401
    if not _valid_map(value):
        return _bad(f"{key} must be a map of tool name to object")
    entries = dict(list(value.items())[:MAX_ITEMS])
    with db.session_scope() as s:
        if key == "toolNew":
            s.execute(delete(ToolRecord).where(ToolRecord.user_id == uid))
            s.add_all(
                [ToolRecord(tool_name=n, user_id=uid, record=rec, modified_at=utcnow()) for n, rec in entries.items()]
            )
        else:
            kind = OVERLAY_KINDS[key]
            s.execute(delete(ToolOverlay).where(ToolOverlay.user_id == uid, ToolOverlay.kind == kind))
            s.add_all(
                [
                    ToolOverlay(kind=kind, tool_name=n, user_id=uid, patch=patch, modified_at=utcnow())
                    for n, patch in entries.items()
                ]
            )
    return None


def _put_feed(uid: int, value: Any, *, key: str) -> Response | None:  # noqa: ANN401
    ok = isinstance(value, list) and all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in value)
    if not ok:
        return _bad(f"{key} must be a list of rows with string ids")
    with db.session_scope() as s:
        known = set(
            s.execute(
                select(ActivityRow.client_id).where(ActivityRow.kind == key, ActivityRow.user_id == uid)
            ).scalars()
        )
        for row in value[:MAX_ITEMS]:
            if row["id"] not in known:
                s.add(
                    ActivityRow(
                        kind=key,
                        client_id=str(row["id"])[:64],
                        user_id=uid,
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
        err = _put_tool_map(uid, value, key=key)
    elif key in FEED_KEYS:
        err = _put_feed(uid, value, key=key)
    else:
        resp = jsonify({"error": "unknown overlay key"})
        resp.status_code = HTTP_NOT_FOUND
        return resp
    return err if err is not None else jsonify({"ok": True})


@v1_bp.route("/v1/search/tools/")
def v1_search() -> Response:
    """Search locally-registered tools (public).

    Federated with live search client-side; upstream results always come
    straight from the Toolhub API.
    """
    q = request.args.get("q", "").strip().lower()
    with db.session_scope() as s:
        merged = _merged_maps(list(s.execute(select(ToolRecord).order_by(ToolRecord.modified_at)).scalars()))
    results = [
        {"name": name, **rec}
        for name, rec in merged.items()
        if not q
        or any(q in str(rec.get(f, "")).lower() for f in ("title", "description"))
        or q in name.lower()
        or any(q in str(k).lower() for k in rec.get("keywords", []))
    ]
    return jsonify({"count": len(results), "results": results})


@v1_bp.route("/toolinfo.json")
def toolinfo_feed() -> Response:
    """Serve the public toolinfo feed of locally-registered tools.

    The official Toolhub crawler can ingest this feed (docs/PRODUCTION.md
    §1.3 — we feed the ecosystem instead of forking it).
    """
    with db.session_scope() as s:
        merged = _merged_maps(list(s.execute(select(ToolRecord).order_by(ToolRecord.modified_at)).scalars()))
    feed = [
        {
            "name": f"toolhub-evolved-{name}",
            "title": rec.get("title", name),
            "description": rec.get("description", ""),
            "url": rec.get("url", ""),
            "keywords": ",".join(rec.get("keywords", [])),
            "repository": rec.get("repository") or None,
            "license": rec.get("license") or None,
            "tool_type": rec.get("toolType") or None,
            "for_wikis": rec.get("forWikis", []),
            "$schema": "/toolinfo/1.2.2",
        }
        for name, rec in merged.items()
        if rec.get("url", "").startswith("https://")
    ]
    return jsonify(feed)
