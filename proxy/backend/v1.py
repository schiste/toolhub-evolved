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

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, abort, jsonify, request, session
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from backend import (
    activity_privacy,
    api_cache,
    authz,
    canonical_tools,
    db,
    github_issues,
    graph_payload,
    home_payload,
    maintainer_index,
    people_index,
    recent_owners,
    security,
    tool_summaries,
    toolhub,
)
from backend.author_claims import (
    AuthorNameProvider,
    SignedToolinfoProvider,
    ToolforgeMaintainerProvider,
    ToolforgeMembershipProvider,
    ToolhubWriteProvider,
    public_key_fingerprint,
    record_author_claim,
)
from backend.author_claims import (
    claim_payload as author_claim_payload,
)
from backend.models import (
    ActivityRow,
    CatalogCuration,
    CrawlerUrl,
    Favorite,
    IssueReport,
    Person,
    PersonProfile,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolHealthTarget,
    ToolinfoControlChallenge,
    ToolList,
    ToolMedia,
    ToolOverlay,
    ToolPersonRelationship,
    ToolRecord,
    ToolThanks,
    User,
    utcnow,
)
from backend.oauth import configured as oauth_configured
from backend.oauth import dev_login_available
from backend.security import current_user_id, login_required, write_guard
from backend.sync import (
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_VERIFIED,
    REVIEW_APPROVED,
    REVIEW_OPEN,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    SOURCE_LOCAL,
    SYNC_ERROR,
    SYNC_EVOLVED_REAL,
    SYNC_LOCAL_DRAFT,
    SYNC_LOCAL_FALLBACK,
    SYNC_OFFICIAL,
    clean_error,
    clean_int,
    clean_review_status,
)
from backend.toolinfo_control import (
    CHALLENGE_FIELD,
    CHALLENGE_STATUS_EXPIRED,
    CHALLENGE_STATUS_PENDING,
    CHALLENGE_STATUS_VERIFIED,
    CHALLENGE_TTL,
    CONTROL_CLAIM_TTL,
    fetch_matching_item,
    new_token,
)
from backend.toolinfo_control import (
    expired as challenge_expired,
)

v1_bp = Blueprint("v1", __name__)

HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_NO_CONTENT = 204
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_CONFLICT = 409
HTTP_BAD_GATEWAY = 502
HTTP_TOO_MANY = 429
UPSTREAM_KIND_INDEX = 1
UPSTREAM_MIN_PARTS = 2
UPSTREAM_OBJECT_INDEX = 2
UPSTREAM_OBJECT_PARTS = 3
MAX_ITEMS = 500  # per overlay key per user
MAX_NAME = 255
FEED_READ_CAP = 100
FEED_KEEP_CAP = 500
RSS_FEED_PAGE_SIZE = 30
RSS_CONTENT_TYPE = "application/rss+xml; charset=utf-8"
# Last-resort base URL for links inside publicly cached responses when
# TOOLHUB_EVOLVED_BASE_URL is unset. A constant, never the request Host — see
# _public_base_url for why that distinction is the whole point.
DEFAULT_PUBLIC_BASE_URL = "https://toolhub-evolved.toolforge.org"
ME_TOOLS_SEARCH_PAGE_SIZE = 100
ME_TOOLS_MAX_SEARCH_TERMS = 20
AUTHOR_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SIGNATURE_PLACEHOLDER = "<base64 signature>"
OVERLAY_KINDS = {"toolEdits": "edits", "toolAnnos": "annos"}
FEED_KEYS = ("revisions", "auditlogs")
VISIBILITY_PRIVATE = "private"
VISIBILITY_PUBLIC = "public"
EVENT_TYPES = {"view", "launch", "save", "list_add"}
CLAIM_METHODS = {
    AUTHOR_CLAIM_AUTHOR_DISPLAY_NAME,
    AUTHOR_CLAIM_TOOLFORGE_MAINTAINER,
    AUTHOR_CLAIM_SIGNED_TOOLINFO,
    AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
    AUTHOR_CLAIM_TOOLHUB_WRITE_ACCESS,
}
MODERATION_MODELS = {
    "catalog-curations": CatalogCuration,
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
    "viewerOwned",
    "baseRevision",
    "fieldStatuses",
    "reviewStatus",
}
CANONICAL_TOOL_KEYS = {"name", "origin"}
TOOL_FALLBACK_KINDS = {"new", "edit", "annotations"}
TOOL_OVERLAY_KIND_BY_FALLBACK = {"edit": "edits", "annotations": "annos"}
OFFICIAL_STATUS_DISCARDED = "discarded"
AUTHOR_NAME_PROVIDER = AuthorNameProvider()
SIGNED_TOOLINFO_PROVIDER = SignedToolinfoProvider()
TOOLFORGE_MAINTAINER_PROVIDER = ToolforgeMaintainerProvider()
TOOLFORGE_MEMBERSHIP_PROVIDER = ToolforgeMembershipProvider()
TOOLHUB_WRITE_PROVIDER = ToolhubWriteProvider()
TOOLINFO_CREATE_MAX_ITEMS = 200
TOOLINFO_CREATE_OPT_FIELDS = ("repository", "license", "toolType")
TOOLINFO_CREATE_LIST_FIELDS = ("keywords", "forWikis", "uiLanguages")
TOOLINFO_CREATE_BOOL_FIELDS = ("deprecated", "experimental")
SOURCE_ANALYSIS_REVIEW_STATUSES = {REVIEW_OPEN, REVIEW_APPROVED, REVIEW_REJECTED}
SOURCE_ANALYSIS_DEFAULT_LIMIT = 20
SOURCE_ANALYSIS_MAX_LIMIT = 50
SOURCE_ANALYSIS_NOT_FOUND = "source analysis report not found"
TOOL_SUMMARY_MAX_NAMES = 50
TOOL_SUMMARY_DEFAULT_LIMIT = 24
HEALTH_GRADE_STRONG = 85
HEALTH_GRADE_GOOD = 70
HEALTH_GRADE_ATTENTION = 50
RUNTIME_HEALTH_SCORES = {"healthy": 95, "ok": 90, "degraded": 55, "down": 15, "error": 20}
PUBLIC_JSON_CACHE_SECONDS = 5 * 60
PUBLIC_JSON_STALE_IF_ERROR_SECONDS = 24 * 60 * 60


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


def _clean_name(value: str) -> str | None:
    value = str(value or "").strip()
    return value[:MAX_NAME] if value else None


def _public_base_url() -> str:
    """Return the canonical base URL for links embedded in publicly cached output.

    request.url_root is built from the Host header, which the client controls.
    The feeds that consume this are served `Cache-Control: public, max-age=300`,
    so deriving the base URL from a request would let one forged Host put
    attacker-chosen <link>/<guid> values into a shared cache and serve them to
    everyone else for five minutes.

    Production therefore takes the value from configuration only, exactly like
    the OAuth callback (backend.oauth._callback_url) already does for the same
    reason. The fallback is a constant, not a header: an unset variable degrades
    to the wrong-but-fixed canonical host rather than to whatever was asked for.
    Header derivation stays available under the local-development flag, where
    there is no shared cache and no registered hostname to protect.
    """
    configured = os.environ.get("TOOLHUB_EVOLVED_BASE_URL", "").rstrip("/")
    if configured:
        return configured
    if os.environ.get("TOOLHUB_INSECURE_COOKIES") == "1":
        return request.url_root.rstrip("/")
    return DEFAULT_PUBLIC_BASE_URL


def _site_url(path: str) -> str:
    return f"{_public_base_url()}{path if path.startswith('/') else '/' + path}"


def _feed_text(value: Any, fallback: str = "") -> str:  # noqa: ANN401 - Toolhub payloads are heterogeneous JSON
    if isinstance(value, dict):
        for key in ("en", "mul"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
        for candidate in value.values():
            if candidate:
                return str(candidate)
        return fallback
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item) or fallback
    text_value = str(value or "").strip()
    return text_value or fallback


def _rss_date(value: Any) -> str:  # noqa: ANN401 - accepts ISO strings and datetime values
    dt = value if isinstance(value, datetime) else _parse_optional_iso(value)
    if dt is None:
        dt = utcnow()
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return format_datetime(dt, usegmt=True)


def _rss_item(title: str, link: str, description: str, published: Any, guid: str) -> dict[str, str]:  # noqa: ANN401
    return {
        "title": title,
        "link": link,
        "description": description,
        "pubDate": _rss_date(published),
        "guid": guid,
    }


def _rss_xml(title: str, description: str, link: str, items: list[dict[str, str]]) -> str:
    item_xml = "\n".join(
        f"""		<item>
			<title>{xml_escape(item["title"])}</title>
			<link>{xml_escape(item["link"])}</link>
			<guid isPermaLink="false">{xml_escape(item["guid"])}</guid>
			<pubDate>{xml_escape(item["pubDate"])}</pubDate>
			<description>{xml_escape(item["description"])}</description>
		</item>"""
        for item in items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
	<channel>
		<title>{xml_escape(title)}</title>
		<link>{xml_escape(link)}</link>
		<description>{xml_escape(description)}</description>
		<language>en</language>
		<lastBuildDate>{xml_escape(_rss_date(utcnow()))}</lastBuildDate>
{item_xml}
	</channel>
</rss>
"""


def _rss_response(title: str, description: str, link_path: str, items: list[dict[str, str]]) -> Response:
    resp = Response(_rss_xml(title, description, _site_url(link_path), items), content_type=RSS_CONTENT_TYPE)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def _public_json_response(payload: dict[str, Any], *, max_age: int = PUBLIC_JSON_CACHE_SECONDS) -> Response:
    """Return cacheable JSON with an ETag validator for public local-data endpoints."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    headers = {
        "Cache-Control": f"public, max-age={max_age}, stale-if-error={PUBLIC_JSON_STALE_IF_ERROR_SECONDS}",
        "ETag": etag,
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers=headers)
    return Response(body, headers=headers, content_type="application/json; charset=utf-8")


def _feed_payload(path: str, params: dict[str, object] | None = None) -> list[dict[str, Any]]:
    payload = toolhub.public_api_get(path, params=params)
    if not isinstance(payload, dict):
        return []
    rows = payload.get("results")
    public_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return activity_privacy.public_activity_rows(public_rows) if path.rstrip("/") == "/api/recent" else public_rows


def _upstream_feed_error(exc: Exception) -> Response:
    resp = jsonify({"error": "feed upstream unavailable", "detail": clean_error(str(exc))})
    resp.status_code = HTTP_BAD_GATEWAY
    return resp


def _recent_feed_item(row: dict[str, Any]) -> dict[str, str]:
    content_type = _feed_text(row.get("content_type"), "item")
    content_id = _feed_text(row.get("content_id"))
    title = _feed_text(row.get("content_title"), content_id or "Toolhub item")
    action = "Updated" if row.get("parent_id") else "Created"
    username = _feed_text(row.get("user", {}).get("username") if isinstance(row.get("user"), dict) else "", "system")
    comment = _feed_text(row.get("comment"))
    path = (
        f"/tools/{quote(content_id, safe='')}"
        if content_type == "tool" and content_id
        else f"/lists/{quote(content_id, safe='')}"
        if content_type == "list" and content_id
        else "/recent"
    )
    detail = f"{action} by {username}."
    if comment:
        detail = f"{detail} {comment}"
    guid = f"toolhub-recent:{row.get('id') or row.get('timestamp') or content_type + ':' + content_id}"
    return _rss_item(f"{action} {content_type}: {title}", _site_url(path), detail, row.get("timestamp"), guid)


def _tool_feed_item(row: dict[str, Any]) -> dict[str, str]:
    name = _feed_text(row.get("name"))
    title = _feed_text(row.get("title"), name or "Toolhub tool")
    description = _feed_text(row.get("description"), f"Toolhub tool {name or title}.")
    modified = row.get("modified_date") or row.get("modified")
    link = _site_url(f"/tools/{quote(name, safe='')}") if name else _site_url("/search")
    guid = f"toolhub-tool:{name or title}"
    return _rss_item(title, link, description, modified, guid)


def _list_feed_item(row: dict[str, Any]) -> dict[str, str]:
    list_id = _feed_text(row.get("id"))
    title = _feed_text(row.get("title"), f"Toolhub list {list_id}")
    description = _feed_text(row.get("description"), f"Toolhub list {title}.")
    modified = row.get("modified_date") or row.get("modified") or row.get("created_date") or row.get("created")
    link = _site_url(f"/lists/{quote(list_id, safe='')}") if list_id else _site_url("/lists")
    return _rss_item(title, link, description, modified, f"toolhub-list:{list_id or title}")


def _revision_feed_item(row: dict[str, Any], *, label: str, history_path: str, kind: str) -> dict[str, str]:
    revision_id = _feed_text(row.get("id"), _feed_text(row.get("timestamp"), "revision"))
    username = _feed_text(row.get("user", {}).get("username") if isinstance(row.get("user"), dict) else "", "system")
    comment = _feed_text(row.get("comment"))
    description = f"Revision by {username}."
    if comment:
        description = f"{description} {comment}"
    return _rss_item(
        f"Revision {revision_id}: {label}",
        _site_url(history_path),
        description,
        row.get("timestamp"),
        f"toolhub-{kind}-revision:{label}:{revision_id}",
    )


@v1_bp.route("/feeds/recent.xml")
def feed_recent() -> Response:
    """RSS feed for official Toolhub recent changes."""
    try:
        rows = _feed_payload("/api/recent/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        "Toolhub recent changes",
        "Recent official Toolhub catalog activity.",
        "/recent",
        [_recent_feed_item(row) for row in rows],
    )


@v1_bp.route("/feeds/tools/recently-updated.xml")
def feed_recently_updated_tools() -> Response:
    """RSS feed for recently updated tools."""
    try:
        rows = _feed_payload(
            "/api/search/tools/",
            {"ordering": "-modified_date", "page_size": RSS_FEED_PAGE_SIZE},
        )
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        "Toolhub recently updated tools",
        "Tools ordered by the official Toolhub modified date.",
        "/search?sort=recent",
        [_tool_feed_item(row) for row in rows],
    )


@v1_bp.route("/feeds/lists.xml")
def feed_lists() -> Response:
    """RSS feed for public Toolhub lists."""
    try:
        rows = _feed_payload("/api/lists/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        "Toolhub lists",
        "Recently visible public Toolhub lists.",
        "/lists",
        [_list_feed_item(row) for row in rows],
    )


@v1_bp.route("/feeds/tools/<path:name>/revisions.xml")
def feed_tool_revisions(name: str) -> Response:
    """RSS feed for one tool's official revision history."""
    clean_name = _clean_name(unquote(name))
    if clean_name is None:
        return _bad("tool name is required")
    try:
        rows = _feed_payload(f"/api/tools/{quote(clean_name, safe='')}/revisions/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        f"Toolhub revisions: {clean_name}",
        f"Official Toolhub revision history for {clean_name}.",
        f"/tools/{quote(clean_name, safe='')}/history",
        [
            _revision_feed_item(
                row,
                label=clean_name,
                history_path=f"/tools/{quote(clean_name, safe='')}/history",
                kind="tool",
            )
            for row in rows
        ],
    )


@v1_bp.route("/feeds/lists/<list_id>/revisions.xml")
def feed_list_revisions(list_id: str) -> Response:
    """RSS feed for one list's official revision history."""
    clean_id = str(list_id or "").strip()[:MAX_NAME]
    if not clean_id:
        return _bad("list id is required")
    try:
        rows = _feed_payload(f"/api/lists/{quote(clean_id, safe='')}/revisions/", {"page_size": RSS_FEED_PAGE_SIZE})
    except Exception as exc:  # noqa: BLE001 - feed readers need a clear 502 payload.
        return _upstream_feed_error(exc)
    return _rss_response(
        f"Toolhub list revisions: {clean_id}",
        f"Official Toolhub revision history for list {clean_id}.",
        f"/lists/{quote(clean_id, safe='')}/history",
        [
            _revision_feed_item(
                row,
                label=clean_id,
                history_path=f"/lists/{quote(clean_id, safe='')}/history",
                kind="list",
            )
            for row in rows
        ],
    )


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


def _public_tool_record_payload(row: ToolRecord) -> dict:
    """Return public tool data without private write diagnostics."""
    out = _tool_record_payload(row)
    for key in ("lastError", "toolhubResponse", "validationErrors"):
        out.pop(key, None)
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
        "catalog-curations": lambda item: {
            "id": item.id,
            "toolName": item.tool_name,
            "patch": item.patch,
            "rationale": item.rationale,
            "reviewStatus": item.review_status,
            "createdByUserId": item.created_by_user_id,
            "createdAt": _iso(item.created_at),
            "modifiedAt": _iso(item.modified_at),
        },
        "tool-records": _tool_record_payload,
        "health-targets": _health_target_payload,
        "media": _media_payload,
        "thanks": _thanks_payload,
    }
    return {"kind": kind, "id": row.id, "data": payload_builders[kind](row)}


def _bad(error: str, validation_errors: list | None = None) -> Response:
    payload: dict[str, Any] = {"error": error}
    if validation_errors:
        payload["lastError"] = error
        payload["validationErrors"] = validation_errors
    resp = jsonify(payload)
    resp.status_code = HTTP_BAD_REQUEST
    return resp


def _url_validation_message(value: Any, *, label: str, https_only: bool = True) -> str | None:  # noqa: ANN401
    """Validate URL-shaped write inputs before they reach Toolhub or crawler code."""
    message = None
    if not isinstance(value, str) or not value.strip():
        message = f"{label} is required."
    else:
        url = value.strip()
        try:
            parsed = urlparse(url)
            host = parsed.hostname
        except ValueError:
            parsed = None
            host = None
            message = f"{label} is not a valid URL."
        allowed = ("https",) if https_only else ("http", "https")
        if message is None and len(url) > MAX_URL:
            message = f"{label} must be {MAX_URL} characters or fewer."
        elif message is None and any(char.isspace() for char in url):
            message = f"{label} cannot contain spaces."
        elif message is None and parsed is not None and parsed.scheme.lower() not in allowed:
            message = f"{label} must use {'https' if https_only else 'http or https'}."
        elif message is None and (parsed is None or not parsed.netloc or not host):
            message = f"{label} must include a host."
    return message


def _url_validation_bad(field: str, message: str) -> Response:
    return _bad(message, [{"field": field, "message": message}])


def _deny(status: int, error: str) -> Response:
    resp = jsonify({"error": error})
    resp.status_code = status
    return resp


def _claim_payload(row: ToolAuthorClaim) -> dict:
    """Serialize one stored author claim into the resolver response contract."""
    return author_claim_payload(row)


def _author_key_payload(row: ToolAuthorKey) -> dict:
    """Serialize one registered public key for account export."""
    return {
        "keyId": row.key_id,
        "algorithm": row.algorithm,
        "fingerprint": public_key_fingerprint(row.public_key),
        "publicKey": row.public_key,
        "createdAt": _iso(row.created_at),
        "revokedAt": _iso(row.revoked_at),
        "lastUsedAt": _iso(row.last_used_at),
    }


def _author_claim_owned_by(user: User):  # noqa: ANN202 - returns a SQLAlchemy boolean expression
    """Match stable account ownership, with a narrow legacy username fallback."""
    return or_(
        ToolAuthorClaim.user_id == user.id,
        and_(ToolAuthorClaim.user_id.is_(None), ToolAuthorClaim.toolhub_username == user.username),
    )


def _author_key_owned_by(user: User):  # noqa: ANN202 - returns a SQLAlchemy boolean expression
    """Match stable account ownership, with a narrow legacy username fallback."""
    return or_(
        ToolAuthorKey.user_id == user.id,
        and_(ToolAuthorKey.user_id.is_(None), ToolAuthorKey.toolhub_username == user.username),
    )


def _source_analysis_payload(row: SourceAnalysisReport) -> dict:
    """Serialize one source-analysis report without raw submitted source."""
    report = row.report if isinstance(row.report, dict) else {}
    return {
        "id": row.id,
        "toolName": row.tool_name or "",
        "sourceLabel": row.source_label or "",
        "reviewStatus": clean_review_status(row.review_status, REVIEW_OPEN),
        "reviewNotes": row.review_notes or "",
        "createdAt": _iso(row.created_at),
        "reviewedAt": _iso(row.reviewed_at),
        "source": row.source or SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
        "syncLabel": _sync_label(row.sync_status or SYNC_EVOLVED_REAL),
        "report": report,
    }


def _score_grade(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= HEALTH_GRADE_STRONG:
        return "strong"
    if score >= HEALTH_GRADE_GOOD:
        return "good"
    if score >= HEALTH_GRADE_ATTENTION:
        return "needs-attention"
    return "high-risk"


def _health_status(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= HEALTH_GRADE_STRONG:
        return "healthy"
    if score >= HEALTH_GRADE_ATTENTION:
        return "watch"
    return "at-risk"


def _bounded_score(value: int) -> int:
    return max(0, min(100, value))


def _summary_dimension(  # noqa: PLR0913 - explicit fields keep scoring dimensions auditable.
    key: str,
    label: str,
    score: int | None,
    weight: float,
    status: str,
    summary: str,
    *,
    confidence: float = 0.5,
    source: str = SOURCE_LOCAL,
) -> dict[str, Any]:
    bounded = _bounded_score(score) if score is not None else None
    return {
        "key": key,
        "label": label,
        "score": bounded,
        "grade": _score_grade(bounded),
        "weight": weight,
        "status": status or _score_grade(bounded),
        "summary": summary,
        "confidence": round(max(0.1, min(0.99, confidence)), 2),
        "source": source,
        "includedInScore": bounded is not None,
    }


def _latest_public_health_core_statement(tool_name: str) -> Select[tuple[SourceAnalysisReport]]:
    return (
        select(SourceAnalysisReport)
        .where(
            SourceAnalysisReport.tool_name == tool_name,
            SourceAnalysisReport.review_status == REVIEW_APPROVED,
        )
        .order_by(
            SourceAnalysisReport.reviewed_at.is_(None),
            SourceAnalysisReport.reviewed_at.desc(),
            SourceAnalysisReport.created_at.desc(),
            SourceAnalysisReport.id.desc(),
        )
        .limit(1)
    )


def _source_repository_summary(report: dict[str, Any]) -> dict[str, Any] | None:
    context = report.get("repositoryContext") if isinstance(report.get("repositoryContext"), dict) else {}
    repository = context.get("repository") if isinstance(context.get("repository"), dict) else {}
    if not repository:
        return None

    summary: dict[str, Any] = {}
    for key in (
        "url",
        "branch",
        "defaultBranch",
        "commitSha",
        "lastCommitAt",
        "analyzedAt",
        "provider",
        "tag",
    ):
        value = repository.get(key)
        if value is not None and str(value).strip():
            summary[key] = str(value).strip()
    for key in ("commitCount", "contributorCount", "lastCommitAgeDays"):
        value = clean_int(repository.get(key))
        if value is not None:
            summary[key] = value
    return summary or None


def _latest_public_health_core(s: Any, tool_name: str) -> dict[str, Any] | None:  # noqa: ANN401 - SQLAlchemy session
    row = s.execute(_latest_public_health_core_statement(tool_name)).scalars().first()
    report = row.report if row is not None and isinstance(row.report, dict) else {}
    health_core = report.get("healthCore") if isinstance(report.get("healthCore"), dict) else None
    if not health_core:
        return None
    return {
        "score": clean_int(health_core.get("score")),
        "grade": str(health_core.get("grade") or "unknown"),
        "confidence": float(health_core.get("confidence") or 0),
        "sourceMaintenanceStatus": str(health_core.get("sourceMaintenanceStatus") or "unknown"),
        "maintainerActivityStatus": str(health_core.get("maintainerActivityStatus") or "unknown"),
        "stewardshipStatus": str(health_core.get("stewardshipStatus") or "needs-context"),
        "dimensions": health_core.get("dimensions") if isinstance(health_core.get("dimensions"), list) else [],
        "repository": _source_repository_summary(report),
        "createdAt": _iso(row.created_at),
        "reviewedAt": _iso(row.reviewed_at),
        "source": SOURCE_LOCAL,
        "syncStatus": row.sync_status or SYNC_EVOLVED_REAL,
    }


def _health_target_dimension(health: ToolHealthTarget | None) -> dict[str, Any] | None:
    if health is None:
        return None
    status = str(health.last_status or "unknown")
    score = RUNTIME_HEALTH_SCORES.get(status)
    return _summary_dimension(
        "runtime-health",
        "Runtime health",
        score,
        1.0,
        status,
        "Latest approved Evolved health target result.",
        confidence=0.9 if score is not None else 0.35,
        source=SOURCE_LOCAL,
    ) | {
        "checkedAt": _iso(health.last_checked_at),
        "targetUrl": health.target_url,
        "lastError": health.last_error or "",
    }


def _maintainer_activity_label(activity_status: str, summary_status: str) -> str:
    if activity_status in {"active", "quiet"} and summary_status in {"verified", "probable"}:
        return "maintained"
    if activity_status in {"active", "quiet"}:
        return "active-maintainer"
    if activity_status in {"stale", "dormant"}:
        return "maintainer-stale"
    if summary_status in {"verified", "probable"}:
        return "verified-maintainer"
    return "unknown"


def _maintainer_dimension(summary: dict[str, Any]) -> dict[str, Any]:
    counts = summary.get("healthCounts") if isinstance(summary.get("healthCounts"), dict) else {}
    people = summary.get("people") if isinstance(summary.get("people"), list) else []
    best = people[0] if people and isinstance(people[0], dict) else {}
    activity = best.get("activity") if isinstance(best.get("activity"), dict) else {}
    summary_status = str(summary.get("status") or "unknown")
    activity_status = str(activity.get("status") or "unknown")
    score = clean_int(summary.get("bestConfidence"))
    if score is not None:
        if activity_status == "active":
            score += 5
        elif activity_status == "quiet":
            score -= 5
        elif activity_status == "stale":
            score -= 25
        elif activity_status == "dormant":
            score -= 40
        if clean_int(counts.get("verifiedPeople")):
            score += 5
        if not clean_int(counts.get("people")):
            score = None
    label = _maintainer_activity_label(activity_status, summary_status)
    return _summary_dimension(
        "maintainer-status",
        "Maintainer status",
        _bounded_score(score) if score is not None else None,
        1.25,
        label,
        "Derived from Evolved maintainer evidence confidence and local maintainer activity.",
        confidence=0.85 if people else 0.2,
        source=SOURCE_LOCAL,
    ) | {
        "summaryStatus": summary_status,
        "activityStatus": activity_status,
        "bestConfidence": clean_int(summary.get("bestConfidence")) or 0,
        "counts": counts,
    }


def _health_summary_from_dimensions(
    tool_name: str,
    dimensions: list[dict[str, Any]],
    *,
    source_health: dict[str, Any] | None,
) -> dict[str, Any]:
    included = [item for item in dimensions if item.get("includedInScore") and item.get("score") is not None]
    weight = sum(float(item.get("weight") or 0) for item in included)
    score = (
        round(sum(float(item["score"]) * float(item.get("weight") or 0) for item in included) / weight)
        if weight
        else None
    )
    return {
        "toolName": tool_name,
        "score": score,
        "grade": _score_grade(score),
        "status": _health_status(score),
        "confidence": (
            round(weight / sum(float(item.get("weight") or 0) for item in dimensions), 2) if dimensions else 0
        ),
        "dimensions": dimensions,
        "sourceHealth": source_health,
        "calculation": {
            "formula": "weighted_average(included dimension scores)",
            "includedWeight": round(weight, 2),
            "dimensionCount": len(dimensions),
            "includedDimensionCount": len(included),
        },
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }


def _tool_names_from_request() -> list[str]:
    names = request.args.getlist("name")
    names.extend(str(request.args.get("names") or "").split(","))
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        clean = _clean_name(name)
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out[:TOOL_SUMMARY_MAX_NAMES]


def _build_local_tool_summary(s: Any, tool_name: str) -> dict[str, Any]:  # noqa: ANN401 - SQLAlchemy session
    maintainer_index.sync_author_claim_edges(s, tool_names=[tool_name])
    person_ids = {
        row[0]
        for row in s.execute(
            select(ToolPersonRelationship.person_id).where(ToolPersonRelationship.tool_name == tool_name).distinct()
        ).all()
    }
    people_index.refresh_activity_summaries(s, person_ids=person_ids)
    maintainer_summary = maintainer_index.public_tool_summary(s, tool_name)
    source_health = _latest_public_health_core(s, tool_name)
    dimensions: list[dict[str, Any]] = []
    if source_health:
        dimensions.append(
            _summary_dimension(
                "source-health",
                "Source health",
                clean_int(source_health.get("score")),
                1.5,
                str(source_health.get("stewardshipStatus") or source_health.get("grade") or "unknown"),
                "Latest approved deterministic source-analysis health core.",
                confidence=float(source_health.get("confidence") or 0.1),
                source=SOURCE_LOCAL,
            )
        )
    dimensions.append(_maintainer_dimension(maintainer_summary))
    health = (
        s.execute(
            select(ToolHealthTarget)
            .where(ToolHealthTarget.tool_name == tool_name, ToolHealthTarget.enabled.is_(True))
            .where(ToolHealthTarget.deleted_at.is_(None), ToolHealthTarget.review_status == REVIEW_APPROVED)
            .order_by(ToolHealthTarget.last_checked_at.desc(), ToolHealthTarget.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    health_dimension = _health_target_dimension(health)
    if health_dimension is not None:
        dimensions.append(health_dimension)
    return {
        "toolName": tool_name,
        "health": _health_summary_from_dimensions(tool_name, dimensions, source_health=source_health),
        "maintainer": maintainer_summary,
        "maintainerDimension": dimensions[0 if not source_health else 1],
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }


def _clean_author_key_id(value: Any) -> str | None:  # noqa: ANN401 - untrusted JSON
    """Return a valid author-key id for signed toolinfo metadata."""
    text_value = str(value or "").strip()
    return text_value if AUTHOR_KEY_ID_RE.fullmatch(text_value) else None


def _toolhub_tool_detail(tool_name: str) -> dict | None:
    """Fetch one exact official Toolhub tool record by name."""
    payload = toolhub.public_api_get(f"/api/tools/{quote(tool_name, safe='')}/")
    return payload if isinstance(payload, dict) and _clean_name(payload.get("name")) else None


def _record_successful_toolhub_write(
    user: User,
    method: str,
    path: str,
    request_payload: object | None,
    response_payload: object | None,
) -> None:
    """Persist Toolhub write-access evidence without affecting the completed write."""
    try:
        with db.session_scope() as s:
            TOOLHUB_WRITE_PROVIDER.record_success(
                s,
                user,
                method=method,
                path=path,
                request_payload=request_payload,
                response_payload=response_payload,
            )
            maintainer_index.sync_author_claim_edges(s, user_ids=[user.id])
    except Exception:  # noqa: BLE001 - provider evidence must never break a successful official write.
        return


def _current_policy_user() -> tuple[User | None, Response | None]:
    """Fetch the session user for Evolved-local policy checks."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required/write_guard guarantees this
    with db.session_scope() as s:
        user = s.get(User, uid)
    # current_user_id() already refuses a session whose user row is gone, so this
    # only fires if the account is deleted between that check and this one. Kept
    # for that race; unreachable from a test, hence the pragma.
    if user is None:  # pragma: no cover - delete-mid-request race
        session.clear()
        return None, _deny(HTTP_UNAUTHORIZED, "sign in required")
    return user, None


def _enforce(user: User, action: str, resource: object | None = None) -> Response | None:
    """Return a 403 when the Evolved-local policy rejects the action."""
    return None if authz.can(user, action, resource) else _deny(HTTP_FORBIDDEN, "not allowed")


def _require_policy(action: str, resource: object | None = None) -> tuple[User | None, Response | None]:
    """Fetch the current user and enforce one Evolved-local policy action."""
    user, denied = _current_policy_user()
    if denied is not None:  # pragma: no cover - only the race above denies here
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


def _upstream_path_parts(path: str) -> list[str]:
    """Return decoded pieces from an official Toolhub API path."""
    return [unquote(part) for part in path.strip("/").split("/") if part]


def _string_payload_value(payload: object | None, *keys: str) -> str | None:
    """Return the first non-empty string-like value from a JSON object payload."""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def _invalidate_official_api_cache(path: str, request_payload: object | None, response_payload: object | None) -> None:
    """Invalidate anonymous cached reads affected by a successful official write."""
    parts = _upstream_path_parts(path)
    if len(parts) < UPSTREAM_MIN_PARTS or parts[0] != "api":
        return
    if parts[UPSTREAM_KIND_INDEX] == "tools":
        tool_name = (
            parts[UPSTREAM_OBJECT_INDEX]
            if len(parts) >= UPSTREAM_OBJECT_PARTS
            else _string_payload_value(response_payload, "name")
        )
        if tool_name is None:
            tool_name = _string_payload_value(request_payload, "name")
        if tool_name is not None:
            api_cache.invalidate_tool(tool_name)
    elif parts[UPSTREAM_KIND_INDEX] == "lists":
        list_id = (
            parts[UPSTREAM_OBJECT_INDEX]
            if len(parts) >= UPSTREAM_OBJECT_PARTS
            else _string_payload_value(response_payload, "id")
        )
        if list_id is not None:
            api_cache.invalidate_list(list_id)
        else:
            api_cache.invalidate_list_collection()


def _json_object_body() -> tuple[dict | None, Response | None]:
    """Return the request JSON object or a normalized 400 response."""
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None, _bad("body must be a JSON object")
    return value, None


def _safe_failure_activity_payload(payload: dict) -> dict:
    """Keep fallback activity queryable without publishing submitted values."""
    response = payload.get("toolhubResponse")
    response = response if isinstance(response, dict) else {}
    safe = {
        "syncStatus": SYNC_LOCAL_FALLBACK,
        "httpStatus": payload.get("_toolhubStatus") or response.get("status_code") or response.get("status"),
        "toolhubCode": payload.get("_toolhubCode") or response.get("code"),
        "lastError": payload.get("lastError"),
    }
    local = payload.get("local")
    if isinstance(local, dict):
        meta = set(META_KEYS) | {"id", "name", "deleted"}
        safe["submittedFields"] = sorted(key for key in local if key not in meta)
    return {key: value for key, value in safe.items() if value not in (None, "", [])}


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
    stored_payload = _safe_failure_activity_payload(payload) if official_status == SYNC_LOCAL_FALLBACK else payload
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
                payload=stored_payload,
                source=SOURCE_LOCAL,
                sync_status=SYNC_EVOLVED_REAL,
                last_synced_at=now if official_status == SYNC_OFFICIAL else None,
                last_error=clean_error(stored_payload.get("lastError")),
            )
        )


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


def _claim_tool_or_error(name: str) -> tuple[dict | None, Response | None]:
    """Load one canonical Toolhub record for a claim operation."""
    clean_name = _clean_name(name)
    if clean_name is None:
        return None, _bad("tool name is required")
    try:
        tool = _toolhub_tool_detail(clean_name)
    except (toolhub.ToolhubAPIError, toolhub.requests.RequestException) as exc:
        return None, _deny(HTTP_BAD_GATEWAY, clean_error(str(exc)) or "official Toolhub is unavailable")
    if tool is None or _clean_name(tool.get("name")) != clean_name:
        return None, _deny(HTTP_NOT_FOUND, "canonical Toolhub tool not found")
    return tool, None


def _create_control_challenge(
    s: Session,
    user: User,
    tool_name: str,
    toolinfo_url: str,
) -> tuple[ToolinfoControlChallenge | None, Response | None]:
    url_error = _url_validation_message(toolinfo_url, label="toolinfo URL")
    if url_error is not None:
        return None, _url_validation_bad("toolinfoUrl", url_error)
    try:
        fetch_matching_item(toolinfo_url, tool_name)
    except Exception as exc:  # noqa: BLE001 - normalize bounded external proof failures
        return None, _bad(
            f"Could not read {tool_name} from the supplied toolinfo URL: {clean_error(str(exc)) or 'fetch failed'}"
        )
    now = utcnow()
    row = ToolinfoControlChallenge(
        user_id=user.id,
        tool_name=tool_name,
        toolinfo_url=toolinfo_url,
        challenge_token=new_token(),
        status=CHALLENGE_STATUS_PENDING,
        created_at=now,
        expires_at=now + CHALLENGE_TTL,
    )
    s.add(row)
    s.flush()
    return row, None


def _verify_control_challenge_record(
    s: Session,
    user: User,
    row: ToolinfoControlChallenge,
) -> tuple[ToolAuthorClaim | None, Response | None]:
    """Verify one URL-control challenge and update its workflow claim."""
    if row.status != CHALLENGE_STATUS_VERIFIED and challenge_expired(row):
        row.status = CHALLENGE_STATUS_EXPIRED
        row.last_checked_at = utcnow()
        row.last_error = "challenge expired; create a new challenge"
        return None, _deny(HTTP_CONFLICT, "ownership challenge expired; create a new challenge")
    if row.status != CHALLENGE_STATUS_VERIFIED:
        try:
            item = fetch_matching_item(row.toolinfo_url, row.tool_name)
        except Exception as exc:  # noqa: BLE001 - keep the challenge pending with an actionable reason
            row.last_checked_at = utcnow()
            row.last_error = clean_error(str(exc)) or "toolinfo fetch failed"
            return None, _bad(f"Could not verify the toolinfo URL: {row.last_error}")
        metadata = item.get("x_toolhub_evolved_verification")
        token = metadata.get("challenge") if isinstance(metadata, dict) else None
        if token != row.challenge_token:
            row.last_checked_at = utcnow()
            row.last_error = f"{CHALLENGE_FIELD} did not contain the issued challenge"
            return None, _bad(
                f"Publish the issued token in {CHALLENGE_FIELD}, then try again.",
                [{"field": CHALLENGE_FIELD, "message": "challenge token did not match"}],
            )
    now = utcnow()
    claim = record_author_claim(
        s,
        tool_name=row.tool_name,
        author_name=user.username,
        toolhub_username=user.username,
        user_id=user.id,
        verification_status=AUTHOR_CLAIM_VERIFIED,
        verification_method=AUTHOR_CLAIM_TOOLINFO_URL_CONTROL,
        evidence_url=row.toolinfo_url,
        evidence_payload={"challengeId": row.id, "field": CHALLENGE_FIELD, "proof": "url_control"},
        expires_at=now + CONTROL_CLAIM_TTL,
    )
    row.status = CHALLENGE_STATUS_VERIFIED
    row.verified_at = row.verified_at or now
    row.last_checked_at = now
    row.last_error = None
    maintainer_index.sync_author_claim_edges(s, tool_names=[row.tool_name], user_ids=[user.id])
    return claim, None


#: Matches the client's own per-render cap, so this never composes summaries
#: for tools the page will not draw.
_ME_TOOLS_SUMMARY_LIMIT = 50


def _profile_payload(profile: PersonProfile | None, person: Person) -> dict[str, Any]:
    return {
        "personId": person.public_id,
        "displayName": person.display_name,
        "bio": profile.bio if profile is not None else "",
        "avatarUrl": profile.avatar_url if profile is not None else "",
        "websiteUrl": profile.website_url if profile is not None else "",
        "location": profile.location if profile is not None else "",
        "links": profile.links if profile is not None and isinstance(profile.links, list) else [],
        "visibility": profile.visibility if profile is not None else "public",
        "updatedAt": _iso(profile.updated_at) if profile is not None else "",
        "source": SOURCE_LOCAL,
        "syncStatus": SYNC_EVOLVED_REAL,
    }


@v1_bp.route("/v1/config/")
def v1_config() -> Response:
    """Report which production capabilities are configured (no secrets)."""
    oauth = oauth_configured()
    return jsonify(
        {
            "oauth": oauth,
            "officialWrites": oauth,
            "devLogin": dev_login_available(),
            "issueReports": github_issues.configured(),
        }
    )


@v1_bp.route("/v1/debug/forwarded/")
@login_required
def v1_debug_forwarded() -> Response:
    """TEMPORARY: report how this request was forwarded, to size ProxyFix.

    Delete this route once the hop count is recorded in backend.register.

    Why it has to exist: the read and write rate limiters key on
    request.remote_addr, and no ProxyFix is installed, so behind the Toolforge
    front proxy every visitor shares one bucket — 121 requests from anyone
    returns 429 to everyone. Fixing that means ProxyFix(x_for=N), and N is the
    one value that cannot be guessed safely: too high and a client forges
    X-Forwarded-For to mint a fresh identity per request (an unlimited bucket,
    strictly worse than today), too low and it degrades back to the shared
    bucket. Only a real request through the real proxy chain answers it.

    `candidates` does the arithmetic: ProxyFix with x_for=N takes the Nth entry
    from the right, so the correct N is whichever row equals the caller's own
    public IP. Signed-in only — this reflects the caller's own request back to
    them, and there is no reason to hand the cluster's forwarding shape to
    anonymous traffic.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    entries = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    return jsonify(
        {
            "remoteAddr": request.remote_addr,
            "xForwardedFor": forwarded_for,
            "xForwardedForEntries": entries,
            "hopCount": len(entries),
            "candidates": {f"x_for={n}": entries[-n] for n in range(1, len(entries) + 1)},
            "accessRoute": list(request.access_route),
            "xForwardedProto": request.headers.get("X-Forwarded-Proto", ""),
            "xRealIp": request.headers.get("X-Real-IP", ""),
            "forwarded": request.headers.get("Forwarded", ""),
            "host": request.host,
        }
    )


@v1_bp.route("/v1/issue-reports/", methods=["POST"])
@write_guard
def v1_issue_report() -> Response:  # noqa: C901, PLR0911 - validation exits keep publication guard explicit
    """Publish an explicitly approved, authenticated report to GitHub."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("approved") is not True:
        return _bad("explicit issue approval is required")
    client_id = str(payload.get("clientId") or "").strip()
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    context = payload.get("context")
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,64}", client_id):
        return _bad("invalid issue report id")
    if not title or len(title) > github_issues.MAX_TITLE:
        return _bad("issue title must be between 1 and 200 characters")
    if not description or len(description) > github_issues.MAX_DESCRIPTION:
        return _bad("issue description is required and must be at most 12000 characters")
    if not isinstance(context, dict):
        return _bad("issue context must be an object")
    try:
        context_size = len(json.dumps(context, ensure_ascii=False))
    except (TypeError, ValueError):
        return _bad("issue context is not valid JSON")
    if context_size > github_issues.MAX_CONTEXT_CHARS:
        return _bad("issue context is too large")
    with db.session_scope() as s:
        existing = s.get(IssueReport, client_id)
        if existing is not None:
            if existing.user_id != uid:
                return _deny(HTTP_CONFLICT, "issue report id already belongs to another user")
            return jsonify(
                {"number": existing.issue_number, "url": existing.issue_url, "repository": existing.repository}
            )
        user = s.get(User, uid)
        if user is None:
            return _deny(HTTP_UNAUTHORIZED, "signed-in user not found")
        body = github_issues.render_body(description, context, user.username)
        try:
            published = github_issues.publish_issue(title, body)
        except github_issues.IssuePublishError as exc:
            return _deny(HTTP_BAD_GATEWAY, str(exc))
        s.add(
            IssueReport(
                client_id=client_id,
                user_id=uid,
                title=title,
                repository=published["repository"],
                issue_number=published["number"],
                issue_url=published["url"],
            )
        )
    return jsonify(published), 201


def _merged_maps(kind_rows: list[Any], viewer_uid: int | None = None) -> dict[str, dict]:
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
            if viewer_uid is not None:
                viewer_owned = row.user_id == viewer_uid
                payload["viewerOwned"] = viewer_owned
                if not viewer_owned:
                    for key in ("lastError", "toolhubResponse", "validationErrors"):
                        payload.pop(key, None)
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
                viewer_uid=uid,
            )
            for key, kind in OVERLAY_KINDS.items()
        }
        tool_new = {}
        for row in s.execute(
            select(ToolRecord)
            .where(
                ToolRecord.deleted_at.is_(None),
                or_(ToolRecord.user_id == uid, ToolRecord.visibility == VISIBILITY_PUBLIC),
            )
            .order_by(ToolRecord.modified_at)
        ).scalars():
            if row.user_id != uid and not _local_tool_is_public(row):
                continue
            record = _tool_record_payload(row)
            record["viewerOwned"] = row.user_id == uid
            if not record["viewerOwned"]:
                for key in ("lastError", "toolhubResponse", "validationErrors"):
                    record.pop(key, None)
            tool_new[row.tool_name] = record
        feeds = {
            key: activity_privacy.public_activity_rows(
                [
                    r.row
                    for r in s.execute(
                        select(ActivityRow)
                        .where(ActivityRow.kind == key)
                        .order_by(ActivityRow.created_at.desc(), ActivityRow.id.desc())
                        .limit(FEED_READ_CAP)
                    ).scalars()
                ]
            )
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


def _data_patch(patch: dict) -> dict:
    """Remove lifecycle metadata before merging a local overlay into a tool."""
    return {k: v for k, v in patch.items() if k not in META_KEYS and k not in CANONICAL_TOOL_KEYS}


@v1_bp.route("/v1/canonical/tools/")
def v1_canonical_tools() -> Response:
    """Return locally cached canonical official Toolhub tool records."""
    names = _tool_names_from_request()
    q = str(request.args.get("q") or "").strip()
    limit = min(max(clean_int(request.args.get("limit")) or TOOL_SUMMARY_DEFAULT_LIMIT, 1), TOOL_SUMMARY_MAX_NAMES)
    if names:
        rows_by_name = canonical_tools.tools_by_name(names)
        results = [rows_by_name[name] for name in names if name in rows_by_name]
    else:
        results = canonical_tools.search(q, limit=limit)
    return jsonify(
        {
            "count": len(results),
            "results": results,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "cachePolicy": {
                "canonical": True,
                "upstream": False,
                "summary": "Local structured cache populated from prior official Toolhub API reads.",
            },
        }
    )


@v1_bp.route("/v1/home/")
def v1_home() -> Response:
    """Return the whole landing page in one composed, cached payload.

    The homepage previously needed nine reads with a dependency between them —
    summaries and the most-listed ordering could not start until the list and
    search reads returned. Composing here collapses that into one request.
    """
    return _public_json_response(
        home_payload.payload(
            lambda names: tool_summaries.summaries_for(names, _build_local_tool_summary, view=tool_summaries.VIEW_CARD),
        )
    )


@v1_bp.route("/v1/graph/")
def v1_graph() -> Response:
    """Return a cached global graph derived from the local canonical catalog."""
    return _public_json_response(
        graph_payload.payload(
            limit=request.args.get("limit"),
            group_by=request.args.get("groupBy"),
        )
    )


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
            row.tool_name: _public_tool_record_payload(row)
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


@v1_bp.route("/v1/recent/owners/")
def v1_recent_owners() -> Response:
    """Bulk-resolve Recent table owner labels through the shared ToolsDB cache.

    Public and unauthenticated, but every cache miss costs an upstream Toolhub
    request, so this is the one read endpoint that can amplify traffic. It is
    rate limited per client like the /api/ proxy, and capped again by a
    per-request fetch budget so a single allowed call cannot fan out into
    OWNER_MAX_NAMES upstream requests.
    """
    if security.read_rate_limited(request.remote_addr):
        return _deny(HTTP_TOO_MANY, "rate limit exceeded")
    names = request.args.getlist("tool")
    csv_names = request.args.get("tools", "")
    if csv_names:
        names.extend(csv_names.split(","))
    return jsonify(recent_owners.resolve_owners(names, fetch_budget=recent_owners.OWNER_FETCH_BUDGET))


@v1_bp.route("/toolinfo.json")
def toolinfo_feed() -> Response:
    """Serve the public toolinfo feed of locally-registered tools.

    The official Toolhub crawler can ingest this feed (docs/PRODUCTION.md
    §1.3 — we feed the ecosystem instead of forking it).
    """
    with db.session_scope() as s:
        merged = {
            row.tool_name: _public_tool_record_payload(row)
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
            "_schema": "/toolinfo/1.2.2",
        }

    feed = [entry(name, rec) for name, rec in merged.items() if str(rec.get("url") or "").startswith("https://")]
    return jsonify(feed)
