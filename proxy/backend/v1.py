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

import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlparse
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, abort, jsonify, request, session
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.sql import Select

from backend import (
    api_cache,
    authz,
    canonical_tools,
    db,
    graph_payload,
    github_issues,
    maintainer_index,
    recent_owners,
    security,
    source_analyzer,
    tool_summaries,
    toolhub,
    toolinfo_discovery,
    toolinfo_sources,
)
from backend.author_claims import (
    SIGNATURE_META_KEY,
    AuthorNameProvider,
    SignedToolinfoProvider,
    ToolforgeMaintainerProvider,
    ToolforgeMembershipProvider,
    ToolhubWriteProvider,
    author_names_from_toolhub_tool,
    canonical_toolinfo_string,
    dedupe_strings,
    public_key_fingerprint,
    string_key,
    validate_ed25519_public_key,
)
from backend.author_claims import (
    claim_payload as author_claim_payload,
)
from backend.models import (
    ActivityRow,
    CrawlerRun,
    CrawlerUrl,
    Favorite,
    MaintainerActivityRollup,
    SourceAnalysisReport,
    ToolAuthorClaim,
    ToolAuthorKey,
    ToolEvent,
    ToolHealthTarget,
    IssueReport,
    ToolhubToken,
    ToolList,
    ToolMaintainerEdge,
    ToolMedia,
    ToolOverlay,
    ToolRecord,
    ToolThanks,
    User,
    utcnow,
)
from backend.oauth import configured as oauth_configured
from backend.oauth import dev_login_available
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
ME_TOOLS_SEARCH_PAGE_SIZE = 100
ME_TOOLS_MAX_SEARCH_TERMS = 20
AUTHOR_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SIGNATURE_PLACEHOLDER = "<base64 signature>"
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


def _visibility(value: Any, default: str = VISIBILITY_PRIVATE) -> str:  # noqa: ANN401
    return value if value in {VISIBILITY_PRIVATE, VISIBILITY_PUBLIC} else default


def _clean_name(value: str) -> str | None:
    value = str(value or "").strip()
    return value[:MAX_NAME] if value else None


def _is_http_url(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, str) and value.startswith(("http://", "https://")) and len(value) <= MAX_URL


def _public_base_url() -> str:
    configured = os.environ.get("TOOLHUB_EVOLVED_BASE_URL", "").rstrip("/")
    return configured or request.url_root.rstrip("/")


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
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


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


def _string_key(value: Any) -> str:  # noqa: ANN401 - untrusted API JSON
    """Return a case-insensitive key for display/user/tool names."""
    return string_key(value)


def _dedupe_strings(values: list[Any]) -> list[str]:
    """Return non-empty strings in first-seen order, case-insensitively deduped."""
    return dedupe_strings(values)


def _toolhub_author_names(tool: dict) -> list[str]:
    """Return author display and identity names from one official Toolhub tool."""
    return author_names_from_toolhub_tool(tool)


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


def _maintainer_context_from_summary(summary: dict) -> dict:
    """Translate the maintainer-index API shape into source-analyzer context."""
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    maintainers = summary.get("maintainers") if isinstance(summary.get("maintainers"), list) else []
    maintainer_count = clean_int(counts.get("maintainers"))
    if not maintainer_count and not maintainers:
        return {}
    ages: list[int] = []
    recent_activity_count = 0
    for row in maintainers:
        activity = row.get("activity") if isinstance(row, dict) else {}
        if not isinstance(activity, dict):
            continue
        age = clean_int(activity.get("lastActivityAgeDays"))
        if age is not None:
            ages.append(max(0, age))
        recent_activity_count += clean_int(activity.get("recentActivityCount")) or 0
    context: dict[str, Any] = {
        "maintainerCount": maintainer_count or len(maintainers),
        "activeMaintainerCount": clean_int(counts.get("activeMaintainers")) or 0,
        "recentActivityCount": recent_activity_count,
        "source": "evolved-maintainer-index",
        "analyzedAt": _iso(utcnow()),
    }
    if ages:
        context["lastActivityAgeDays"] = min(ages)
    return context


def _source_repository_context(tool_name: str | None, repository_context: object) -> object:
    """Add Evolved maintainer context to source analysis when no caller context exists."""
    if tool_name is None or (repository_context is not None and not isinstance(repository_context, dict)):
        return repository_context
    if (
        isinstance(repository_context, dict)
        and isinstance(repository_context.get("maintainers"), dict)
        and repository_context["maintainers"]
    ):
        return repository_context
    with db.session_scope() as s:
        maintainer_index.sync_author_claim_edges(s, tool_names=[tool_name])
        keys = [
            row[0]
            for row in s.execute(
                select(ToolMaintainerEdge.maintainer_key).where(ToolMaintainerEdge.tool_name == tool_name).distinct()
            ).all()
        ]
        maintainer_index.refresh_activity_rollups(s, maintainer_keys=keys)
        summary = maintainer_index.public_tool_summary(s, tool_name)
    maintainer_context = _maintainer_context_from_summary(summary)
    if not maintainer_context:
        return repository_context
    merged = dict(repository_context or {})
    merged["maintainers"] = maintainer_context
    return merged


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
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    maintainers = summary.get("maintainers") if isinstance(summary.get("maintainers"), list) else []
    best = maintainers[0] if maintainers and isinstance(maintainers[0], dict) else {}
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
        if clean_int(counts.get("verifiedMaintainers")):
            score += 5
        if not clean_int(counts.get("maintainers")):
            score = None
    label = _maintainer_activity_label(activity_status, summary_status)
    return _summary_dimension(
        "maintainer-status",
        "Maintainer status",
        _bounded_score(score) if score is not None else None,
        1.25,
        label,
        "Derived from Evolved maintainer evidence confidence and local maintainer activity.",
        confidence=0.85 if maintainers else 0.2,
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
    keys = [
        row[0]
        for row in s.execute(
            select(ToolMaintainerEdge.maintainer_key).where(ToolMaintainerEdge.tool_name == tool_name).distinct()
        ).all()
    ]
    maintainer_index.refresh_activity_rollups(s, maintainer_keys=keys)
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


def _toolinfo_body(value: Any) -> dict | None:  # noqa: ANN401 - untrusted JSON
    """Return one toolinfo object from JSON input."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    return value if _clean_name(value.get("name")) is not None else None


def _signature_metadata(key_id: str) -> dict:
    """Return the metadata block a maintainer adds after signing."""
    return {"algorithm": "ed25519", "key_id": key_id, "signature": SIGNATURE_PLACEHOLDER}


def _toolhub_search_results(term: str) -> list[dict]:
    """Fetch candidate tools from official Toolhub search for one author term."""
    payload = toolhub.public_api_get(
        "/api/search/tools/",
        params={
            "author__term": term,
            "ordering": "-score",
            "page": 1,
            "page_size": ME_TOOLS_SEARCH_PAGE_SIZE,
        },
    )
    results = payload.get("results") if isinstance(payload, dict) else []
    return [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []


def _toolhub_tool_detail(tool_name: str) -> dict | None:
    """Fetch one exact official Toolhub tool record by name."""
    payload = toolhub.public_api_get(f"/api/tools/{quote(tool_name, safe='')}/")
    return payload if isinstance(payload, dict) and _clean_name(payload.get("name")) else None


def _claims_by_tool(claims: list[dict]) -> dict[str, list[dict]]:
    """Group serialized author claims by Toolhub tool name."""
    out: dict[str, list[dict]] = {}
    for claim in claims:
        out.setdefault(_string_key(claim.get("toolName")), []).append(claim)
    return out


def _search_terms_for_user(username: str, claims: list[ToolAuthorClaim]) -> list[str]:
    """Return bounded Toolhub author-search terms for a signed-in user."""
    return _dedupe_strings([username, *[row.author_name for row in claims]])[:ME_TOOLS_MAX_SEARCH_TERMS]


def _add_candidate_tool(candidates: dict[str, dict], row: dict, term: str) -> None:
    """Merge one official Toolhub search result into the candidate map."""
    tool_name = _clean_name(row.get("name"))
    if tool_name is None:
        return
    entry = candidates.setdefault(
        tool_name,
        {
            "tool": row,
            "matchedAuthorNames": [],
            "searchTerms": [],
        },
    )
    entry["searchTerms"] = _dedupe_strings([*entry["searchTerms"], term])
    author_names = _toolhub_author_names(row)
    matched = [name for name in author_names if _string_key(name) == _string_key(term)] or [term]
    entry["matchedAuthorNames"] = _dedupe_strings([*entry["matchedAuthorNames"], *matched])


def _add_toolforge_candidate(candidates: dict[str, dict], row: dict, toolforge_name: str, username: str) -> None:
    """Merge one exact Toolforge-derived Toolhub tool into the candidate map."""
    tool_name = _clean_name(row.get("name"))
    if tool_name is None:
        return
    entry = candidates.setdefault(
        tool_name,
        {
            "tool": row,
            "matchedAuthorNames": [],
            "searchTerms": [],
        },
    )
    entry["tool"] = row
    entry["searchTerms"] = _dedupe_strings([*entry["searchTerms"], f"toolforge:{toolforge_name}"])
    entry["matchedAuthorNames"] = _dedupe_strings(
        [*entry["matchedAuthorNames"], *(_toolhub_author_names(row) or [username])]
    )
    entry["evidenceUrl"] = TOOLFORGE_MAINTAINER_PROVIDER.evidence_url(toolforge_name)
    entry["evidencePayload"] = {
        **(entry.get("evidencePayload") if isinstance(entry.get("evidencePayload"), dict) else {}),
        "toolforgeToolName": toolforge_name,
        "discoveryMethod": "toolforge_ldap_membership",
    }


def _candidate_tools_for_terms(search_terms: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """Search official Toolhub for all resolver terms, preserving partial successes."""
    candidates: dict[str, dict] = {}
    errors: list[dict] = []
    for term in search_terms:
        try:
            rows = _toolhub_search_results(term)
        except toolhub.ToolhubAPIError as exc:
            errors.append({"term": term, "status": exc.status_code, "details": exc.payload})
            continue
        except toolhub.requests.RequestException as exc:
            errors.append({"term": term, "status": 502, "details": {"message": str(exc)}})
            continue
        for row in rows:
            _add_candidate_tool(candidates, row, term)
    return candidates, errors


def _candidate_tools_for_toolforge_memberships(username: str) -> tuple[dict[str, dict], list[dict], list[str]]:
    """Fetch official Toolhub candidates from Toolforge tool-account memberships."""
    candidates: dict[str, dict] = {}
    errors: list[dict] = []
    toolforge_names = TOOLFORGE_MEMBERSHIP_PROVIDER.tool_names(username)
    for toolforge_name in toolforge_names:
        official_name = f"toolforge-{toolforge_name}"
        try:
            row = _toolhub_tool_detail(official_name)
        except toolhub.ToolhubAPIError as exc:
            if exc.status_code != HTTP_NOT_FOUND:
                errors.append({"term": official_name, "status": exc.status_code, "details": exc.payload})
            continue
        except toolhub.requests.RequestException as exc:
            errors.append({"term": official_name, "status": 502, "details": {"message": str(exc)}})
            continue
        if row is not None:
            _add_toolforge_candidate(candidates, row, toolforge_name, username)
    return candidates, errors, toolforge_names


def _resolver_item(
    tool_name: str,
    entry: dict,
    claims_by_tool: dict[str, list[dict]],
    discoveries_by_tool: dict[str, dict] | None = None,
    sources_by_tool: dict[str, dict] | None = None,
) -> dict:
    """Attach only this tool's provider claims to one candidate Toolhub tool."""
    claims = list(claims_by_tool.get(_string_key(tool_name), []))
    return {
        "tool": entry["tool"],
        "matchedAuthorNames": entry["matchedAuthorNames"],
        "searchTerms": entry["searchTerms"],
        "evidenceUrl": entry.get("evidenceUrl"),
        "claims": claims,
        "toolinfoDiscovery": (discoveries_by_tool or {}).get(tool_name, toolinfo_discovery.discovery_payload(None)),
        "toolinfoSource": (sources_by_tool or {}).get(tool_name),
    }


def _resolver_groups(
    candidates: dict[str, dict],
    claims_by_tool: dict[str, list[dict]],
    discoveries_by_tool: dict[str, dict] | None = None,
    sources_by_tool: dict[str, dict] | None = None,
) -> dict:
    """Split candidate tools into verified and possible groups."""
    groups: dict[str, list[dict]] = {"verified": [], "possible": []}
    for tool_name, entry in candidates.items():
        item = _resolver_item(tool_name, entry, claims_by_tool, discoveries_by_tool, sources_by_tool)
        key = "verified" if any(claim.get("isVerified") for claim in item["claims"]) else "possible"
        groups[key].append(item)
    return groups


def _author_search_evidence_url(search_term: str) -> str:
    """Return the official Toolhub search URL that produced an author-name match."""
    query = urlencode(
        {
            "author__term": search_term,
            "ordering": "-score",
            "page": 1,
            "page_size": ME_TOOLS_SEARCH_PAGE_SIZE,
        }
    )
    return f"{toolhub.base_url()}/api/search/tools/?{query}"


def _record_candidate_provider_claims(user: User, candidates: dict[str, dict]) -> list[dict]:
    """Persist resolver-side provider evidence and return fresh claim payloads."""
    with db.session_scope() as s:
        for tool_name, entry in candidates.items():
            search_term = entry["searchTerms"][0] if entry["searchTerms"] else user.username
            AUTHOR_NAME_PROVIDER.record(
                s,
                user,
                tool_name=tool_name,
                author_names=entry["matchedAuthorNames"],
                evidence_url=entry.get("evidenceUrl") or _author_search_evidence_url(search_term),
                evidence_payload=entry.get("evidencePayload") or {"searchTerms": entry["searchTerms"]},
            )
            TOOLFORGE_MAINTAINER_PROVIDER.verify(
                s,
                user,
                tool_name=tool_name,
                author_names=entry["matchedAuthorNames"],
                toolhub_tool=entry["tool"],
            )
        rows = list(
            s.execute(select(ToolAuthorClaim).where(ToolAuthorClaim.toolhub_username == user.username)).scalars()
        )
        maintainer_index.sync_author_claim_edges(s, usernames=[user.username])
        return [_claim_payload(row) for row in rows]


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
            maintainer_index.sync_author_claim_edges(s, usernames=[user.username])
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
    _invalidate_official_api_cache(path, payload, body)
    _record_successful_toolhub_write(user, method, path, payload, body)
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
    _invalidate_official_api_cache(path, payload, body)
    _record_successful_toolhub_write(user, method, path, payload, body)
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
    if attempt.get("crawlerFetch") is not None:
        payload["crawlerFetch"] = attempt["crawlerFetch"]
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
    payload = {
        "ok": True,
        "result": SYNC_LOCAL_FALLBACK,
        "syncStatus": SYNC_LOCAL_FALLBACK,
        "lastError": failure["lastError"],
        "validationErrors": failure["validationErrors"],
        "toolhubResponse": failure["details"],
        "local": local,
    }
    if failure.get("crawlerFetch") is not None:
        payload["crawlerFetch"] = failure["crawlerFetch"]
    resp = jsonify(payload)
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


def _validated_tool_write(
    value: dict,
    route_name: str | None,
) -> tuple[str | None, dict | None, str | None, Response | None]:
    """Validate a tool write request and extract create-only crawler metadata."""
    name, fields = _compact_tool_payload(value, route_name)
    if name is None or fields is None:
        return None, None, None, _bad("tool write needs name, title, description and an https url")
    if route_name is not None:
        return name, fields, None, None
    toolinfo_url, toolinfo_err = _create_toolinfo_url(value)
    return name, fields, toolinfo_url, toolinfo_err


def _create_toolinfo_url(payload: dict) -> tuple[str | None, Response | None]:
    """Return a valid create-time toolinfo URL, when supplied."""
    value = _payload_value(payload, "toolinfoUrl", "toolinfo_url")
    if not isinstance(value, str) or not value.strip():
        return None, None
    url = value.strip()
    error = _url_validation_message(url, label="toolinfo URL")
    if error is not None:
        return None, _url_validation_bad("toolinfo_url", error)
    return url, None


def _fetch_toolinfo_json_once(url: str) -> object:
    """Reuse the scheduled crawler's hardened fetcher for create-time enrichment."""
    import crawl  # noqa: PLC0415 - local import avoids backend package startup cycles.

    return crawl._fetch_json(toolhub.requests.Session(), url)  # noqa: SLF001 - shared internal crawler primitive.


def _normalize_toolinfo_item(item: dict) -> dict | None:
    """Reuse the crawler's compact toolinfo→Evolved record mapping."""
    import crawl  # noqa: PLC0415 - local import avoids backend package startup cycles.

    return crawl.normalize_record(item)


def _matching_toolinfo_item(data: object, name: str) -> dict | None:
    """Find the item for the tool being created in one toolinfo response."""
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data[:TOOLINFO_CREATE_MAX_ITEMS]
    else:
        return None
    for item in items:
        if isinstance(item, dict) and _clean_name(item.get("name")) == name:
            return item
    return None


def _merge_toolinfo_fields(fields: dict, record: dict) -> tuple[dict, list[str]]:
    """Fill missing create fields from toolinfo while preserving explicit user input."""
    merged = dict(fields)
    enriched: list[str] = []
    for field in TOOLINFO_CREATE_OPT_FIELDS:
        if not merged.get(field) and record.get(field):
            merged[field] = record[field]
            enriched.append(field)
    for field in TOOLINFO_CREATE_LIST_FIELDS:
        if not merged.get(field) and record.get(field):
            merged[field] = record[field]
            enriched.append(field)
    for field in TOOLINFO_CREATE_BOOL_FIELDS:
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
                SIGNED_TOOLINFO_PROVIDER.verify(s, owner, toolinfo=toolinfo_item, evidence_url=toolinfo_url)
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
        if user is None:  # pragma: no cover - delete-mid-request race; see _current_policy_user
            session.clear()
            return jsonify({"authenticated": False})
        role = authz.user_role(user)
        official_writes = s.get(ToolhubToken, uid) is not None
        return jsonify(
            {
                "authenticated": True,
                "username": user.username,
                "csrf": session.get("csrf", ""),
                "officialWrites": official_writes,
                "evolvedRole": role,
                "evolvedRoleLabel": authz.role_label(role),
                "evolvedPermissions": authz.role_permissions(role),
            }
        )


@v1_bp.route("/v1/author-keys/")
@login_required
def v1_author_keys() -> Response:
    """List public keys registered by the signed-in Toolhub user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        keys = [
            _author_key_payload(row)
            for row in s.execute(
                select(ToolAuthorKey)
                .where(ToolAuthorKey.toolhub_username == user.username)
                .order_by(ToolAuthorKey.revoked_at.is_not(None), ToolAuthorKey.created_at, ToolAuthorKey.id)
            ).scalars()
        ]
    return jsonify({"username": user.username, "keys": keys})


@v1_bp.route("/v1/author-keys/", methods=["POST"])
@write_guard
def v1_author_key_create() -> Response:
    """Register one public key for signed-toolinfo verification."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = _json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — _json_object_body returned no error
    key_id = _clean_author_key_id(_payload_value(body, "keyId", "key_id"))
    if key_id is None:
        return _bad("keyId must use 1-128 letters, digits, dots, colons, underscores or hyphens")
    algorithm = str(_payload_value(body, "algorithm") or "ed25519").strip().lower()
    if algorithm != "ed25519":
        return _bad("only ed25519 public keys are supported")
    try:
        public_key = validate_ed25519_public_key(str(_payload_value(body, "publicKey", "public_key") or ""))
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    with db.session_scope() as s:
        existing = s.execute(
            select(ToolAuthorKey).where(ToolAuthorKey.toolhub_username == user.username, ToolAuthorKey.key_id == key_id)
        ).scalar_one_or_none()
        if existing is not None:
            return _deny(HTTP_CONFLICT, "key id already exists")
        row = ToolAuthorKey(toolhub_username=user.username, key_id=key_id, public_key=public_key, algorithm=algorithm)
        s.add(row)
        s.flush()
        payload = _author_key_payload(row)
    resp = jsonify({"ok": True, "key": payload})
    resp.status_code = 201
    return resp


@v1_bp.route("/v1/author-keys/<key_id>/", methods=["DELETE"])
@write_guard
def v1_author_key_revoke(key_id: str) -> Response:
    """Revoke one registered public key for the signed-in Toolhub user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
    clean_key_id = _clean_author_key_id(key_id)
    if clean_key_id is None:
        return _bad("invalid key id")
    with db.session_scope() as s:
        row = s.execute(
            select(ToolAuthorKey).where(
                ToolAuthorKey.toolhub_username == user.username,
                ToolAuthorKey.key_id == clean_key_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return _deny(HTTP_NOT_FOUND, "public key not found")
        if row.revoked_at is None:
            row.revoked_at = utcnow()
        payload = _author_key_payload(row)
    return jsonify({"ok": True, "key": payload})


@v1_bp.route("/v1/toolinfo/signing-payload/", methods=["POST"])
@write_guard
def v1_toolinfo_signing_payload() -> Response:
    """Return the canonical toolinfo bytes that a registered key should sign."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    body, bad = _json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — _json_object_body returned no error
    key_id = _clean_author_key_id(_payload_value(body, "keyId", "key_id"))
    if key_id is None:
        return _bad("choose a registered key id")
    toolinfo = _toolinfo_body(_payload_value(body, "toolinfo"))
    if toolinfo is None:
        return _bad("toolinfo must be one JSON object with a valid name")
    with db.session_scope() as s:
        key = s.execute(
            select(ToolAuthorKey).where(
                ToolAuthorKey.toolhub_username == user.username,
                ToolAuthorKey.key_id == key_id,
                ToolAuthorKey.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        if key is None:
            return _deny(HTTP_NOT_FOUND, "active public key not found")
    canonical_payload = canonical_toolinfo_string(toolinfo)
    signature_metadata = _signature_metadata(key_id)
    return jsonify(
        {
            "toolName": _clean_name(toolinfo.get("name")),
            "keyId": key_id,
            "algorithm": "ed25519",
            "signatureField": SIGNATURE_META_KEY,
            "canonicalPayload": canonical_payload,
            "canonicalPayloadBase64": base64.b64encode(canonical_payload.encode("utf-8")).decode("ascii"),
            "signatureMetadata": signature_metadata,
            "signedToolinfoPreview": {**toolinfo, SIGNATURE_META_KEY: signature_metadata},
        }
    )


@v1_bp.route("/v1/source-analysis/")
@login_required
def v1_source_analysis_list() -> Response:
    """List source-analysis reports owned by the signed-in user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    limit = min(
        max(clean_int(request.args.get("limit")) or SOURCE_ANALYSIS_DEFAULT_LIMIT, 1),
        SOURCE_ANALYSIS_MAX_LIMIT,
    )
    tool_name = _clean_name(request.args.get("tool", ""))
    stmt = select(SourceAnalysisReport).where(SourceAnalysisReport.user_id == uid)
    if tool_name is not None:
        stmt = stmt.where(SourceAnalysisReport.tool_name == tool_name)
    with db.session_scope() as s:
        reports = list(
            s.execute(
                stmt.order_by(SourceAnalysisReport.created_at.desc(), SourceAnalysisReport.id.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
    return jsonify({"count": len(reports), "results": [_source_analysis_payload(row) for row in reports]})


@v1_bp.route("/v1/source-analysis/", methods=["POST"])
@write_guard
def v1_source_analysis_create() -> Response:
    """Analyze submitted source files and store the derived report."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = _json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — _json_object_body returned no error
    tool_name = _clean_name(_payload_value(body, "toolName", "tool_name"))
    source_label = str(_payload_value(body, "sourceLabel", "source_label") or "").strip()[:MAX_NAME]
    repository_context = _source_repository_context(
        tool_name,
        _payload_value(body, "repositoryContext", "repository_context"),
    )
    try:
        report = source_analyzer.analyze_source_files(
            _payload_value(body, "files"),
            tool_name=tool_name,
            source_label=source_label,
            repository_context=repository_context,
        )
    except source_analyzer.SourceAnalysisError as exc:
        return _bad(str(exc))
    with db.session_scope() as s:
        row = SourceAnalysisReport(
            user_id=uid,
            created_by_user_id=uid,
            tool_name=tool_name,
            source_label=source_label,
            report=report,
            review_status=REVIEW_OPEN,
            source=SOURCE_LOCAL,
            sync_status=SYNC_EVOLVED_REAL,
        )
        s.add(row)
        s.flush()
        payload = _source_analysis_payload(row)
        _emit_structured_activity(
            s,
            user,
            action="source-analysis-created",
            object_type="source_analysis",
            object_key=str(row.id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"toolName": tool_name, "sourceLabel": source_label},
            title=tool_name or source_label or f"Source analysis #{row.id}",
        )
    resp = jsonify({"ok": True, "sourceAnalysis": payload})
    resp.status_code = 201
    return resp


@v1_bp.route("/v1/source-analysis/<int:report_id>/")
@login_required
def v1_source_analysis_detail(report_id: int) -> Response:
    """Return one source-analysis report owned by the signed-in user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    with db.session_scope() as s:
        row = s.get(SourceAnalysisReport, report_id)
        if row is None or row.user_id != uid:
            return _deny(HTTP_NOT_FOUND, SOURCE_ANALYSIS_NOT_FOUND)
        payload = _source_analysis_payload(row)
    return jsonify({"sourceAnalysis": payload})


@v1_bp.route("/v1/source-analysis/<int:report_id>/review/", methods=["POST"])
@write_guard
def v1_source_analysis_review(report_id: int) -> Response:
    """Mark one source-analysis report as open, approved, or rejected."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_WRITE, authz.Resource(owner_user_id=uid))
    body, bad = _json_object_body()
    if bad is not None:
        return bad
    assert body is not None  # noqa: S101 — _json_object_body returned no error
    review_status = str(_payload_value(body, "reviewStatus", "review_status") or "").strip()
    if review_status not in SOURCE_ANALYSIS_REVIEW_STATUSES:
        return _bad("reviewStatus must be open, approved, or rejected")
    review_notes = clean_error(_payload_value(body, "reviewNotes", "review_notes"))
    with db.session_scope() as s:
        row = s.get(SourceAnalysisReport, report_id)
        if row is None or row.user_id != uid:
            return _deny(HTTP_NOT_FOUND, SOURCE_ANALYSIS_NOT_FOUND)
        row.review_status = review_status
        row.review_notes = review_notes
        row.reviewed_at = None if review_status == REVIEW_OPEN else utcnow()
        payload = _source_analysis_payload(row)
        _emit_structured_activity(
            s,
            user,
            action=f"source-analysis-{review_status}",
            object_type="source_analysis",
            object_key=str(row.id),
            official_status=SYNC_EVOLVED_REAL,
            payload={"toolName": row.tool_name, "reviewStatus": review_status},
            title=row.tool_name or row.source_label or f"Source analysis #{row.id}",
        )
    return jsonify({"ok": True, "sourceAnalysis": payload})


@v1_bp.route("/v1/me/tools/")
@login_required
def v1_me_tools() -> Response:
    """Resolve Toolhub tools that may belong to the signed-in Toolhub user."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — login_required guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))

    with db.session_scope() as s:
        stored_claims = list(
            s.execute(select(ToolAuthorClaim).where(ToolAuthorClaim.toolhub_username == user.username)).scalars()
        )
    search_terms = _search_terms_for_user(user.username, stored_claims)
    candidates, errors = _candidate_tools_for_terms(search_terms)
    toolforge_candidates, toolforge_errors, toolforge_tool_names = _candidate_tools_for_toolforge_memberships(
        user.username
    )
    for tool_name, entry in toolforge_candidates.items():
        existing = candidates.get(tool_name)
        if existing is None:
            candidates[tool_name] = entry
            continue
        existing["tool"] = entry["tool"]
        existing["matchedAuthorNames"] = _dedupe_strings(
            [*existing["matchedAuthorNames"], *entry["matchedAuthorNames"]]
        )
        existing["searchTerms"] = _dedupe_strings([*existing["searchTerms"], *entry["searchTerms"]])
        if entry.get("evidenceUrl"):
            existing["evidenceUrl"] = entry["evidenceUrl"]
        if isinstance(entry.get("evidencePayload"), dict):
            existing["evidencePayload"] = {
                **(existing.get("evidencePayload") if isinstance(existing.get("evidencePayload"), dict) else {}),
                **entry["evidencePayload"],
            }
    errors.extend(toolforge_errors)

    if errors and not candidates and len(errors) == len(search_terms):
        resp = jsonify({"error": "official Toolhub is unavailable", "username": user.username, "errors": errors})
        resp.status_code = 502
        return resp

    claim_payloads = _record_candidate_provider_claims(user, candidates)
    claims_by_tool = _claims_by_tool(claim_payloads)
    discoveries_by_tool = toolinfo_discovery.ensure_pending_for_candidates(candidates)
    sources_by_tool = toolinfo_sources.sources_for_tools(list(candidates))
    groups = _resolver_groups(candidates, claims_by_tool, discoveries_by_tool, sources_by_tool)

    return jsonify(
        {
            "username": user.username,
            "searchTerms": search_terms,
            "toolforgeToolNames": toolforge_tool_names,
            "toolinfoDiscovery": discoveries_by_tool,
            "toolinfoSources": sources_by_tool,
            "counts": {"verified": len(groups["verified"]), "possible": len(groups["possible"])},
            "verified": groups["verified"],
            "possible": groups["possible"],
            "errors": errors,
        }
    )


@v1_bp.route("/v1/maintainers/tools/<name>/")
def v1_tool_maintainers(name: str) -> Response:
    """Return a public-safe derived maintainer summary for one tool."""
    if security.read_rate_limited(request.remote_addr):
        return _deny(HTTP_TOO_MANY, "rate limit exceeded")
    clean_name = _clean_name(name)
    if clean_name is None:
        return _bad("tool name is required")
    errors: list[str] = []
    with db.session_scope() as s:
        try:
            tool = toolhub.public_api_get(f"/api/tools/{quote(clean_name, safe='')}/")
            if isinstance(tool, dict):
                maintainer_index.replace_toolhub_metadata_edges(s, clean_name, tool)
        except Exception as exc:  # noqa: BLE001 - cached/local maintainer summaries should remain readable.
            errors.append(clean_error(str(exc)) or "official Toolhub is unavailable")
        maintainer_index.sync_author_claim_edges(s, tool_names=[clean_name])
        summary = maintainer_index.public_tool_summary(s, clean_name)
    if errors:
        summary["errors"] = errors
    return jsonify(summary)


@v1_bp.route("/v1/people/tools/<name>/")
def v1_tool_people(name: str) -> Response:
    """Return the normalized people/relationship view for one tool."""
    return v1_tool_maintainers(name)


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


@v1_bp.route("/v1/issue-reports/", methods=["POST"])
@write_guard
def v1_issue_report() -> Response:
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
            return jsonify({"number": existing.issue_number, "url": existing.issue_url, "repository": existing.repository})
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
    name, fields, toolinfo_url, toolinfo_err = _validated_tool_write(value, route_name)
    if toolinfo_err is not None:
        return toolinfo_err
    assert name is not None  # noqa: S101 - _validated_tool_write returned no denial
    assert fields is not None  # noqa: S101 - _validated_tool_write returned no denial
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
            _emit_structured_activity(
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
        _emit_structured_activity(
            s,
            user,
            action=action,
            object_type="tool",
            object_key=name,
            official_status=SYNC_LOCAL_FALLBACK,
            payload=_with_crawler_fetch(
                {"lastError": attempt["lastError"], "toolhubResponse": attempt["details"], "local": local},
                crawler_fetch,
            ),
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
    raw_url = value.get("url")
    error = _url_validation_message(raw_url, label="crawler URL")
    if error is not None:
        return _url_validation_bad("url", error)
    url = str(raw_url).strip()
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


@v1_bp.route("/v1/crawler/toolinfo-discovery/", methods=["POST"])
@write_guard
def discover_toolinfo_url() -> Response:
    """Find a toolinfo.json URL from a tool homepage/root URL."""
    value, err = _json_object_body()
    if err is not None:
        return err
    assert value is not None  # noqa: S101 - err covers non-dict bodies
    raw_url = _payload_value(value, "url", "baseUrl")
    error = _url_validation_message(raw_url, label="tool URL")
    if error is not None:
        return _url_validation_bad("url", error)
    _require_policy_or_abort(authz.ACTION_TOOLHUB_WRITE)
    return jsonify(toolinfo_discovery.discover_toolinfo_url(str(raw_url)))


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
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_READ, authz.Resource(owner_user_id=uid))
    username = user.username
    with db.session_scope() as s:
        author_claims = [
            _claim_payload(row)
            for row in s.execute(
                select(ToolAuthorClaim)
                .where(ToolAuthorClaim.toolhub_username == username)
                .order_by(
                    ToolAuthorClaim.tool_name,
                    ToolAuthorClaim.author_name,
                    ToolAuthorClaim.verification_method,
                )
            ).scalars()
        ]
        author_keys = [
            _author_key_payload(row)
            for row in s.execute(
                select(ToolAuthorKey)
                .where(ToolAuthorKey.toolhub_username == username)
                .order_by(ToolAuthorKey.created_at, ToolAuthorKey.id)
            ).scalars()
        ]
        source_analysis_reports = [
            _source_analysis_payload(row)
            for row in s.execute(
                select(SourceAnalysisReport)
                .where(SourceAnalysisReport.user_id == uid)
                .order_by(SourceAnalysisReport.created_at, SourceAnalysisReport.id)
            ).scalars()
        ]
        maintainer_edges = [
            maintainer_index.public_edge_payload(row)
            | {
                "toolName": row.tool_name,
                "authorName": row.author_name,
                "checkedAt": _iso(row.checked_at),
                "expiresAt": _iso(row.expires_at),
            }
            for row in s.execute(
                select(ToolMaintainerEdge)
                .where(ToolMaintainerEdge.toolhub_username == username)
                .order_by(ToolMaintainerEdge.tool_name, ToolMaintainerEdge.method)
            ).scalars()
        ]
        maintainer_key = maintainer_index.maintainer_key(toolhub_username=username)
        maintainer_activity = maintainer_index.activity_payload(s.get(MaintainerActivityRollup, maintainer_key))
    return jsonify(
        {
            "exportedAt": _iso(utcnow()),
            "user": {"username": username},
            "overlay": _assemble_overlay(uid),
            "authorClaims": author_claims,
            "authorKeys": author_keys,
            "maintainerActivity": maintainer_activity,
            "maintainerEdges": maintainer_edges,
            "sourceAnalysisReports": source_analysis_reports,
        }
    )


@v1_bp.route("/v1/user/evolved-data/", methods=["DELETE"])
@write_guard
def v1_user_delete_evolved_data() -> Response:
    """Delete the caller's local Evolved data without touching official Toolhub."""
    uid = current_user_id()
    assert uid is not None  # noqa: S101 — write_guard guarantees this
    user = _require_policy_or_abort(authz.ACTION_PRIVATE_DELETE, authz.Resource(owner_user_id=uid))
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
            "sourceAnalysisReports": SourceAnalysisReport,
        }.items():
            count = s.execute(select(func.count()).select_from(model).where(model.user_id == uid)).scalar_one()
            deleted[key] = int(count)
            s.execute(delete(model).where(model.user_id == uid))
        health_count = s.execute(
            select(func.count()).select_from(ToolHealthTarget).where(ToolHealthTarget.created_by_user_id == uid)
        ).scalar_one()
        deleted["healthTargets"] = int(health_count)
        s.execute(delete(ToolHealthTarget).where(ToolHealthTarget.created_by_user_id == uid))
        author_claim_count = s.execute(
            select(func.count()).select_from(ToolAuthorClaim).where(ToolAuthorClaim.toolhub_username == user.username)
        ).scalar_one()
        deleted["authorClaims"] = int(author_claim_count)
        s.execute(delete(ToolAuthorClaim).where(ToolAuthorClaim.toolhub_username == user.username))
        author_key_count = s.execute(
            select(func.count()).select_from(ToolAuthorKey).where(ToolAuthorKey.toolhub_username == user.username)
        ).scalar_one()
        deleted["authorKeys"] = int(author_key_count)
        s.execute(delete(ToolAuthorKey).where(ToolAuthorKey.toolhub_username == user.username))
        maintainer_edge_count = s.execute(
            select(func.count())
            .select_from(ToolMaintainerEdge)
            .where(ToolMaintainerEdge.toolhub_username == user.username)
        ).scalar_one()
        deleted["maintainerEdges"] = int(maintainer_edge_count)
        s.execute(delete(ToolMaintainerEdge).where(ToolMaintainerEdge.toolhub_username == user.username))
        maintainer_key = maintainer_index.maintainer_key(toolhub_username=user.username)
        maintainer_activity_count = s.execute(
            select(func.count())
            .select_from(MaintainerActivityRollup)
            .where(MaintainerActivityRollup.maintainer_key == maintainer_key)
        ).scalar_one()
        deleted["maintainerActivity"] = int(maintainer_activity_count)
        s.execute(delete(MaintainerActivityRollup).where(MaintainerActivityRollup.maintainer_key == maintainer_key))
    return jsonify({"ok": True, "deleted": deleted})


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


@v1_bp.route("/v1/graph/")
def v1_graph() -> Response:
    """Return a cached global graph derived from the local canonical catalog."""
    return _public_json_response(
        graph_payload.payload(
            limit=request.args.get("limit"),
            group_by=request.args.get("groupBy"),
        )
    )


@v1_bp.route("/v1/tools/summaries/")
def v1_tool_summaries() -> Response:
    """Return local Evolved health and maintainer summaries for visible tools."""
    names = _tool_names_from_request()
    if not names:
        return _public_json_response(
            {"count": 0, "results": {}, "cacheMeta": {}, "source": SOURCE_LOCAL, "syncStatus": SYNC_EVOLVED_REAL}
        )
    read = tool_summaries.summaries_for(names, _build_local_tool_summary)
    return _public_json_response(
        {
            "count": len(read.results),
            "results": read.results,
            "cacheMeta": read.cache_meta,
            "source": SOURCE_LOCAL,
            "syncStatus": SYNC_EVOLVED_REAL,
            "cachePolicy": {
                "canonical": False,
                "upstream": False,
                "summary": (
                    "Materialized local Evolved summaries only; stale rows are served immediately "
                    "and refreshed asynchronously."
                ),
            },
        }
    )


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
    """List approved media, or submit URL-based media metadata for moderation.

    No @write_guard here because GET is public: the POST half applies the guard
    itself inside _tool_media_post. An audit that reads decorators alone will
    score this route as an unauthenticated write, so check there before believing it.
    """
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
            "_schema": "/toolinfo/1.2.2",
        }

    feed = [entry(name, rec) for name, rec in merged.items() if str(rec.get("url") or "").startswith("https://")]
    return jsonify(feed)
